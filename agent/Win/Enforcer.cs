using System.Diagnostics;
using SinavAjan.Core;

namespace SinavAjan.Win;

public sealed class EnforcerTick
{
    public ForegroundSnapshot? Foreground { get; init; }
    public int Monitors { get; init; }
    public List<AgentEvent> Events { get; } = new();

    /// <summary>Friendly names of the programs closed in this tick (for the student notice).</summary>
    public List<string> ClosedPrograms { get; } = new();
}

/// <summary>Takes the desktop snapshot with Win32 calls and carries out the decisions.</summary>
public sealed class Enforcer
{
    private readonly EnforcementLogic _logic = new(Environment.ProcessId);
    private readonly Stopwatch _clock = Stopwatch.StartNew();
    private readonly HashSet<int> _killFailed = new();

    public void Reset()
    {
        _logic.Reset();
        _killFailed.Clear();
    }

    /// <summary>
    /// One pass. With enforce=false only the foreground window and monitor count are read
    /// (for the heartbeat); nothing is closed and no events are produced.
    /// </summary>
    public EnforcerTick Tick(Policy policy, bool enforce, double toleranceSeconds)
    {
        var snapshot = Capture(includeWindows: enforce);
        var tick = new EnforcerTick { Foreground = snapshot.Foreground, Monitors = snapshot.Monitors };
        if (!enforce) return tick;

        var result = _logic.Evaluate(snapshot, policy, toleranceSeconds, _clock.Elapsed);
        tick.Events.AddRange(result.Events);

        foreach (var order in result.Kills)
        {
            // The path was read a moment ago; make sure the PID still is that program.
            var current = WindowInspector.GetProcessPath(order.Pid);
            if (current == null || !string.Equals(current, order.Path, StringComparison.OrdinalIgnoreCase)) continue;

            var display = WindowInspector.DisplayName(order.Path);
            var details = new Dictionary<string, object?>
            {
                ["name"] = Policy.FileName(order.Path),
                ["path"] = order.Path,
                ["title"] = order.Title,
                ["display"] = display,
            };
            if (WindowInspector.ProcessStartUnix(order.Pid) is { } started) details["started"] = started;
            var error = WindowInspector.Kill(order.Pid);
            if (error == null)
            {
                tick.Events.Add(new AgentEvent("process_killed", details));
                tick.ClosedPrograms.Add(display);
            }
            else if (_killFailed.Add(order.Pid))
            {
                details["error"] = error;
                tick.Events.Add(new AgentEvent("process_kill_failed", details));
            }
        }
        return tick;
    }

    private static DesktopSnapshot Capture(bool includeWindows)
    {
        var paths = new Dictionary<int, string?>();

        string? PathOf(int pid)
        {
            if (!paths.TryGetValue(pid, out var path))
            {
                path = WindowInspector.GetProcessPath(pid);
                paths[pid] = path;
            }
            return path;
        }

        // Store apps: look through the ApplicationFrameHost window to the real app process.
        (int Pid, string? Path) Resolve(IntPtr hwnd, int pid)
        {
            var path = PathOf(pid);
            if (WindowInspector.IsUwpFrameHost(path))
            {
                var hosted = WindowInspector.FindHostedProcess(hwnd, pid);
                if (hosted != 0) return (hosted, PathOf(hosted));
            }
            return (pid, path);
        }

        ForegroundSnapshot? foreground = null;
        if (WindowInspector.GetForeground() is { } fg)
        {
            var (pid, path) = Resolve(fg.Hwnd, fg.Pid);
            foreground = new ForegroundSnapshot(pid, path, fg.Title, fg.ClassName);
        }

        var windows = new List<ProcWindow>();
        if (includeWindows)
        {
            foreach (var window in WindowInspector.EnumerateVisibleTopLevel())
            {
                var (pid, path) = Resolve(window.Hwnd, window.Pid);
                windows.Add(new ProcWindow(pid, path, window.Title, window.IsAppWindow));
            }
        }
        return new DesktopSnapshot(foreground, windows, WindowInspector.MonitorCount);
    }
}
