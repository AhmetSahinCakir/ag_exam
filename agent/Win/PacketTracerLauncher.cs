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

    /// <summary>Opens the exam file with Packet Tracer. Throws InvalidOperationException with a Turkish text.</summary>
    public static void Open(string examFile, Policy policy)
    {
        var exe = FindExecutable(policy);
        try
        {
            if (exe != null)
            {
                var info = new ProcessStartInfo(exe)
                {
                    UseShellExecute = false,
                    WorkingDirectory = Path.GetDirectoryName(exe) ?? "",
                };
                info.ArgumentList.Add(examFile);
                using var started = Process.Start(info);
                LocalLog.Write($"Packet Tracer başlatıldı: {exe}");
                return;
            }

            // Not found in the expected folders: let Windows use the .pka file association.
            using var shell = Process.Start(new ProcessStartInfo(examFile) { UseShellExecute = true });
            LocalLog.Write("Packet Tracer dosya ilişkilendirmesiyle açıldı");
        }
        catch (Exception ex) when (ex is Win32Exception or InvalidOperationException or IOException)
        {
            throw new InvalidOperationException(
                exe == null
                    ? "Packet Tracer bu bilgisayarda bulunamadı."
                    : $"Packet Tracer başlatılamadı: {ex.Message}", ex);
        }
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
