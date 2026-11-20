using System.Runtime.InteropServices;

namespace SinavAjan.Win;

/// <summary>Win32 declarations (the agent is built for win-x64 only).</summary>
internal static class NativeMethods
{
    public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

    public const int GWL_EXSTYLE = -20;
    public const long WS_EX_TOOLWINDOW = 0x00000080;
    public const long WS_EX_APPWINDOW = 0x00040000;
    public const long WS_EX_NOACTIVATE = 0x08000000;
    public const int SM_CMONITORS = 80;

    public const uint PROCESS_TERMINATE = 0x0001;
    public const uint PROCESS_SET_QUOTA = 0x0100;
    public const uint PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;

    public const int JobObjectExtendedLimitInformation = 9;
    public const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    public const uint FLASHW_ALL = 0x00000003;
    public const uint FLASHW_TIMERNOFG = 0x0000000C;

    [StructLayout(LayoutKind.Sequential)]
    public struct FLASHWINFO
    {
        public uint cbSize;
        public IntPtr hwnd;
        public uint dwFlags;
        public uint uCount;
        public uint dwTimeout;
    }

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool FlashWindowEx(ref FLASHWINFO info);

    /// <summary>
    /// Asks for attention the quiet way: the window's taskbar button blinks until the user
    /// opens the window. The window is not brought to the front and takes no focus.
    /// </summary>
    public static void FlashTaskbar(IntPtr window)
    {
        var info = new FLASHWINFO
        {
            cbSize = (uint)Marshal.SizeOf<FLASHWINFO>(),
            hwnd = window,
            dwFlags = FLASHW_ALL | FLASHW_TIMERNOFG,
            uCount = uint.MaxValue,
            dwTimeout = 0,
        };
        FlashWindowEx(ref info);
    }

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool EnumChildWindows(IntPtr parent, EnumWindowsProc callback, IntPtr lParam);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    public static extern int GetWindowTextLengthW(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    public static extern int GetWindowTextW(IntPtr hWnd, [Out] char[] text, int maxCount);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    public static extern int GetClassNameW(IntPtr hWnd, [Out] char[] className, int maxCount);

    [DllImport("user32.dll", ExactSpelling = true)]
    public static extern IntPtr GetWindowLongPtrW(IntPtr hWnd, int index);

    [DllImport("user32.dll")]
    public static extern int GetSystemMetrics(int index);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr OpenProcess(uint access, [MarshalAs(UnmanagedType.Bool)] bool inherit, uint processId);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode, ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool QueryFullProcessImageNameW(IntPtr process, uint flags, [Out] char[] buffer, ref uint size);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool TerminateProcess(IntPtr process, uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CloseHandle(IntPtr handle);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode, ExactSpelling = true)]
    public static extern IntPtr CreateJobObjectW(IntPtr attributes, string? name);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint length);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }
}
