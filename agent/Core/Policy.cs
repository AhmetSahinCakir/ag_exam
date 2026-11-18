using System.Text;
using System.Text.RegularExpressions;

namespace SinavAjan.Core;

public enum PathClass
{
    /// <summary>On the allowlist (Packet Tracer folder, the agent itself, ffmpeg).</summary>
    Allowed,

    /// <summary>Under the Windows folder: never killed, only watched while in the foreground.</summary>
    Windows,

    /// <summary>Listed under "kapatma_disi": never killed, still reported when in the foreground.</summary>
    NeverKill,

    /// <summary>Not allowed: a process with a window is terminated.</summary>
    Forbidden,

    /// <summary>The path could not be determined (protected process): never killed.</summary>
    Unknown,
}

/// <summary>
/// The application-control policy received from the server, compiled for fast matching.
/// Decisions are made on the full process path, never on window titles.
/// All comparisons are ordinal/invariant (a Turkish UI culture must not change "I" handling).
/// </summary>
public sealed class Policy
{
    private readonly List<Regex> _allow = new();
    private readonly List<Regex> _neverKill = new();
    private readonly HashSet<string> _windowsKill = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _self = new(StringComparer.OrdinalIgnoreCase);
    private readonly string _windowsDir;

    public string Version { get; }
    public bool AppWindowsOnly { get; }

    /// <summary>Allow patterns with environment variables expanded (used to locate Packet Tracer).</summary>
    public IReadOnlyList<string> AllowPatterns { get; }

    /// <param name="dto">Policy from the server.</param>
    /// <param name="windowsDir">The Windows folder, e.g. C:\Windows.</param>
    /// <param name="selfPaths">Full paths that are always allowed (agent exe, ffmpeg.exe).</param>
    public Policy(PolicyDto dto, string windowsDir, IEnumerable<string?> selfPaths)
    {
        Version = dto.Version ?? "";
        AppWindowsOnly = dto.AppWindowsOnly;
        _windowsDir = Normalise(windowsDir).TrimEnd('\\') + "\\";

        var expanded = new List<string>();
        foreach (var pattern in dto.Patterns ?? new List<string>())
        {
            if (string.IsNullOrWhiteSpace(pattern)) continue;
            var text = Normalise(Environment.ExpandEnvironmentVariables(pattern.Trim()));
            expanded.Add(text);
            _allow.Add(Compile(text));
        }
        AllowPatterns = expanded;

        foreach (var pattern in dto.NeverKill ?? new List<string>())
        {
            if (string.IsNullOrWhiteSpace(pattern)) continue;
            _neverKill.Add(Compile(Normalise(Environment.ExpandEnvironmentVariables(pattern.Trim()))));
        }
        foreach (var name in dto.WindowsKill ?? new List<string>())
        {
            if (!string.IsNullOrWhiteSpace(name)) _windowsKill.Add(name.Trim());
        }
        foreach (var path in selfPaths)
        {
            if (!string.IsNullOrWhiteSpace(path)) _self.Add(Normalise(path));
        }
    }

    public PathClass Classify(string? processPath)
    {
        if (string.IsNullOrWhiteSpace(processPath)) return PathClass.Unknown;
        var path = Normalise(processPath);

        if (_self.Contains(path)) return PathClass.Allowed;
        foreach (var regex in _allow)
        {
            if (regex.IsMatch(path)) return PathClass.Allowed;
        }
        if (path.StartsWith(_windowsDir, StringComparison.OrdinalIgnoreCase))
        {
            return _windowsKill.Contains(FileName(path)) ? PathClass.Forbidden : PathClass.Windows;
        }
        foreach (var regex in _neverKill)
        {
            if (regex.IsMatch(path)) return PathClass.NeverKill;
        }
        return PathClass.Forbidden;
    }

    public static string FileName(string path)
    {
        var index = path.LastIndexOfAny(new[] { '\\', '/' });
        return index >= 0 ? path[(index + 1)..] : path;
    }

    private static string Normalise(string path)
    {
        var text = path.Trim().Replace('/', '\\');
        if (text.StartsWith(@"\\?\", StringComparison.Ordinal)) text = text[4..];
        return text;
    }

    /// <summary>
    /// Glob to regex. "*" = anything except "\", "**" = anything, "?" = one character.
    /// A pattern that ends with "\" means that folder and everything below it.
    /// </summary>
    public static Regex Compile(string pattern)
    {
        var builder = new StringBuilder("^");
        for (var i = 0; i < pattern.Length; i++)
        {
            var c = pattern[i];
            if (c == '*')
            {
                if (i + 1 < pattern.Length && pattern[i + 1] == '*')
                {
                    builder.Append(".*");
                    i++;
                }
                else
                {
                    builder.Append(@"[^\\]*");
                }
            }
            else if (c == '?')
            {
                builder.Append(@"[^\\]");
            }
            else
            {
                builder.Append(Regex.Escape(c.ToString()));
            }
        }
        if (pattern.EndsWith('\\')) builder.Append(".*");
        builder.Append('$');
        return new Regex(builder.ToString(),
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);
    }
}
