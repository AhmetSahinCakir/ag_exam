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
    /// <summary>Upper limit of the stream; a screen that does not change uses far less.</summary>
    public int BitrateKbps { get; init; } = 500;
    /// <summary>Picture quality (x264 CRF): lower is sharper and larger.</summary>
    public int Crf { get; init; } = 23;
    /// <summary>Seconds between two full pictures (keyframes).</summary>
    public int KeyframeSeconds { get; init; } = 10;

    public static StreamSettings From(StreamConfig local, StreamDto server) => new()
    {
        Url = server.Url,
        User = string.IsNullOrEmpty(server.User) ? local.User : server.User,
        Pass = string.IsNullOrEmpty(server.User) ? local.Pass : server.Pass,
        Fps = Math.Clamp(server.Fps ?? local.Fps, 1, 30),
        Width = Math.Clamp(server.Width ?? local.Width, 320, 3840),
        BitrateKbps = Math.Clamp(server.BitrateKbps ?? local.BitrateKbps, 50, 8000),
        Crf = Math.Clamp(server.Crf ?? 23, 15, 40),
        KeyframeSeconds = Math.Clamp(server.KeyframeSeconds ?? 10, 1, 30),
    };
}

public static class FfmpegCommand
{
    /// <summary>
    /// ffmpeg arguments that capture the whole desktop (all monitors, gdigrab) and publish
    /// it as H.264 over RTSP/TCP to MediaMTX.
    ///
    /// The picture is encoded to a fixed quality with an upper limit on the bitrate, not to a
    /// fixed bitrate: an exam screen stands still most of the time, and a still screen then
    /// costs almost nothing — on the classroom Wi-Fi and in the recording alike. Measured on a
    /// Packet Tracer-like work session and on a still Windows desktop: 40-50 kbit/s instead of
    /// a constant 500.
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

            // Scaled down to the stream width; a smaller screen is sent as it is, not enlarged.
            "-vf", $"scale='trunc(min({s.Width.ToString(inv)},iw)/2)*2':-2",
            // Constrained Baseline without B-frames: what every browser plays over WebRTC.
            "-c:v", "libx264", "-preset", "superfast", "-profile:v", "baseline", "-tune", "zerolatency",
            // qcomp 1: every picture gets the same quality. With the default, x264 sharpens the
            // pictures after a full one although nothing on the screen changed, which made a
            // still desktop cost three times as much.
            "-crf", s.Crf.ToString(inv), "-qcomp", "1",
            "-maxrate", bitrate, "-bufsize", (s.BitrateKbps * 2).ToString(inv) + "k",
            // A full picture is what a still screen costs most. One every 10 seconds: the panel
            // shows a screen at the latest that long after it connects to it.
            "-g", (s.Fps * s.KeyframeSeconds).ToString(inv),
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
