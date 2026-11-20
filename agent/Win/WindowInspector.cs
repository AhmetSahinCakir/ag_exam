using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using SinavAjan.Core;

namespace SinavAjan.Win;

/// <summary>A visible top-level window.</summary>
/// <param name="IsAppWindow">
/// True for a real application window: it has a title and is not a tool / no-activate
/// helper window (those never appear on the taskbar or in Alt+Tab).
/// </param>
public readonly record struct WindowInfo(IntPtr Hwnd, int Pid, string Title, bool IsAppWindow, string ClassName = "");

public static class WindowInspector
{
    private const string UwpFrameHost = "ApplicationFrameHost.exe";

    public static int MonitorCount => Math.Max(1, NativeMethods.GetSystemMetrics(NativeMethods.SM_CMONITORS));

    /// <summary>The foreground window (GetForegroundWindow -> GetWindowThreadProcessId), or null.</summary>
    public static WindowInfo? GetForeground()
    {
        var hwnd = NativeMethods.GetForegroundWindow();
        if (hwnd == IntPtr.Zero) return null;
        NativeMethods.GetWindowThreadProcessId(hwnd, out var pid);
        if (pid == 0) return null;
        return new WindowInfo(hwnd, (int)pid, GetTitle(hwnd), true, GetClassName(hwnd));
    }

    /// <summary>All visible top-level windows (EnumWindows + IsWindowVisible).</summary>
    public static List<WindowInfo> EnumerateVisibleTopLevel()
    {
        var windows = new List<WindowInfo>();
        NativeMethods.EnumWindowsProc callback = (hwnd, _) =>
        {
            if (!NativeMethods.IsWindowVisible(hwnd)) return true;
            NativeMethods.GetWindowThreadProcessId(hwnd, out var pid);
            if (pid == 0) return true;

            var title = GetTitle(hwnd);
            var style = NativeMethods.GetWindowLongPtrW(hwnd, NativeMethods.GWL_EXSTYLE).ToInt64();
            var forcedApp = (style & NativeMethods.WS_EX_APPWINDOW) != 0;
            var helper = (style & (NativeMethods.WS_EX_TOOLWINDOW | NativeMethods.WS_EX_NOACTIVATE)) != 0;
            var isApp = title.Length > 0 && (forcedApp || !helper);
            windows.Add(new WindowInfo(hwnd, (int)pid, title, isApp));
            return true;
        };
        NativeMethods.EnumWindows(callback, IntPtr.Zero);
        GC.KeepAlive(callback);
        return windows;
    }

    /// <summary>
    /// Store (UWP) apps are drawn inside a frame window owned by ApplicationFrameHost.exe.
    /// Returns the process that really owns the content, or 0 when there is none.
    /// </summary>
    public static int FindHostedProcess(IntPtr frameWindow, int framePid)
    {
        var hosted = 0;
        NativeMethods.EnumWindowsProc callback = (child, _) =>
        {
            NativeMethods.GetWindowThreadProcessId(child, out var pid);
            if (pid == 0 || pid == framePid) return true;
            hosted = (int)pid;
            return false;
        };
        NativeMethods.EnumChildWindows(frameWindow, callback, IntPtr.Zero);
        GC.KeepAlive(callback);
        return hosted;
    }

    public static bool IsUwpFrameHost(string? path) =>
        path != null && Policy.FileName(path).Equals(UwpFrameHost, StringComparison.OrdinalIgnoreCase);

    /// <summary>Full image path of a process, or null when it cannot be read.</summary>
    public static string? GetProcessPath(int pid)
    {
        var handle = NativeMethods.OpenProcess(NativeMethods.PROCESS_QUERY_LIMITED_INFORMATION, false, (uint)pid);
        if (handle == IntPtr.Zero) return null;
        try
        {
            var buffer = new char[1024];
            var size = (uint)buffer.Length;
            if (!NativeMethods.QueryFullProcessImageNameW(handle, 0, buffer, ref size) || size == 0)
            {
                buffer = new char[32768];
                size = (uint)buffer.Length;
                if (!NativeMethods.QueryFullProcessImageNameW(handle, 0, buffer, ref size) || size == 0) return null;
            }
            return new string(buffer, 0, (int)size);
        }
        finally
        {
            NativeMethods.CloseHandle(handle);
        }
    }

    /// <summary>Terminates a process. Returns null on success, otherwise the error text.</summary>
    /// <summary>
    /// When the process was started, in Unix seconds by this computer's clock; null when it
    /// cannot be read. The server compares it with the moment the exam began for this student:
    /// a program that was already open then is closed without a warning.
    /// </summary>
    public static double? ProcessStartUnix(int pid)
    {
        try
        {
            using var process = System.Diagnostics.Process.GetProcessById(pid);
            return new DateTimeOffset(process.StartTime.ToUniversalTime()).ToUnixTimeMilliseconds() / 1000.0;
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException
                                       or NotSupportedException or System.ComponentModel.Win32Exception)
        {
            return null;
        }
    }

    public static string? Kill(int pid)
    {
        var handle = NativeMethods.OpenProcess(NativeMethods.PROCESS_TERMINATE, false, (uint)pid);
        if (handle == IntPtr.Zero) return new Win32Exception(Marshal.GetLastWin32Error()).Message;
        try
        {
            return NativeMethods.TerminateProcess(handle, 1)
                ? null
                : new Win32Exception(Marshal.GetLastWin32Error()).Message;
        }
        finally
        {
            NativeMethods.CloseHandle(handle);
        }
    }

    /// <summary>Friendly program name ("Google Chrome"); falls back to the file name.</summary>
    public static string DisplayName(string path)
    {
        try
        {
            var description = FileVersionInfo.GetVersionInfo(path).FileDescription;
            if (!string.IsNullOrWhiteSpace(description)) return description.Trim();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException)
        {
        }
        return Policy.FileName(path);
    }

    /// <summary>The window class, e.g. "Progman" for the desktop. Never localised.</summary>
    private static string GetClassName(IntPtr hwnd)
    {
        var buffer = new char[256];
        var copied = NativeMethods.GetClassNameW(hwnd, buffer, buffer.Length);
        return copied > 0 ? new string(buffer, 0, copied) : "";
    }

    private static string GetTitle(IntPtr hwnd)
    {
        var length = NativeMethods.GetWindowTextLengthW(hwnd);
        if (length <= 0) return "";
        var buffer = new char[Math.Min(length, 512) + 1];
        var copied = NativeMethods.GetWindowTextW(hwnd, buffer, buffer.Length);
        return copied > 0 ? new string(buffer, 0, copied).Trim() : "";
    }
}
