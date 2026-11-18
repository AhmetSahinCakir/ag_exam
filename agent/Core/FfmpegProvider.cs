using System.IO.Compression;

namespace SinavAjan.Core;

/// <summary>
/// Makes ffmpeg.exe available as a file on disk.
///
/// The student gets a single file, SinavAjan.exe; ffmpeg travels inside it, gzip-compressed.
/// While the agent runs, ffmpeg is unpacked to %LOCALAPPDATA%\SinavAjan\ffmpeg.exe and removed
/// again when the agent closes. The unpacked file is held open for reading only, so it cannot
/// be replaced by another program while the exam is running.
///
/// A build without the embedded copy (development) uses ffmpeg.exe next to the agent.
/// </summary>
public sealed class FfmpegProvider : IDisposable
{
    public const string ResourceName = "ffmpeg.exe.gz";
    private const string FileName = "ffmpeg.exe";

    /// <summary>A failed unpack is not repeated more often than this.</summary>
    private static readonly TimeSpan RetryInterval = TimeSpan.FromSeconds(10);

    private readonly object _gate = new();
    private readonly Func<Stream?> _openEmbedded;
    private FileStream? _guard;
    private string? _lastProblem;
    private DateTime _lastFailureUtc = DateTime.MinValue;
    private bool _disposed;

    /// <summary>Where ffmpeg.exe is, or will be once <see cref="Ensure"/> has succeeded.</summary>
    public string FilePath { get; }

    /// <summary>True when ffmpeg comes from inside the agent rather than from its folder.</summary>
    public bool Embedded { get; }

    /// <param name="agentDirectory">Folder of SinavAjan.exe (used when nothing is embedded).</param>
    /// <param name="unpackDirectory">Folder the embedded copy is unpacked to.</param>
    /// <param name="openEmbedded">Opens the gzip-compressed embedded copy; null when there is none.</param>
    public FfmpegProvider(string agentDirectory, string unpackDirectory, Func<Stream?> openEmbedded)
    {
        _openEmbedded = openEmbedded;
        using (var probe = openEmbedded())
        {
            Embedded = probe != null;
        }
        FilePath = Embedded
            ? ChooseUnpackPath(unpackDirectory)
            : Path.Combine(agentDirectory, FileName);
    }

    /// <summary>
    /// Makes sure ffmpeg.exe is on disk: unpacks it on the first call and again if the file has
    /// disappeared since (for example removed by an antivirus). Cheap when nothing needs doing.
    /// </summary>
    /// <returns>null when ffmpeg.exe is ready; otherwise what went wrong.</returns>
    public string? Ensure()
    {
        lock (_gate)
        {
            if (_disposed) return "program kapanıyor";
            if (!Embedded) return File.Exists(FilePath) ? null : $"bulunamadı: {FilePath}";
            if (_guard != null && File.Exists(FilePath)) return null;
            if (_lastProblem != null && DateTime.UtcNow - _lastFailureUtc < RetryInterval) return _lastProblem;

            try
            {
                Unpack();
                _lastProblem = null;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidDataException)
            {
                _lastProblem = $"ffmpeg hazırlanamadı: {ex.Message}";
                _lastFailureUtc = DateTime.UtcNow;
            }
            return _lastProblem;
        }
    }

    private void Unpack()
    {
        _guard?.Dispose();
        _guard = null;

        Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
        var temp = FilePath + ".tmp";
        try
        {
            using (var source = _openEmbedded() ?? throw new IOException("gömülü kopya yok"))
            using (var gzip = new GZipStream(source, CompressionMode.Decompress))
            using (var target = new FileStream(temp, FileMode.Create, FileAccess.Write, FileShare.None, 1 << 20))
            {
                gzip.CopyTo(target);
                if (target.Length == 0) throw new InvalidDataException("gömülü kopya boş");
            }
            File.Move(temp, FilePath, overwrite: true);
        }
        catch
        {
            try
            {
                File.Delete(temp);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
            }
            throw;
        }

        // Read-only handle without write/delete sharing: the file can be run, but not changed,
        // renamed or deleted by anyone else until the agent closes.
        _guard = new FileStream(FilePath, FileMode.Open, FileAccess.Read, FileShare.Read);
    }

    /// <summary>
    /// Clears what an earlier run may have left behind (the agent was killed, the computer was
    /// switched off) and picks the file name for this run.
    /// </summary>
    private static string ChooseUnpackPath(string directory)
    {
        try
        {
            if (Directory.Exists(directory))
            {
                foreach (var leftover in Directory.EnumerateFiles(directory, "ffmpeg*.*"))
                {
                    try
                    {
                        File.Delete(leftover);
                    }
                    catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                    {
                        // Still in use; a different name is chosen below.
                    }
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
        }

        var path = Path.Combine(directory, FileName);
        for (var n = 2; File.Exists(path) && n < 10; n++)
        {
            path = Path.Combine(directory, $"ffmpeg-{n}.exe");
        }
        return path;
    }

    /// <summary>Removes the unpacked copy. Call after ffmpeg has been stopped.</summary>
    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed) return;
            _disposed = true;
            _guard?.Dispose();
            _guard = null;
            if (!Embedded) return;

            // ffmpeg may need a moment to exit before its file can be removed.
            for (var attempt = 0; attempt < 30; attempt++)
            {
                try
                {
                    File.Delete(FilePath);
                    File.Delete(FilePath + ".tmp");
                    return;
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Thread.Sleep(100);
                }
            }
            LocalLog.Write($"ffmpeg kopyası silinemedi: {FilePath}");
        }
    }
}
