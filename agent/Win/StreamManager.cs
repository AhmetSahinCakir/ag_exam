using System.ComponentModel;
using System.Diagnostics;
using SinavAjan.Core;

namespace SinavAjan.Win;

/// <summary>
/// Runs ffmpeg (hidden, inside a Job Object) and keeps it running: if the process dies it
/// is started again within 2 seconds; if it is alive but the stream stops advancing (dead
/// TCP connection) it is killed and restarted.
/// </summary>
public sealed class StreamManager : IDisposable
{
    private static readonly TimeSpan RestartDelay = TimeSpan.FromSeconds(2);
    private static readonly TimeSpan StallLimit = TimeSpan.FromSeconds(12);
    private static readonly TimeSpan PollInterval = TimeSpan.FromMilliseconds(500);

    private readonly object _gate = new();
    private readonly string _ffmpegPath;
    private readonly Func<string?>? _prepare;
    private readonly JobObject _job = new();
    private readonly Queue<string> _stderr = new();

    private List<string> _args = new();
    private string _logArgs = "";
    private Process? _process;
    private CancellationTokenSource? _cts;
    private Task? _watchdog;
    private DateTime _lastStartUtc = DateTime.MinValue;
    private DateTime _lastProgressUtc = DateTime.MinValue;
    private long _lastFrame = -1;
    private bool _missingReported;

    /// <summary>ffmpeg was (re)started after it had already been running. Argument: reason.</summary>
    public event Action<string>? Restarted;

    /// <summary>ffmpeg.exe is missing or cannot be executed. Raised once.</summary>
    public event Action<string>? Missing;

    /// <param name="ffmpegPath">Full path of ffmpeg.exe.</param>
    /// <param name="prepare">
    /// Called before every start; puts ffmpeg.exe in place if needed. Returns null when the
    /// file is ready, otherwise what went wrong.
    /// </param>
    public StreamManager(string ffmpegPath, Func<string?>? prepare = null)
    {
        _ffmpegPath = ffmpegPath;
        _prepare = prepare;
    }

    /// <summary>True while ffmpeg runs and frames are actually going out.</summary>
    public bool IsAlive
    {
        get
        {
            lock (_gate)
            {
                return _process is { HasExited: false }
                       && DateTime.UtcNow - _lastProgressUtc < StallLimit;
            }
        }
    }

    public void Start(StreamSettings settings)
    {
        Stop();
        lock (_gate)
        {
            _args = FfmpegCommand.Build(settings);
            _logArgs = FfmpegCommand.ForLog(_args, settings.Pass);
            _cts = new CancellationTokenSource();
            _watchdog = Task.Run(() => WatchAsync(_cts.Token));
        }
    }

    public void Stop()
    {
        CancellationTokenSource? cts;
        Task? watchdog;
        lock (_gate)
        {
            cts = _cts;
            watchdog = _watchdog;
            _cts = null;
            _watchdog = null;
        }
        if (cts == null) return;
        cts.Cancel();
        try
        {
            watchdog?.Wait(TimeSpan.FromSeconds(3));
        }
        catch (AggregateException)
        {
        }
        KillProcess();
        cts.Dispose();
    }

    private async Task WatchAsync(CancellationToken ct)
    {
        var everStarted = false;
        while (!ct.IsCancellationRequested)
        {
            string? restartReason = null;
            bool needStart;
            lock (_gate)
            {
                if (_process == null)
                {
                    needStart = true;
                }
                else if (_process.HasExited)
                {
                    restartReason = $"ffmpeg kapandı (kod {SafeExitCode(_process)}){LastErrorLine()}";
                    needStart = true;
                }
                else if (DateTime.UtcNow - _lastProgressUtc > StallLimit
                         && DateTime.UtcNow - _lastStartUtc > StallLimit)
                {
                    restartReason = "yayın ilerlemiyor";
                    needStart = true;
                }
                else
                {
                    needStart = false;
                }
            }

            if (needStart)
            {
                KillProcess();
                var wait = RestartDelay - (DateTime.UtcNow - _lastStartUtc);
                if (wait > TimeSpan.Zero)
                {
                    try
                    {
                        await Task.Delay(wait, ct).ConfigureAwait(false);
                    }
                    catch (OperationCanceledException)
                    {
                        return;
                    }
                }
                if (ct.IsCancellationRequested) return;

                if (TryStartProcess())
                {
                    if (everStarted && restartReason != null)
                    {
                        LocalLog.Write($"ffmpeg yeniden başlatıldı: {restartReason}");
                        Restarted?.Invoke(restartReason);
                    }
                    everStarted = true;
                }
            }

            try
            {
                await Task.Delay(PollInterval, ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    private bool TryStartProcess()
    {
        _lastStartUtc = DateTime.UtcNow;
        var problem = _prepare?.Invoke();
        if (problem != null)
        {
            ReportMissing(problem);
            return false;
        }
        if (!File.Exists(_ffmpegPath))
        {
            ReportMissing($"bulunamadı: {_ffmpegPath}");
            return false;
        }

        var info = new ProcessStartInfo(_ffmpegPath)
        {
            UseShellExecute = false,
            CreateNoWindow = true, // hidden: no console window
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            WorkingDirectory = Path.GetDirectoryName(_ffmpegPath) ?? "",
        };
        foreach (var arg in _args) info.ArgumentList.Add(arg);

        Process process;
        try
        {
            process = Process.Start(info) ?? throw new InvalidOperationException("süreç başlatılamadı");
        }
        catch (Exception ex) when (ex is Win32Exception or InvalidOperationException or IOException)
        {
            ReportMissing(ex.Message);
            return false;
        }

        try
        {
            _job.Assign(process); // from now on ffmpeg cannot outlive the agent
        }
        catch (Win32Exception ex)
        {
            LocalLog.Write($"ffmpeg Job Object'e eklenemedi: {ex.Message}");
        }

        process.OutputDataReceived += (_, e) => OnProgressLine(process, e.Data);
        process.ErrorDataReceived += (_, e) => OnErrorLine(process, e.Data);
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        lock (_gate)
        {
            _process = process;
            _lastFrame = -1;
            _lastProgressUtc = DateTime.MinValue;
            _stderr.Clear();
        }
        LocalLog.Write($"ffmpeg başlatıldı (pid {process.Id}): {_logArgs}");
        return true;
    }

    private void OnProgressLine(Process source, string? line)
    {
        // "-progress pipe:1" prints key=value lines; "frame=123" grows while frames are sent.
        if (line == null || !line.StartsWith("frame=", StringComparison.Ordinal)) return;
        if (!long.TryParse(line.AsSpan(6).Trim(), out var frame)) return;
        lock (_gate)
        {
            if (!ReferenceEquals(source, _process)) return;
            if (frame > _lastFrame)
            {
                _lastFrame = frame;
                _lastProgressUtc = DateTime.UtcNow;
            }
        }
    }

    private void OnErrorLine(Process source, string? line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;
        lock (_gate)
        {
            if (!ReferenceEquals(source, _process)) return;
            _stderr.Enqueue(line.Trim());
            while (_stderr.Count > 10) _stderr.Dequeue();
        }
    }

    private string LastErrorLine()
    {
        // Called with _gate held.
        return _stderr.Count > 0 ? $": {_stderr.Last()}" : "";
    }

    private static string SafeExitCode(Process process)
    {
        try
        {
            return process.ExitCode.ToString();
        }
        catch (InvalidOperationException)
        {
            return "?";
        }
    }

    private void ReportMissing(string reason)
    {
        if (_missingReported) return;
        _missingReported = true;
        LocalLog.Write($"ffmpeg çalıştırılamadı: {reason}");
        Missing?.Invoke(reason);
    }

    private void KillProcess()
    {
        Process? process;
        lock (_gate)
        {
            process = _process;
            _process = null;
        }
        if (process == null) return;
        try
        {
            if (!process.HasExited)
            {
                process.Kill();
                process.WaitForExit(2000);
            }
        }
        catch (Exception ex) when (ex is InvalidOperationException or Win32Exception or NotSupportedException)
        {
        }
        finally
        {
            process.Dispose();
        }
    }

    public void Dispose()
    {
        Stop();
        _job.Dispose(); // closes the job handle: anything still inside is killed by Windows
    }
}
