namespace SinavAjan.Core;

/// <summary>A visible top-level window and the process that owns its content.</summary>
public sealed record ProcWindow(int Pid, string? Path, string Title, bool IsAppWindow);

public sealed record ForegroundSnapshot(int Pid, string? Path, string Title)
{
    public string Name => Path != null ? Policy.FileName(Path) : $"pid {Pid}";
}

/// <summary>What the desktop looks like right now (taken once per second).</summary>
public sealed record DesktopSnapshot(ForegroundSnapshot? Foreground, IReadOnlyList<ProcWindow> Windows, int Monitors);

public sealed record KillOrder(int Pid, string Path, string Title);

public sealed record AgentEvent(string Type, Dictionary<string, object?> Details);

public sealed class EnforcementResult
{
    public List<KillOrder> Kills { get; } = new();
    public List<AgentEvent> Events { get; } = new();
}

/// <summary>
/// The application-control rules, free of any Windows API so that they can be tested
/// anywhere. Called once per second while the exam is RUNNING.
///
/// Kill rule: a process that owns a window, is not on the allowlist and is not under the
/// Windows folder is terminated.
/// Foreground rule: when the foreground window belongs to anything that is not on the
/// allowlist (Windows' own UI included) for longer than the tolerance, a warning is
/// raised. Short switches (Start menu, Alt+Tab, notifications, UAC) stay silent.
/// </summary>
public sealed class EnforcementLogic
{
    private static readonly TimeSpan RepeatInterval = TimeSpan.FromSeconds(30);

    private readonly int _selfPid;
    private int? _monitors;
    private string? _lastForegroundKey;
    private TimeSpan? _foreignSince;
    private bool _foreignReported;
    private string? _foreignName;
    private TimeSpan _foreignReportedAt;

    public EnforcementLogic(int selfPid) => _selfPid = selfPid;

    public void Reset()
    {
        _monitors = null;
        _lastForegroundKey = null;
        _foreignSince = null;
        _foreignReported = false;
        _foreignName = null;
    }

    /// <param name="snapshot">Current desktop state.</param>
    /// <param name="policy">Allowlist policy.</param>
    /// <param name="toleranceSeconds">Foreground tolerance (5 s by default).</param>
    /// <param name="now">Monotonic time.</param>
    public EnforcementResult Evaluate(DesktopSnapshot snapshot, Policy policy, double toleranceSeconds, TimeSpan now)
    {
        var result = new EnforcementResult();
        CheckMonitors(snapshot.Monitors, result);
        CollectKills(snapshot, policy, result);
        CheckForeground(snapshot.Foreground, policy, toleranceSeconds, now, result);
        return result;
    }

    private void CheckMonitors(int monitors, EnforcementResult result)
    {
        if (_monitors == null)
        {
            _monitors = monitors;
            if (monitors > 1)
            {
                result.Events.Add(new AgentEvent("monitor_change",
                    new Dictionary<string, object?> { ["count"] = monitors, ["initial"] = true }));
            }
        }
        else if (monitors != _monitors)
        {
            result.Events.Add(new AgentEvent("monitor_change",
                new Dictionary<string, object?> { ["count"] = monitors, ["previous"] = _monitors }));
            _monitors = monitors;
        }
    }

    private void CollectKills(DesktopSnapshot snapshot, Policy policy, EnforcementResult result)
    {
        var seen = new HashSet<int>();

        void Consider(int pid, string? path, string title)
        {
            if (pid == _selfPid || pid <= 4) return; // never ourselves, never Idle/System
            if (!seen.Add(pid)) return;
            if (policy.Classify(path) == PathClass.Forbidden) result.Kills.Add(new KillOrder(pid, path!, title));
        }

        foreach (var window in snapshot.Windows)
        {
            if (policy.AppWindowsOnly && !window.IsAppWindow) continue;
            Consider(window.Pid, window.Path, window.Title);
        }
        // Whatever the student is interacting with right now always counts as "has a window".
        if (snapshot.Foreground is { } foreground) Consider(foreground.Pid, foreground.Path, foreground.Title);
    }

    private void CheckForeground(ForegroundSnapshot? foreground, Policy policy, double toleranceSeconds, TimeSpan now,
        EnforcementResult result)
    {
        if (foreground == null) return; // no foreground window at this instant: neither good nor bad

        var kind = policy.Classify(foreground.Path);
        var allowed = kind == PathClass.Allowed;
        var key = $"{foreground.Pid}|{foreground.Path}";
        if (key != _lastForegroundKey)
        {
            _lastForegroundKey = key;
            // Every foreground switch goes to the event log (not to the alert feed).
            result.Events.Add(new AgentEvent("foreground_change", new Dictionary<string, object?>
            {
                ["name"] = foreground.Name,
                ["path"] = foreground.Path ?? "",
                ["title"] = foreground.Title,
                ["allowed"] = allowed,
            }));
        }

        if (allowed)
        {
            if (_foreignSince != null && _foreignReported)
            {
                result.Events.Add(new AgentEvent("foreground_restored", new Dictionary<string, object?>
                {
                    ["seconds"] = Math.Round((now - _foreignSince.Value).TotalSeconds),
                }));
            }
            _foreignSince = null;
            _foreignReported = false;
            _foreignName = null;
            return;
        }

        _foreignSince ??= now;
        var elapsed = (now - _foreignSince.Value).TotalSeconds;
        if (elapsed < toleranceSeconds) return;

        var sameAsLastReport = _foreignReported && foreground.Name == _foreignName
                                                && now - _foreignReportedAt < RepeatInterval;
        if (sameAsLastReport) return;

        _foreignReported = true;
        _foreignName = foreground.Name;
        _foreignReportedAt = now;
        result.Events.Add(new AgentEvent("foreign_foreground", new Dictionary<string, object?>
        {
            ["name"] = foreground.Name,
            ["path"] = foreground.Path ?? "",
            ["title"] = foreground.Title,
            ["seconds"] = Math.Round(elapsed),
        }));
    }
}
