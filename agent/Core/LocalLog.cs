using System.Text;

namespace SinavAjan.Core;

/// <summary>Everything the agent writes to disk lives under %LOCALAPPDATA%\SinavAjan\.</summary>
public static class AgentPaths
{
    public static string Root { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SinavAjan");

    public static string LogFile => Path.Combine(Root, "ajan.log");
    public static string StudentDir(string numara) => Path.Combine(Root, numara);
    public static string ExamFile(string numara) => Path.Combine(StudentDir(numara), "sinav.pka");
    public static string MetaFile(string numara) => Path.Combine(StudentDir(numara), "sinav.json");

    /// <summary>Deletes every file the agent has ever written. Returns an error text or null.</summary>
    public static string? DeleteAll()
    {
        LocalLog.Disable();
        try
        {
            if (Directory.Exists(Root)) Directory.Delete(Root, recursive: true);
            return null;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return ex.Message;
        }
    }
}

/// <summary>Small local log for troubleshooting. Never throws.</summary>
public static class LocalLog
{
    private const long MaxBytes = 2 * 1024 * 1024;
    private static readonly object Gate = new();
    private static bool _disabled;

    public static void Write(string message)
    {
        lock (Gate)
        {
            if (_disabled) return;
            try
            {
                Directory.CreateDirectory(AgentPaths.Root);
                var file = new FileInfo(AgentPaths.LogFile);
                if (file.Exists && file.Length > MaxBytes) file.Delete();
                File.AppendAllText(AgentPaths.LogFile,
                    $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {message}{Environment.NewLine}", Encoding.UTF8);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                // Logging must never break the exam.
            }
        }
    }

    public static void Disable()
    {
        lock (Gate) _disabled = true;
    }
}
