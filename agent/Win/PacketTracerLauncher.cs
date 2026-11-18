using System.ComponentModel;
using System.Diagnostics;
using SinavAjan.Core;

namespace SinavAjan.Win;

public static class PacketTracerLauncher
{
    /// <summary>
    /// Looks for PacketTracer*.exe inside the allowlisted folders
    /// (e.g. C:\Program Files\Cisco Packet Tracer 8.2.2\bin\PacketTracer.exe).
    /// When several versions are installed the newest one wins.
    /// </summary>
    public static string? FindExecutable(Policy policy)
    {
        var candidates = new List<string>();
        foreach (var pattern in policy.AllowPatterns)
        {
            if (!pattern.EndsWith('\\') || pattern.Contains("**", StringComparison.Ordinal)) continue;
            foreach (var folder in ExpandFolders(pattern.TrimEnd('\\')))
            {
                foreach (var sub in new[] { "bin", "" })
                {
                    var dir = sub.Length == 0 ? folder : Path.Combine(folder, sub);
                    try
                    {
                        if (!Directory.Exists(dir)) continue;
                        candidates.AddRange(Directory.GetFiles(dir, "PacketTracer*.exe")
                            .Where(file => policy.Classify(file) == PathClass.Allowed));
                    }
                    catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                    {
                    }
                }
            }
        }
        return candidates
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderByDescending(FileVersion)
            .ThenByDescending(path => path, StringComparer.OrdinalIgnoreCase)
            .FirstOrDefault();
    }

    /// <summary>True when a Packet Tracer process from an allowlisted folder is running.</summary>
    public static bool IsRunning(Policy policy)
    {
        foreach (var process in Process.GetProcesses())
        {
            try
            {
                if (!process.ProcessName.StartsWith("PacketTracer", StringComparison.OrdinalIgnoreCase)) continue;
                if (policy.Classify(WindowInspector.GetProcessPath(process.Id)) == PathClass.Allowed) return true;
            }
            catch (InvalidOperationException)
            {
            }
            finally
            {
                process.Dispose();
            }
        }
        return false;
    }

    /// <summary>
    /// Opens the exam file with Packet Tracer. Throws <see cref="PacketTracerException"/> when
    /// Packet Tracer cannot be used; the file is never handed to the Windows "Open with" dialog.
    /// </summary>
    public static void Open(string examFile, Policy policy)
    {
        var exe = FindExecutable(policy);
        if (exe == null)
        {
            // Not in the allowlisted folders. Is it installed somewhere else?
            var associated = AssociatedProgram(".pka");
            if (associated == null)
            {
                throw new PacketTracerException(PacketTracerProblem.NotFound,
                    "Packet Tracer bu bilgisayarda bulunamadı.");
            }
            if (policy.Classify(associated) != PathClass.Allowed)
            {
                // Starting it would be pointless: the application control would close it again.
                throw new PacketTracerException(PacketTracerProblem.NotAllowed,
                    $"Packet Tracer izin verilen klasörlerin dışında kurulu: {associated}");
            }
            exe = associated;
        }

        try
        {
            var info = new ProcessStartInfo(exe)
            {
                UseShellExecute = false,
                WorkingDirectory = Path.GetDirectoryName(exe) ?? "",
            };
            info.ArgumentList.Add(examFile);
            using var started = Process.Start(info);
            LocalLog.Write($"Packet Tracer başlatıldı: {exe}");
        }
        catch (Exception ex) when (ex is Win32Exception or InvalidOperationException or IOException)
        {
            throw new PacketTracerException(PacketTracerProblem.StartFailed,
                $"Packet Tracer başlatılamadı ({exe}): {ex.Message}", ex);
        }
    }

    /// <summary>The program Windows would use to open files with this extension, or null.</summary>
    private static string? AssociatedProgram(string extension)
    {
        var buffer = new char[2048];
        var length = (uint)buffer.Length;
        var result = NativeMethods.AssocQueryStringW(NativeMethods.ASSOCF_INIT_IGNOREUNKNOWN,
            NativeMethods.ASSOCSTR_EXECUTABLE, extension, null, buffer, ref length);
        if (result != 0 || length <= 1) return null;

        var path = new string(buffer, 0, (int)length).TrimEnd('\0').Trim();
        if (path.Length == 0 || !File.Exists(path)) return null;
        if (Policy.FileName(path).Equals("OpenWith.exe", StringComparison.OrdinalIgnoreCase)) return null;
        return path;
    }

    /// <summary>Expands wildcards in the directory components of a folder pattern.</summary>
    private static IEnumerable<string> ExpandFolders(string pattern)
    {
        var parts = pattern.Split('\\', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length == 0) return Array.Empty<string>();

        IEnumerable<string> current = new[] { parts[0] + "\\" }; // drive root, e.g. "C:\"
        foreach (var part in parts.Skip(1))
        {
            var segment = part;
            current = segment.IndexOfAny(new[] { '*', '?' }) < 0
                ? current.Select(dir => Path.Combine(dir, segment))
                : current.SelectMany(dir => SafeDirectories(dir, segment));
        }
        return current.ToList();
    }

    private static IEnumerable<string> SafeDirectories(string parent, string pattern)
    {
        try
        {
            return Directory.Exists(parent) ? Directory.GetDirectories(parent, pattern) : Array.Empty<string>();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return Array.Empty<string>();
        }
    }

    private static Version FileVersion(string path)
    {
        try
        {
            var info = FileVersionInfo.GetVersionInfo(path);
            return new Version(Math.Max(0, info.FileMajorPart), Math.Max(0, info.FileMinorPart),
                Math.Max(0, info.FileBuildPart), Math.Max(0, info.FilePrivatePart));
        }
        catch (Exception ex) when (ex is IOException or ArgumentException)
        {
            return new Version(0, 0);
        }
    }
}

public enum PacketTracerProblem
{
    /// <summary>No Packet Tracer in the allowlisted folders and no program registered for .pka files.</summary>
    NotFound,

    /// <summary>Installed, but outside the allowlisted folders (the teacher must add the folder).</summary>
    NotAllowed,

    StartFailed,
}

public sealed class PacketTracerException : Exception
{
    public PacketTracerProblem Problem { get; }

    public PacketTracerException(PacketTracerProblem problem, string message, Exception? inner = null)
        : base(message, inner)
    {
        Problem = problem;
    }
}
