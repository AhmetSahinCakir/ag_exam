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
