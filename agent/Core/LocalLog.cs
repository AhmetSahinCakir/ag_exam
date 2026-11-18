using System.Text;

namespace SinavAjan.Core;

/// <summary>
/// The agent's own files (a small log and a note about the exam file) live under
/// %LOCALAPPDATA%\SinavAjan\. The exam file itself is saved wherever the student chooses.
/// </summary>
public static class AgentPaths
{
    public static string Root { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SinavAjan");

    public static string LogFile => Path.Combine(Root, "ajan.log");
    public static string StudentDir(string numara) => Path.Combine(Root, numara);
    public static string MetaFile(string numara) => Path.Combine(StudentDir(numara), "sinav.json");
}

/// <summary>Small local log for troubleshooting. Never throws.</summary>
public static class LocalLog
{
    private const long MaxBytes = 2 * 1024 * 1024;
    private static readonly object Gate = new();

    public static void Write(string message)
    {
        lock (Gate)
        {
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
}
