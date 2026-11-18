using System.Text.Json.Serialization;

namespace SinavAjan.Core;

/// <summary>Answer to the UDP discovery broadcast.</summary>
public sealed class DiscoveryReply
{
    [JsonPropertyName("ip")] public string Ip { get; set; } = "";
    [JsonPropertyName("port")] public int Port { get; set; } = 8000;
    [JsonPropertyName("sinif_adi")] public string SinifAdi { get; set; } = "";
    [JsonPropertyName("ogretmen_adi")] public string OgretmenAdi { get; set; } = "";

    /// <summary>Random per server start; the same server answers with the same id on every adapter.</summary>
    [JsonPropertyName("id")] public string Id { get; set; } = "";
}

/// <summary>A teacher server the agent can talk to.</summary>
public sealed class ServerInfo
{
    public string Host { get; init; } = "";
    public int Port { get; init; } = 8000;
    public string InstanceId { get; init; } = "";
    public string SinifAdi { get; set; } = "";
    public string OgretmenAdi { get; set; } = "";
    public string RetentionNote { get; set; } = "";

    public string Key => $"{Host}:{Port}";
    public string Display => $"Sınıf: {SinifAdi} — Öğretmen: {OgretmenAdi}";
}

public sealed class InfoResponse
{
    [JsonPropertyName("sinif_adi")] public string SinifAdi { get; set; } = "";
    [JsonPropertyName("ogretmen_adi")] public string OgretmenAdi { get; set; } = "";
    [JsonPropertyName("exam_state")] public string ExamState { get; set; } = "";
    [JsonPropertyName("server_version")] public string ServerVersion { get; set; } = "";
    [JsonPropertyName("retention_note")] public string RetentionNote { get; set; } = "";
}

public sealed class LoginRequest
{
    [JsonPropertyName("numara")] public string Numara { get; set; } = "";
    [JsonPropertyName("ad")] public string Ad { get; set; } = "";
    [JsonPropertyName("soyad")] public string Soyad { get; set; } = "";
    [JsonPropertyName("hostname")] public string Hostname { get; set; } = "";
    [JsonPropertyName("mac")] public string Mac { get; set; } = "";
    [JsonPropertyName("agent_version")] public string AgentVersion { get; set; } = "";
}

/// <summary>Exam status; returned by login and by every heartbeat.</summary>
public class ExamStatus
{
    [JsonPropertyName("exam_state")] public string ExamState { get; set; } = "WAITING";
    [JsonPropertyName("exam_id")] public string ExamId { get; set; } = "";
    [JsonPropertyName("allowlist_version")] public string AllowlistVersion { get; set; } = "";
    [JsonPropertyName("server_time")] public double ServerTime { get; set; }
    [JsonPropertyName("started_at")] public double StartedAt { get; set; }
    [JsonPropertyName("ends_at")] public double EndsAt { get; set; }
}

public sealed class LoginResponse : ExamStatus
{
    [JsonPropertyName("token")] public string Token { get; set; } = "";
    [JsonPropertyName("allowlist")] public PolicyDto Allowlist { get; set; } = new();
    [JsonPropertyName("settings")] public SettingsDto Settings { get; set; } = new();
    [JsonPropertyName("stream")] public StreamDto Stream { get; set; } = new();
    [JsonPropertyName("student")] public StudentDto Student { get; set; } = new();
}

public sealed class PolicyDto
{
    [JsonPropertyName("version")] public string Version { get; set; } = "";
    [JsonPropertyName("patterns")] public List<string> Patterns { get; set; } = new();
    [JsonPropertyName("windows_kill")] public List<string> WindowsKill { get; set; } = new();
    [JsonPropertyName("never_kill")] public List<string> NeverKill { get; set; } = new();
    [JsonPropertyName("app_windows_only")] public bool AppWindowsOnly { get; set; } = true;
}

public sealed class SettingsDto
{
    [JsonPropertyName("foreground_tolerance_s")] public double ForegroundToleranceS { get; set; } = 5;
    [JsonPropertyName("kill_countdown_s")] public int KillCountdownS { get; set; } = 10;
    [JsonPropertyName("heartbeat_interval_s")] public double HeartbeatIntervalS { get; set; } = 2;
}

public sealed class StreamDto
{
    [JsonPropertyName("url")] public string Url { get; set; } = "";
    [JsonPropertyName("user")] public string User { get; set; } = "";
    [JsonPropertyName("pass")] public string Pass { get; set; } = "";
    [JsonPropertyName("fps")] public int? Fps { get; set; }
    [JsonPropertyName("width")] public int? Width { get; set; }
    [JsonPropertyName("bitrate_kbps")] public int? BitrateKbps { get; set; }
}

public sealed class StudentDto
{
    [JsonPropertyName("numara")] public string Numara { get; set; } = "";
    [JsonPropertyName("ad")] public string Ad { get; set; } = "";
    [JsonPropertyName("soyad")] public string Soyad { get; set; } = "";
    [JsonPropertyName("last_sha256")] public string LastSha256 { get; set; } = "";
}

public sealed class HeartbeatRequest
{
    [JsonPropertyName("fg_process")] public string FgProcess { get; set; } = "";
    [JsonPropertyName("fg_path")] public string FgPath { get; set; } = "";
    [JsonPropertyName("fg_title")] public string FgTitle { get; set; } = "";
    [JsonPropertyName("monitors")] public int Monitors { get; set; }
    [JsonPropertyName("ffmpeg_alive")] public bool FfmpegAlive { get; set; }
    [JsonPropertyName("exam_state_seen")] public string ExamStateSeen { get; set; } = "";
}

public sealed class EventRequest
{
    [JsonPropertyName("type")] public string Type { get; set; } = "";
    [JsonPropertyName("details")] public Dictionary<string, object?> Details { get; set; } = new();
    /// <summary>Unix time (seconds) on the student's clock when the event happened.</summary>
    [JsonPropertyName("ts")] public double Ts { get; set; }
}

public sealed class ConfigResponse
{
    [JsonPropertyName("allowlist")] public PolicyDto Allowlist { get; set; } = new();
    [JsonPropertyName("settings")] public SettingsDto Settings { get; set; } = new();
}

public sealed class SubmitResponse
{
    [JsonPropertyName("sha256")] public string Sha256 { get; set; } = "";
    [JsonPropertyName("filename")] public string Filename { get; set; } = "";
    [JsonPropertyName("version")] public int Version { get; set; }
    [JsonPropertyName("size")] public long Size { get; set; }
}

public sealed class ErrorResponse
{
    [JsonPropertyName("error")] public string Error { get; set; } = "";
}
