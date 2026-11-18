using System.Diagnostics;
using System.Security.Principal;
using SinavAjan.Core;
using SinavAjan.UI;

namespace SinavAjan;

internal static class Program
{

    public static string Version =>
        typeof(Program).Assembly.GetName().Version?.ToString(3) ?? "1.0.0";

    [STAThread]
    private static int Main()
    {
        Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);

        // Before anything else: without administrator rights nothing is contacted and
        // nothing is streamed. (The manifest already asks for elevation; this check covers
        // the cases where that is bypassed.)
        if (!IsAdministrator())
        {
            MessageDialog.Show(null, DialogTone.Warning, "Yönetici izni gerekli",
                "Bu program yönetici olarak çalıştırılmalıdır. Sağ tık → Yönetici olarak çalıştır.");
            return 1;
        }

        using var single = new Mutex(true, @"Local\SinavAjan.TekKopya", out var first);
        if (!first)
        {
            MessageDialog.Show(null, DialogTone.Info, "Sınav Ajanı zaten çalışıyor",
                "Açık olan pencereyi kullanın; görev çubuğunda “Sınav” ya da “Sınav Ajanı” adıyla durur.");
            return 1;
        }

        try
        {
            // Lets the agent read the path of (and close) processes started elevated.
            Process.EnterDebugMode();
        }
        catch (Exception ex)
        {
            LocalLog.Write($"SeDebugPrivilege alınamadı: {ex.Message}");
        }

        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (_, e) => LocalLog.Write($"HATA (arayüz): {e.Exception}");
        AppDomain.CurrentDomain.UnhandledException += (_, e) => LocalLog.Write($"HATA: {e.ExceptionObject}");
        TaskScheduler.UnobservedTaskException += (_, e) =>
        {
            LocalLog.Write($"HATA (görev): {e.Exception}");
            e.SetObserved();
        };

        var config = AgentConfig.Load(AppContext.BaseDirectory);
        Application.Run(new MainForm(config));
        return 0;
    }

    private static bool IsAdministrator()
    {
        try
        {
            using var identity = WindowsIdentity.GetCurrent();
            return new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator);
        }
        catch (Exception)
        {
            return false;
        }
    }
}
