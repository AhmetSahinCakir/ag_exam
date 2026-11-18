using System.Globalization;

namespace SinavAjan.Core;

/// <summary>Effective screen-stream settings: agent.json defaults, optionally overridden by the server.</summary>
public sealed class StreamSettings
{
    public string Url { get; init; } = "";
    public string User { get; init; } = "";
    public string Pass { get; init; } = "";
    public int Fps { get; init; } = 5;
    public int Width { get; init; } = 1280;
    public int BitrateKbps { get; init; } = 500;

    public static StreamSettings From(StreamConfig local, StreamDto server) => new()
    {
        Url = server.Url,
        User = string.IsNullOrEmpty(server.User) ? local.User : server.User,
        Pass = string.IsNullOrEmpty(server.User) ? local.Pass : server.Pass,
        Fps = Math.Clamp(server.Fps ?? local.Fps, 1, 30),
        Width = Math.Clamp(server.Width ?? local.Width, 320, 3840),
        BitrateKbps = Math.Clamp(server.BitrateKbps ?? local.BitrateKbps, 50, 8000),
    };
}

public static class FfmpegCommand
{
    /// <summary>
    /// ffmpeg arguments that capture the whole desktop (all monitors, gdigrab) and publish
    /// it as H.264 over RTSP/TCP to MediaMTX.
    /// </summary>
    public static List<string> Build(StreamSettings s)
    {
        var inv = CultureInfo.InvariantCulture;
        var bitrate = s.BitrateKbps.ToString(inv) + "k";
        return new List<string>
        {
            "-hide_banner", "-loglevel", "warning", "-nostdin",
            // Machine-readable progress on stdout; the agent uses it to detect a stalled stream.
            "-nostats", "-progress", "pipe:1", "-stats_period", "1",

            "-f", "gdigrab", "-framerate", s.Fps.ToString(inv), "-i", "desktop",

            "-vf", $"scale={s.Width.ToString(inv)}:-2",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", (s.BitrateKbps * 2).ToString(inv) + "k",
            // One keyframe every 2 seconds: quick start for the panel, clean recording segments.
            "-g", (s.Fps * 2).ToString(inv),
            "-pix_fmt", "yuv420p",

            "-f", "rtsp", "-rtsp_transport", "tcp", UrlWithCredentials(s.Url, s.User, s.Pass),
        };
    }

    /// <summary>rtsp://host:8554/1 -> rtsp://user:pass@host:8554/1 (credentials URL-encoded).</summary>
    public static string UrlWithCredentials(string url, string user, string pass)
    {
        const string scheme = "rtsp://";
        if (string.IsNullOrEmpty(user) || !url.StartsWith(scheme, StringComparison.OrdinalIgnoreCase)) return url;
        var rest = url[scheme.Length..];
        var at = rest.IndexOf('@');
        var slash = rest.IndexOf('/');
        if (at >= 0 && (slash < 0 || at < slash)) rest = rest[(at + 1)..]; // drop existing credentials
        return $"{scheme}{Uri.EscapeDataString(user)}:{Uri.EscapeDataString(pass)}@{rest}";
    }

    /// <summary>The same arguments with the password hidden, for the local log.</summary>
    public static string ForLog(IEnumerable<string> args, string pass) =>
        string.Join(' ', args).Replace(Uri.EscapeDataString(pass), "***", StringComparison.Ordinal);
}
