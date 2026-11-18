using System.Runtime.InteropServices;
using SinavAjan.Core;

namespace SinavAjan.Win;

/// <summary>
/// Windows 10/11 virtual desktops (Task View, Win+Ctrl+D, Win+Ctrl+→). Only the documented
/// IVirtualDesktopManager interface is used: it tells whether a window is on the desktop
/// that is shown right now. Nothing is changed on the student's computer.
/// </summary>
internal static class VirtualDesktop
{
    [ComImport]
    [Guid("a5cd92ff-29be-454c-8d04-d82879fb3f1b")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IVirtualDesktopManager
    {
        [PreserveSig]
        int IsWindowOnCurrentVirtualDesktop(IntPtr topLevelWindow,
            [MarshalAs(UnmanagedType.Bool)] out bool onCurrentDesktop);

        [PreserveSig]
        int GetWindowDesktopId(IntPtr topLevelWindow, out Guid desktopId);

        [PreserveSig]
        int MoveWindowToDesktop(IntPtr topLevelWindow, ref Guid desktopId);
    }

    [ComImport]
    [Guid("aa509086-5ca9-4c25-8f95-589d3c07b48a")]
    private class VirtualDesktopManager
    {
    }

    private static IVirtualDesktopManager? _manager;
    private static bool _unavailable;

    /// <summary>
    /// Is the window on the virtual desktop the user is looking at? Null when Windows cannot
    /// tell (the feature is missing or the call failed). Call from the UI thread.
    /// </summary>
    public static bool? IsOnCurrentDesktop(IntPtr window)
    {
        if (_unavailable || window == IntPtr.Zero) return null;
        try
        {
            _manager ??= (IVirtualDesktopManager)new VirtualDesktopManager();
            return _manager.IsWindowOnCurrentVirtualDesktop(window, out var onCurrent) == 0 ? onCurrent : null;
        }
        catch (Exception ex) when (ex is COMException or InvalidCastException or NotSupportedException
                                       or TypeLoadException or UnauthorizedAccessException)
        {
            _unavailable = true; // do not try again on every tick
            LocalLog.Write($"sanal masaüstü denetimi kullanılamıyor: {ex.Message}");
            return null;
        }
    }
}
