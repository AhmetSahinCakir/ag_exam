using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace SinavAjan.Win;

/// <summary>
/// A Windows Job Object with KILL_ON_JOB_CLOSE. Every process assigned to it is killed
/// by Windows when the last handle to the job closes — that is, when the agent exits for
/// ANY reason (normal exit, crash, "End task" in Task Manager). This is how ffmpeg is
/// guaranteed never to outlive the agent.
/// </summary>
public sealed class JobObject : IDisposable
{
    private IntPtr _handle;

    public JobObject()
    {
        _handle = NativeMethods.CreateJobObjectW(IntPtr.Zero, null);
        if (_handle == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());

        var info = new NativeMethods.JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = NativeMethods.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        var size = Marshal.SizeOf<NativeMethods.JOBOBJECT_EXTENDED_LIMIT_INFORMATION>();
        var buffer = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(info, buffer, false);
            if (!NativeMethods.SetInformationJobObject(_handle, NativeMethods.JobObjectExtendedLimitInformation,
                    buffer, (uint)size))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    public void Assign(Process process)
    {
        if (_handle == IntPtr.Zero) throw new ObjectDisposedException(nameof(JobObject));
        if (!NativeMethods.AssignProcessToJobObject(_handle, process.Handle))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }

    public void Dispose()
    {
        if (_handle == IntPtr.Zero) return;
        NativeMethods.CloseHandle(_handle); // kills everything still inside the job
        _handle = IntPtr.Zero;
    }
}
