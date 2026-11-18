using SinavAjan.Core;
using SinavAjan.Win;

namespace SinavAjan;

public enum Phase
{
    /// <summary>Logged in, streaming, waiting for the teacher. The allowlist is NOT applied.</summary>
    Waiting,

    /// <summary>The teacher shared the exam file: warning + countdown before programs are closed.</summary>
    Countdown,

    /// <summary>Exam in progress: the allowlist is enforced and the exam file can be downloaded.</summary>
    Running,

    /// <summary>
    /// The teacher ended the exam but this student has not handed in yet. Nothing closes:
    /// the screen is still streamed, the allowlist is still enforced and the file can still
    /// be handed in - it is then recorded as late.
    /// </summary>
    Ended,

    /// <summary>Handed in, or the teacher closed the exam: nothing runs any more.</summary>
    Finished,
}

public sealed record FinishInfo(string Title, string Message, bool Success);

/// <summary>A file the student picked for submission, already read and checked.</summary>
/// <param name="Error">Non-empty when the file could not be read at all.</param>
public sealed record SubmitCandidate(string Path, byte[] Bytes, string Sha256, DateTime LastWriteLocal,
    SubmitProblem Problem, string Error = "");

/// <summary>
/// The exam session after login. Owns the heartbeat, the screen stream and the
/// application control, and follows the server's exam state (WAITING → RUNNING → ENDED).
/// The exam starts when the teacher shares the exam file; the student then downloads it to
/// a place of their choice, and at the end picks the file to submit.
/// All members must be used from the UI thread; events are raised on the UI thread.
/// </summary>
public sealed class ExamController : IDisposable
{
    private readonly ApiClient _api;
    private readonly AgentConfig _config;
    private readonly LoginRequest _login;
    private readonly string _ffmpegPath;
    private readonly string _windowsDir;
    private readonly CancellationTokenSource _cts = new();
    private readonly EventQueue _events;
    private readonly Enforcer _enforcer = new();
    private readonly StreamManager _stream;
    private readonly Dictionary<string, DateTime> _noticeTimes = new(StringComparer.OrdinalIgnoreCase);

    private SynchronizationContext _ui = new();
    private LoginResponse _session;
    private Policy _policy;
    private SettingsDto _settings;
    private ForegroundSnapshot? _foreground;
    private int _monitors = 1;
    private string _examStateSeen = "";
    private DateTime _offlineSinceUtc;
    private string _examFilePath = "";
    private long _baselineTicks;
    private string _examSha = "";
    private string _submittedSha = "";
    private DateTime? _otherDesktopSinceUtc;
    private double _endsAt;            // server clock; 0 = no time limit
    private double _scheduledAt;       // server clock; 0 = no planned start
    private double _serverClockAhead;  // seconds the server's clock is ahead of this computer's
    private bool _lastMinutesNoticed;
    private int _otherDesktopReadings;
    private bool _ending;
    private bool _submitting;
    private bool _downloading;
    private bool _policyRefreshing;
    private bool _sessionProblemNotified;
    private int _restartCount;
    private DateTime _restartReportedUtc = DateTime.MinValue;

    public Phase Phase { get; private set; } = Phase.Waiting;
    public bool Online { get; private set; } = true;
    public string ExamId { get; private set; } = "";
    public DateTime CountdownEndsUtc { get; private set; }

    /// <summary>Short progress/problem text for the student.</summary>
    public string StatusNote { get; private set; } = "";

    /// <summary>Non-empty when the server refuses this session (e.g. same number elsewhere).</summary>
    public string SessionProblem { get; private set; } = "";

    public string Numara => _session.Student.Numara;
    public string FullName => $"{_session.Student.Ad} {_session.Student.Soyad}".Trim();
    public bool StreamAlive => _stream.IsAlive;
    public bool Submitting => _submitting;
    public bool Downloading => _downloading;

    /// <summary>Where the student saved the exam file; empty until it has been downloaded.</summary>
    public string ExamFilePath => _examFilePath;

    public bool ExamFileReady => _examFilePath.Length > 0;

    /// <summary>A file can be handed in: during the exam, and (late) after it has ended.</summary>
    public bool CanSubmit => Phase is Phase.Running or Phase.Ended;

    /// <summary>Seconds left when the teacher set a time limit; null when there is none.</summary>
    public double? RemainingSeconds => _endsAt > 0 && Phase is Phase.Countdown or Phase.Running
        ? Math.Max(0, _endsAt - (NetInfo.UnixNow() + _serverClockAhead))
        : null;

    /// <summary>
    /// Called by the window twice a second. When the last ten minutes begin the student gets
    /// one notice; nothing else happens (the panel is not brought to the front).
    /// </summary>
    public void TickClock()
    {
        if (Phase != Phase.Running || RemainingSeconds is not { } left) return;
        if (!ExamClock.InLastMinutes(left))
        {
            _lastMinutesNoticed = false; // extra time was given: warn again when it runs low
            return;
        }
        if (_lastMinutesNoticed) return;
        _lastMinutesNoticed = true;
        Notice?.Invoke("Son 10 dakika", "Sınavın bitmesine 10 dakikadan az kaldı. Dosyanızı kaydedip teslim etmeyi unutmayın.", 12);
    }

    /// <summary>The time of day the teacher planned the exam to start; null when nothing is planned.</summary>
    public DateTime? PlannedStart => _scheduledAt > 0 && Phase == Phase.Waiting
        ? DateTimeOffset.FromUnixTimeMilliseconds((long)(_scheduledAt * 1000)).LocalDateTime
        : null;

    public event Action? Changed;
    /// <summary>A short notice for the student: (headline, text, seconds on screen).</summary>
    public event Action<string, string, int>? Notice;

    private const int NoticeSeconds = 7;
    public event Action<FinishInfo>? Finished;

    public ExamController(ApiClient api, AgentConfig config, LoginRequest login, LoginResponse session,
        FfmpegProvider ffmpeg)
    {
        _api = api;
        _config = config;
        _login = login;
        _session = session;
        _settings = session.Settings;
        _ffmpegPath = ffmpeg.FilePath;
        _windowsDir = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        _policy = BuildPolicy(session.Allowlist);
        _submittedSha = session.Student.LastSha256 ?? "";
        _events = new EventQueue(api);
        _stream = new StreamManager(_ffmpegPath, ffmpeg.Ensure);
    }

    private Policy BuildPolicy(PolicyDto dto) =>
        new(dto, _windowsDir, new[] { Environment.ProcessPath, _ffmpegPath });

    /// <summary>Starts streaming, heartbeat and monitoring. Call on the UI thread.</summary>
    public void Start()
    {
        _ui = SynchronizationContext.Current ?? throw new InvalidOperationException("UI thread required");

        _stream.Restarted += reason => _ui.Post(_ => OnStreamRestarted(reason), null);
        _stream.Missing += reason => _ui.Post(_ => OnStreamMissing(reason), null);
        // The screen stream starts right after login, already in the waiting phase.
        _stream.Start(StreamSettings.From(_config.Stream, _session.Stream));

        _ = Task.Run(() => _events.RunAsync(_cts.Token));
        _ = HeartbeatLoopAsync();
        _ = EnforceLoopAsync();
        ApplyStatus(_session);
    }

    // ------------------------------------------------------------------ heartbeat

    private async Task HeartbeatLoopAsync()
    {
        var token = _cts.Token;
        while (!token.IsCancellationRequested && Phase != Phase.Finished)
        {
            try
            {
                var foreground = _foreground;
                var status = await _api.HeartbeatAsync(new HeartbeatRequest
                {
                    FgProcess = foreground?.Name ?? "",
                    FgPath = foreground?.Path ?? "",
                    FgTitle = foreground?.Title ?? "",
                    Monitors = _monitors,
                    FfmpegAlive = _stream.IsAlive,
                    ExamStateSeen = _examStateSeen,
                }, token);
                MarkOnline();
                ApplyStatus(status);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (ApiException ex) when (ex.Status == 401)
            {
                // The server no longer knows this session (restarted or replaced): log in again.
                await ReloginAsync(token);
            }
            catch (ApiException ex) when (ex.IsNetwork)
            {
                MarkOffline();
            }
            catch (ApiException ex)
            {
                LocalLog.Write($"heartbeat hatası: {ex.Message}");
            }
            catch (Exception ex)
            {
                LocalLog.Write($"heartbeat beklenmeyen hata: {ex}");
            }

            try
            {
                await Task.Delay(TimeSpan.FromSeconds(Math.Clamp(_settings.HeartbeatIntervalS, 1, 10)), token);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    private async Task ReloginAsync(CancellationToken token)
    {
        try
        {
            var session = await _api.LoginAsync(_login, token);
            _api.Token = session.Token;
            _session = session;
            _settings = session.Settings;
            _policy = BuildPolicy(session.Allowlist);
            if (SessionProblem.Length > 0)
            {
                SessionProblem = "";
                _sessionProblemNotified = false;
                Changed?.Invoke();
            }
            LocalLog.Write("oturum yenilendi");
            MarkOnline();
            ApplyStatus(session);
        }
        catch (OperationCanceledException)
        {
        }
        catch (ApiException ex) when (ex.IsNetwork)
        {
            MarkOffline();
        }
        catch (ApiException ex)
        {
            SessionProblem = ex.Message;
            Changed?.Invoke();
            if (!_sessionProblemNotified)
            {
                _sessionProblemNotified = true;
                Notice?.Invoke("Oturum yenilenemedi", ex.Message, NoticeSeconds);
            }
        }
    }

    private void MarkOffline()
    {
        if (!Online) return;
        Online = false;
        _offlineSinceUtc = DateTime.UtcNow;
        LocalLog.Write("sunucuya ulaşılamıyor");
        Changed?.Invoke();
    }

    private void MarkOnline()
    {
        if (Online) return;
        Online = true;
        var seconds = Math.Round((DateTime.UtcNow - _offlineSinceUtc).TotalSeconds);
        _events.Enqueue("reconnect", new Dictionary<string, object?> { ["seconds"] = seconds });
        Changed?.Invoke();
    }

    private void ApplyStatus(ExamStatus status)
    {
        if (Phase == Phase.Finished) return;
        _examStateSeen = status.ExamState;
        if (status.ServerTime > 0) _serverClockAhead = status.ServerTime - NetInfo.UnixNow();
        if (status.EndsAt != _endsAt || status.ScheduledAt != _scheduledAt)
        {
            _endsAt = status.EndsAt;
            _scheduledAt = status.ScheduledAt;
            Changed?.Invoke();
        }
        if (!string.IsNullOrEmpty(status.AllowlistVersion) && status.AllowlistVersion != _policy.Version
                                                          && !_policyRefreshing)
        {
            _ = RefreshPolicyAsync();
        }

        if (_ending) return;
        var inExam = Phase is Phase.Countdown or Phase.Running or Phase.Ended;
        if (status.ExamState == "CLOSED")
        {
            // The teacher closed the exam for everybody ("Yeni sınav" / "Sistemi kapat").
            _ = CloseExamAsync();
        }
        else if (status.ExamState == "RUNNING" && Phase == Phase.Waiting)
        {
            _ = BeginExamAsync(status.ExamId);
        }
        else if (status.Submitted && CanSubmit && !_submitting)
        {
            // The teacher's computer has this student's file in its submissions folder
            // (it checks the folder itself): nothing is left to do here.
            _ = FinishAsync(new FinishInfo("Teslim alındı", "Dosyanız teslim alındı.", true));
        }
        else if (status.ExamState == "ENDED" && Phase != Phase.Ended)
        {
            EnterEndedPhase(status.ExamId);
        }
        else if (status.ExamState == "WAITING" && inExam)
        {
            // The teacher's computer no longer knows this exam (a new one was prepared).
            _ = FinishAsync(new FinishInfo("Sınav kapatıldı", "Dosyanızı teslim etmediniz.", false));
        }
    }

    /// <summary>
    /// The teacher ended the exam and nothing was handed in from here yet. The program stays
    /// open so that the student can still hand in; that submission is recorded as late.
    /// </summary>
    private void EnterEndedPhase(string examId)
    {
        if (ExamId.Length == 0) ExamId = examId;
        RestoreDownloadedFile(examId);
        Phase = Phase.Ended; // still streamed and controlled, see EnforceLoopAsync
        LocalLog.Write("sınav bitti; teslim bekleniyor (geç teslim)");
        Changed?.Invoke();
        // Stays on screen longer: the panel itself is not pushed to the front.
        Notice?.Invoke("Sınav bitti", "Dosyanızı hemen teslim edin. Teslim geç olarak kaydedilecek.", 20);
    }

    private async Task RefreshPolicyAsync()
    {
        _policyRefreshing = true;
        try
        {
            var config = await _api.GetConfigAsync(_cts.Token);
            _policy = BuildPolicy(config.Allowlist);
            _settings = config.Settings;
            LocalLog.Write($"izin listesi güncellendi (sürüm {_policy.Version})");
        }
        catch (Exception ex) when (ex is ApiException or OperationCanceledException)
        {
            // Will be retried on the next heartbeat.
        }
        finally
        {
            _policyRefreshing = false;
        }
    }

    // --------------------------------------------------------------- exam start

    private async Task BeginExamAsync(string examId)
    {
        ExamId = examId;
        Phase = Phase.Countdown;
        var seconds = Math.Clamp(_settings.KillCountdownS, 0, 120);
        CountdownEndsUtc = DateTime.UtcNow.AddSeconds(seconds);
        LocalLog.Write($"sınav başladı (kimlik {examId})");
        RestoreDownloadedFile(examId);
        Changed?.Invoke();

        try
        {
            await Task.Delay(TimeSpan.FromSeconds(seconds), _cts.Token);
        }
        catch (OperationCanceledException)
        {
            return;
        }
        if (Phase != Phase.Countdown || _ending) return;

        Phase = Phase.Running; // the enforcement loop picks this up within a second
        _events.Enqueue("enforcement_started");
        Changed?.Invoke();
    }

    /// <summary>
    /// The agent was restarted during this exam: continue with the file the student already
    /// downloaded (and worked on) instead of asking them to download it again.
    /// </summary>
    private void RestoreDownloadedFile(string examId)
    {
        if (ExamFileReady) return;
        var meta = ExamFiles.ReadMeta(Numara);
        if (meta == null || meta.ExamId != examId || meta.Path.Length == 0 || !File.Exists(meta.Path)) return;
        _examFilePath = meta.Path;
        _baselineTicks = meta.BaselineWriteTicks;
        _examSha = meta.ExamSha256;
        if (_submittedSha.Length == 0) _submittedSha = meta.SubmittedSha256;
        _events.Enqueue("exam_file_kept");
    }

    /// <summary>
    /// Downloads the exam file to the location the student picked. Returns null on success,
    /// otherwise an error text for the student.
    /// </summary>
    public async Task<string?> DownloadExamFileAsync(string targetPath)
    {
        if (Phase != Phase.Running || _ending) return "Sınav dosyası şu anda indirilemez.";
        if (_downloading) return "İndirme zaten sürüyor.";
        _downloading = true;
        Changed?.Invoke();
        try
        {
            var bytes = await _api.DownloadExamFileAsync(_cts.Token);
            await File.WriteAllBytesAsync(targetPath, bytes, _cts.Token);
            _examFilePath = targetPath;
            _baselineTicks = File.GetLastWriteTimeUtc(targetPath).Ticks;
            _examSha = NetInfo.Sha256Hex(bytes);
            ExamFiles.WriteMeta(Numara, new ExamFileMeta
            {
                ExamId = ExamId,
                Path = targetPath,
                BaselineWriteTicks = _baselineTicks,
                SubmittedSha256 = _submittedSha,
                ExamSha256 = _examSha,
            });
            LocalLog.Write($"sınav dosyası indirildi: {targetPath}");
            _events.Enqueue("exam_file_ready", new Dictionary<string, object?> { ["size"] = bytes.Length });
            return null;
        }
        catch (ApiException ex)
        {
            return ex.Message;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or NotSupportedException)
        {
            return $"Dosya bu konuma kaydedilemedi: {ex.Message}";
        }
        catch (OperationCanceledException)
        {
            return "İşlem iptal edildi.";
        }
        finally
        {
            _downloading = false;
            if (Phase != Phase.Finished) Changed?.Invoke();
        }
    }

    // ---------------------------------------------------------- application control

    private async Task EnforceLoopAsync()
    {
        var token = _cts.Token;
        var wasEnforcing = false;
        while (!token.IsCancellationRequested && Phase != Phase.Finished)
        {
            var policy = _policy;
            // Until the file is handed in the student is still in the exam, also after its end.
            var enforce = Phase is Phase.Running or Phase.Ended;
            var tolerance = Math.Clamp(_settings.ForegroundToleranceS, 1, 120);
            var reset = enforce && !wasEnforcing;
            wasEnforcing = enforce;
            try
            {
                var tick = await Task.Run(() =>
                {
                    if (reset) _enforcer.Reset();
                    return _enforcer.Tick(policy, enforce, tolerance);
                }, token);

                _foreground = tick.Foreground;
                _monitors = tick.Monitors;
                foreach (var item in tick.Events) _events.Enqueue(item.Type, item.Details);
                foreach (var program in tick.ClosedPrograms) NotifyClosed(program);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception ex)
            {
                LocalLog.Write($"denetim döngüsünde hata: {ex}");
            }

            try
            {
                await Task.Delay(1000, token);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    private void NotifyClosed(string program)
    {
        // The same program reopening repeatedly should not flood the student with popups.
        if (_noticeTimes.TryGetValue(program, out var last) && DateTime.UtcNow - last < TimeSpan.FromSeconds(10)) return;
        _noticeTimes[program] = DateTime.UtcNow;
        Notice?.Invoke("Program kapatıldı", $"{program} sınav sırasında kullanılamaz.", NoticeSeconds);
    }

    private void OnStreamRestarted(string reason)
    {
        if (Phase == Phase.Finished) return;
        _restartCount++;
        if (DateTime.UtcNow - _restartReportedUtc < TimeSpan.FromSeconds(30)) return;
        _events.Enqueue("ffmpeg_restart", new Dictionary<string, object?>
        {
            ["reason"] = reason,
            ["count"] = _restartCount,
        });
        _restartCount = 0;
        _restartReportedUtc = DateTime.UtcNow;
    }

    private void OnStreamMissing(string reason)
    {
        if (Phase == Phase.Finished) return;
        _events.Enqueue("ffmpeg_missing", new Dictionary<string, object?> { ["reason"] = reason });
        Notice?.Invoke("Ekran aktarımı başlatılamadı",
            "Antivirüs programınız engellemiş olabilir. Sınavı yapan kişiye haber verin.", 12);
    }

    // ------------------------------------------------------------------- submit

    /// <summary>
    /// Reads the file the student picked in the "Teslim et" dialog and checks it: is it a
    /// Packet Tracer file, is it the untouched exam file, was it saved before this exam?
    /// </summary>
    public async Task<SubmitCandidate> InspectSubmissionAsync(string path)
    {
        try
        {
            var info = new FileInfo(path);
            var early = SubmissionRules.Check(info.Name, info.Length, "", info.LastWriteTimeUtc.Ticks, "", 0);
            if (SubmissionRules.Blocks(early))
            {
                return new SubmitCandidate(path, Array.Empty<byte>(), "", info.LastWriteTime, early);
            }
            var bytes = await Task.Run(() => ExamFiles.ReadShared(path));
            var sha = NetInfo.Sha256Hex(bytes);
            var problem = SubmissionRules.Check(info.Name, bytes.LongLength, sha, info.LastWriteTimeUtc.Ticks,
                _examSha, _baselineTicks);
            return new SubmitCandidate(path, bytes, sha, info.LastWriteTime, problem);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or NotSupportedException
                                       or ArgumentException)
        {
            return new SubmitCandidate(path, Array.Empty<byte>(), "", DateTime.MinValue, SubmitProblem.None,
                $"Dosya okunamadı: {ex.Message}");
        }
    }

    /// <summary>Uploads the file the student picked. Returns null on success, else an error text.</summary>
    public async Task<string?> SubmitAsync(SubmitCandidate candidate)
    {
        if (_submitting || _ending || Phase == Phase.Finished) return "Teslim zaten sürüyor.";
        _submitting = true;
        Changed?.Invoke();
        try
        {
            var response = await _api.SubmitAsync(candidate.Bytes, candidate.Sha256,
                Path.GetFileName(candidate.Path), candidate.Problem == SubmitProblem.SavedBeforeDownload, _cts.Token);
            RememberSubmitted(response.Sha256);
            LocalLog.Write($"teslim edildi: {candidate.Path} -> {response.Filename}");

            var message = "Dosyanız teslim alındı.";
            if (response.Late)
            {
                message += "\r\n\r\nSınav bittikten sonra teslim ettiğiniz için geç teslim olarak kaydedildi.";
            }
            if (!string.Equals(candidate.Sha256, response.Sha256, StringComparison.OrdinalIgnoreCase))
            {
                message += "\r\n\r\nUYARI: Teslim edilen dosya bu bilgisayardakiyle aynı görünmüyor. " +
                           "Durumu hemen bildirin.";
            }
            await FinishAsync(new FinishInfo("Teslim alındı", message, true));
            return null;
        }
        catch (ApiException ex)
        {
            _events.Enqueue("submit_failed", new Dictionary<string, object?> { ["error"] = ex.Message });
            return ex.Message;
        }
        catch (OperationCanceledException)
        {
            return "İşlem iptal edildi.";
        }
        finally
        {
            _submitting = false;
            if (Phase != Phase.Finished) Changed?.Invoke();
        }
    }

    // ---------------------------------------------------------- virtual desktops

    /// <summary>
    /// Called by the window twice a second: is the exam panel on the virtual desktop the
    /// student is looking at? Switching to another desktop (Win+Ctrl+→) is reported.
    /// </summary>
    public void ReportDesktop(bool panelOnCurrentDesktop)
    {
        if (!CanSubmit || _ending) return;
        if (!panelOnCurrentDesktop)
        {
            // Two readings in a row, so that a switch animation never counts.
            if (_otherDesktopSinceUtc != null || ++_otherDesktopReadings < 2) return;
            _otherDesktopSinceUtc = DateTime.UtcNow;
            LocalLog.Write("başka bir sanal masaüstüne geçildi");
            _events.Enqueue("desktop_switch");
            Notice?.Invoke("Başka bir masaüstündesiniz",
                "Bu durum kaydedildi. Sınav masaüstüne geri dönün.", NoticeSeconds);
            return;
        }
        _otherDesktopReadings = 0;
        if (_otherDesktopSinceUtc is not { } since) return;
        _otherDesktopSinceUtc = null;
        _events.Enqueue("desktop_return", new Dictionary<string, object?>
        {
            ["seconds"] = Math.Round((DateTime.UtcNow - since).TotalSeconds),
        });
    }

    private void RememberSubmitted(string sha)
    {
        _submittedSha = sha;
        var meta = ExamFiles.ReadMeta(Numara);
        if (meta == null) return;
        meta.SubmittedSha256 = sha;
        ExamFiles.WriteMeta(Numara, meta);
    }

    // ----------------------------------------------------------------- exam end

    /// <summary>
    /// The teacher closed the exam for everybody ("Yeni sınav" or "Sistemi kapat"): the program
    /// stops. Nothing is ever handed in automatically - only the student hands in a file.
    /// </summary>
    private async Task CloseExamAsync()
    {
        _ending = true;
        var inExam = Phase is Phase.Countdown or Phase.Running or Phase.Ended;
        StatusNote = "Sınav kapatılıyor…";
        LocalLog.Write("sınav kapatıldı");
        Changed?.Invoke();

        // Let a submission the student already started finish first.
        for (var i = 0; i < 100 && (_submitting || _downloading); i++) await Task.Delay(100);
        if (Phase == Phase.Finished) return;

        var info = inExam
            ? new FinishInfo("Sınav kapatıldı", "Dosyanızı teslim etmediniz.", false)
            : new FinishInfo("Sınav kapatıldı", "Bu pencereyi kapatabilirsiniz.", true);
        await FinishAsync(info);
    }

    // ------------------------------------------------------------------ shutdown

    private async Task FinishAsync(FinishInfo info)
    {
        if (Phase == Phase.Finished) return;
        Phase = Phase.Finished; // application control and heartbeat stop here
        await _events.DrainAsync(TimeSpan.FromSeconds(2));
        _cts.Cancel();
        _stream.Stop(); // ffmpeg is closed
        LocalLog.Write($"bitti: {info.Title}");
        Changed?.Invoke();
        Finished?.Invoke(info);
    }

    /// <summary>The student chose to close the agent: tell the server (best effort).</summary>
    public async Task ExitByUserAsync()
    {
        if (Phase == Phase.Finished) return;
        var phase = Phase.ToString();
        Phase = Phase.Finished;
        await _events.SendNowAsync("agent_exit", new Dictionary<string, object?> { ["phase"] = phase },
            TimeSpan.FromSeconds(1.5));
        _cts.Cancel();
        _stream.Stop();
    }

    public void Dispose()
    {
        _cts.Cancel();
        _stream.Dispose();
    }
}
