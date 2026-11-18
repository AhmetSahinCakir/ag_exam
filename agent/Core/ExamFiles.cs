using System.Text.Json;
using System.Text.Json.Serialization;

namespace SinavAjan.Core;

/// <summary>
/// Small note the agent keeps about the exam file: which exam it belongs to and where the
/// student chose to save it. It lets a restarted agent continue with the same file.
/// </summary>
public sealed class ExamFileMeta
{
    [JsonPropertyName("exam_id")] public string ExamId { get; set; } = "";

    /// <summary>Full path the student picked in the "save" dialog.</summary>
    [JsonPropertyName("path")] public string Path { get; set; } = "";

    /// <summary>Last-write time (UTC ticks) of the file right after the download.</summary>
    [JsonPropertyName("baseline_write_ticks")] public long BaselineWriteTicks { get; set; }

    /// <summary>SHA-256 of the last version the server confirmed.</summary>
    [JsonPropertyName("submitted_sha256")] public string SubmittedSha256 { get; set; } = "";

    /// <summary>SHA-256 of the exam file exactly as it was downloaded (before any work).</summary>
    [JsonPropertyName("exam_sha256")] public string ExamSha256 { get; set; } = "";
}

/// <summary>What is wrong with the file a student picked for submission.</summary>
public enum SubmitProblem
{
    None,

    // The file cannot be submitted at all.
    NotPka,
    Empty,
    TooBig,

    // The file can be submitted, but the student is asked first.
    SameAsExamFile,
    SavedBeforeDownload,
}

/// <summary>Texts about time that are shown to the student.</summary>
public static class ExamClock
{
    /// <summary>"Kalan süre: 34 dk", "Kalan süre: 1 sa 5 dk", "Kalan süre: 1 dakikadan az".</summary>
    public static string Remaining(double seconds)
    {
        if (seconds < 60) return "Kalan süre: 1 dakikadan az";
        var minutes = (int)Math.Ceiling(seconds / 60);
        return minutes >= 60
            ? $"Kalan süre: {minutes / 60} sa {minutes % 60} dk"
            : $"Kalan süre: {minutes} dk";
    }
}

/// <summary>Checks made on the student's computer before a file is uploaded.</summary>
public static class SubmissionRules
{
    public const long MaxUploadBytes = 50L * 1024 * 1024;

    /// <param name="fileName">Name of the picked file.</param>
    /// <param name="length">Its size in bytes.</param>
    /// <param name="sha256">Its SHA-256 (hex).</param>
    /// <param name="lastWriteUtcTicks">When it was last saved.</param>
    /// <param name="examSha256">SHA-256 of the exam file as downloaded ("" if unknown).</param>
    /// <param name="downloadedUtcTicks">When the exam file was downloaded (0 if unknown).</param>
    public static SubmitProblem Check(string fileName, long length, string sha256, long lastWriteUtcTicks,
        string examSha256, long downloadedUtcTicks)
    {
        if (!fileName.EndsWith(".pka", StringComparison.OrdinalIgnoreCase)) return SubmitProblem.NotPka;
        if (length == 0) return SubmitProblem.Empty;
        if (length > MaxUploadBytes) return SubmitProblem.TooBig;
        // Byte for byte the file the teacher shared: nothing was saved into it.
        if (examSha256.Length > 0 && string.Equals(sha256, examSha256, StringComparison.OrdinalIgnoreCase))
        {
            return SubmitProblem.SameAsExamFile;
        }
        // Last saved before this exam's file even existed here: most likely some other file.
        if (downloadedUtcTicks > 0 && lastWriteUtcTicks < downloadedUtcTicks) return SubmitProblem.SavedBeforeDownload;
        return SubmitProblem.None;
    }

    /// <summary>True when the file must not be uploaded.</summary>
    public static bool Blocks(SubmitProblem problem) =>
        problem is SubmitProblem.NotPka or SubmitProblem.Empty or SubmitProblem.TooBig;
}

public static class ExamFiles
{
    public static ExamFileMeta? ReadMeta(string numara)
    {
        try
        {
            var path = AgentPaths.MetaFile(numara);
            return File.Exists(path) ? JsonSerializer.Deserialize<ExamFileMeta>(File.ReadAllText(path)) : null;
        }
        catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    public static void WriteMeta(string numara, ExamFileMeta meta)
    {
        try
        {
            Directory.CreateDirectory(AgentPaths.StudentDir(numara));
            File.WriteAllText(AgentPaths.MetaFile(numara), JsonSerializer.Serialize(meta));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            LocalLog.Write($"sinav.json yazılamadı: {ex.Message}");
        }
    }

    /// <summary>Reads a file that another program (Packet Tracer) may still have open.</summary>
    public static byte[] ReadShared(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete);
        using var buffer = new MemoryStream();
        stream.CopyTo(buffer);
        return buffer.ToArray();
    }
}
