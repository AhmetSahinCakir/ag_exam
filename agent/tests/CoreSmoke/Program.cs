using System.Globalization;
using System.Net;
using System.Text;
using SinavAjan.Core;

namespace SinavAjan.Tests;

internal static class Program
{
    private static int _failed;
    private static int _passed;

    private static void Check(bool condition, string what)
    {
        if (condition)
        {
            _passed++;
        }
        else
        {
            _failed++;
            Console.WriteLine($"  BAŞARISIZ: {what}");
        }
    }

    private static void Equal<T>(T expected, T actual, string what) =>
        Check(EqualityComparer<T>.Default.Equals(expected, actual), $"{what}: beklenen {expected}, bulunan {actual}");

    private static async Task<int> Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        PolicyTests();
        TurkishCultureTests();
        EnforcementTests();
        FfmpegTests();
        DiscoveryParseTests();

        string? server = null;
        var discover = false;
        for (var i = 0; i < args.Length; i++)
        {
            if (args[i] is "server" or "--server" && i + 1 < args.Length) server = args[++i];
            if (args[i] is "discover" or "--discover") discover = true;
        }
        if (server != null || discover) await IntegrationAsync(server);

        Console.WriteLine($"{_passed} denetim geçti, {_failed} başarısız.");
        return _failed == 0 ? 0 : 1;
    }

    private static Policy MakePolicy(bool appWindowsOnly = true) => new(
        new PolicyDto
        {
            Version = "t1",
            Patterns =
            {
                @"C:\Program Files\Cisco Packet Tracer*\",
                @"C:\Program Files (x86)\Cisco Packet Tracer*\",
            },
            WindowsKill = { "notepad.exe", "mspaint.exe" },
            NeverKill = { @"C:\Program Files\NVIDIA Corporation\**" },
            AppWindowsOnly = appWindowsOnly,
        },
        @"C:\Windows",
        new[] { @"D:\Sinav\SinavAjan.exe", @"D:\Sinav\ffmpeg.exe", null });

    private static void PolicyTests()
    {
        Console.WriteLine("İzin listesi kuralları");
        var p = MakePolicy();
        Equal(PathClass.Allowed, p.Classify(@"C:\Program Files\Cisco Packet Tracer 8.2.2\bin\PacketTracer.exe"), "PT");
        Equal(PathClass.Allowed, p.Classify(@"C:\Program Files\Cisco Packet Tracer 8.2.2\bin\QtWebEngineProcess.exe"), "PT yardımcı süreç");
        Equal(PathClass.Allowed, p.Classify(@"c:\program files (x86)\cisco packet tracer 7.3\bin\PacketTracer7.exe"), "PT x86 küçük harf");
        Equal(PathClass.Allowed, p.Classify(@"C:\Program Files\Cisco Packet Tracer\bin\PacketTracer.exe"), "PT sürümsüz klasör");
        Equal(PathClass.Allowed, p.Classify(@"\\?\C:\Program Files\Cisco Packet Tracer 8.2.2\bin\PacketTracer.exe"), "PT \\\\?\\ öneki");
        Equal(PathClass.Forbidden, p.Classify(@"C:\Program Files\Cisco\Packet Tracer 8\bin\PacketTracer.exe"), "farklı klasör");
        Equal(PathClass.Forbidden, p.Classify(@"C:\Program Files\Google\Chrome\Application\chrome.exe"), "Chrome");
        Equal(PathClass.Forbidden, p.Classify(@"C:\Users\ali\AppData\Local\Discord\app-1.0\Discord.exe"), "Discord");
        Equal(PathClass.Forbidden, p.Classify(@"C:\Program Files\WindowsApps\Microsoft.WindowsNotepad_11.2312_x64__8wekyb3d8bbwe\Notepad\Notepad.exe"), "Win11 Not Defteri");
        Equal(PathClass.Windows, p.Classify(@"C:\Windows\explorer.exe"), "explorer");
        Equal(PathClass.Windows, p.Classify(@"C:\WINDOWS\System32\cmd.exe"), "cmd");
        Equal(PathClass.Windows, p.Classify(@"C:\Windows\SystemApps\Microsoft.Windows.StartMenuExperienceHost_cw5n1h2txyewy\StartMenuExperienceHost.exe"), "başlat menüsü");
        Equal(PathClass.Forbidden, p.Classify(@"C:\Windows\System32\notepad.exe"), "Win10 Not Defteri (istisna)");
        Equal(PathClass.Forbidden, p.Classify(@"C:\WINDOWS\system32\NOTEPAD.EXE"), "Not Defteri büyük harf");
        Equal(PathClass.Forbidden, p.Classify(@"C:\WindowsSahte\zararli.exe"), "C:\\Windows önek tuzağı");
        Equal(PathClass.NeverKill, p.Classify(@"C:\Program Files\NVIDIA Corporation\NVIDIA GeForce Experience\NVIDIA Share.exe"), "kapatma_disi");
        Equal(PathClass.Allowed, p.Classify(@"D:\Sinav\SinavAjan.exe"), "ajanın kendisi");
        Equal(PathClass.Allowed, p.Classify(@"d:\sinav\FFMPEG.EXE"), "ffmpeg");
        Equal(PathClass.Forbidden, p.Classify(@"D:\Sinav\baska.exe"), "ajan klasöründeki başka exe");
        Equal(PathClass.Unknown, p.Classify(null), "yol okunamadı");
        Equal("chrome.exe", Policy.FileName(@"C:\x\chrome.exe"), "dosya adı");
        Check(Policy.Compile(@"C:\A*\b?.exe").IsMatch(@"C:\Abc\b1.exe"), "glob * ve ?");
        Check(!Policy.Compile(@"C:\A*\b.exe").IsMatch(@"C:\Abc\x\b.exe"), "glob * klasör aşmaz");
        Check(Policy.Compile(@"C:\A\**\b.exe").IsMatch(@"C:\A\x\y\b.exe"), "glob ** klasör aşar");
    }

    private static void TurkishCultureTests()
    {
        Console.WriteLine("Türkçe kültürde büyük/küçük harf (I/İ/ı/i)");
        var previous = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = new CultureInfo("tr-TR");
            var p = MakePolicy();
            Equal(PathClass.Allowed, p.Classify(@"C:\PROGRAM FILES\CISCO PACKET TRACER 8.2.2\BIN\PACKETTRACER.EXE"), "tr-TR büyük harf PT");
            Equal(PathClass.Windows, p.Classify(@"C:\WINDOWS\EXPLORER.EXE"), "tr-TR WINDOWS");
            Equal(PathClass.Forbidden, p.Classify(@"C:\WINDOWS\SYSTEM32\MSPAINT.EXE"), "tr-TR MSPAINT (I harfi)");
        }
        catch (CultureNotFoundException)
        {
            Console.WriteLine("  (tr-TR kültürü bu sistemde yok; atlandı)");
        }
        finally
        {
            CultureInfo.CurrentCulture = previous;
        }
    }

    private const string Pt = @"C:\Program Files\Cisco Packet Tracer 8.2.2\bin\PacketTracer.exe";
    private const string Chrome = @"C:\Program Files\Google\Chrome\Application\chrome.exe";
    private const string Explorer = @"C:\Windows\explorer.exe";
    private const string Overlay = @"C:\Program Files\Acme\overlay.exe";

    private static int CountEvents(EnforcementResult result, string type) => result.Events.Count(e => e.Type == type);

    private static void EnforcementTests()
    {
        Console.WriteLine("Denetim mantığı");
        var policy = MakePolicy();
        var logic = new EnforcementLogic(selfPid: 999);
        var ptWindow = new ProcWindow(100, Pt, "Cisco Packet Tracer", true);
        var ptFg = new ForegroundSnapshot(100, Pt, "Cisco Packet Tracer");
        TimeSpan T(double s) => TimeSpan.FromSeconds(s);

        // Chrome has a window -> killed; PT, Explorer and the agent itself are not.
        var r = logic.Evaluate(new DesktopSnapshot(ptFg, new[]
        {
            ptWindow,
            new ProcWindow(200, Chrome, "Yeni Sekme - Google Chrome", true),
            new ProcWindow(300, Explorer, "Program Manager", true),
            new ProcWindow(999, Chrome, "kendimiz", true),
            new ProcWindow(400, Overlay, "", false),
        }, 1), policy, 5, T(0));
        Equal(1, r.Kills.Count, "yalnızca Chrome kapatılır");
        Equal(200, r.Kills.FirstOrDefault()?.Pid ?? 0, "kapatılan pid");
        Equal(1, CountEvents(r, "foreground_change"), "ilk öndeki pencere kaydı");
        Equal(0, CountEvents(r, "monitor_change"), "tek monitör uyarı vermez");

        // Start menu (explorer) in front for 2 seconds, then back: no warning.
        var explorerFg = new ForegroundSnapshot(300, Explorer, "Başlat");
        r = logic.Evaluate(new DesktopSnapshot(explorerFg, new[] { ptWindow }, 1), policy, 5, T(1));
        Equal(0, CountEvents(r, "foreign_foreground"), "1 sn: uyarı yok");
        r = logic.Evaluate(new DesktopSnapshot(explorerFg, new[] { ptWindow }, 1), policy, 5, T(3));
        Equal(0, CountEvents(r, "foreign_foreground"), "2 sn: uyarı yok");
        r = logic.Evaluate(new DesktopSnapshot(ptFg, new[] { ptWindow }, 1), policy, 5, T(4));
        Equal(0, CountEvents(r, "foreground_restored"), "uyarı çıkmadıysa 'geri döndü' de yok");

        // Explorer in front for more than 5 seconds: one warning, not repeated every second.
        r = logic.Evaluate(new DesktopSnapshot(explorerFg, new[] { ptWindow }, 1), policy, 5, T(10));
        r = logic.Evaluate(new DesktopSnapshot(explorerFg, new[] { ptWindow }, 1), policy, 5, T(14.9));
        Equal(0, CountEvents(r, "foreign_foreground"), "4.9 sn: henüz uyarı yok");
        r = logic.Evaluate(new DesktopSnapshot(explorerFg, new[] { ptWindow }, 1), policy, 5, T(15.1));
        Equal(1, CountEvents(r, "foreign_foreground"), "5 sn aşıldı: uyarı");
        Equal("explorer.exe", r.Events.First(e => e.Type == "foreign_foreground").Details["name"] as string, "uyarıdaki süreç adı");
        r = logic.Evaluate(new DesktopSnapshot(explorerFg, new[] { ptWindow }, 1), policy, 5, T(16));
        Equal(0, CountEvents(r, "foreign_foreground"), "aynı durum için tekrar yok");
        r = logic.Evaluate(new DesktopSnapshot(explorerFg, new[] { ptWindow }, 1), policy, 5, T(46));
        Equal(1, CountEvents(r, "foreign_foreground"), "30 sn sonra hatırlatma");
        r = logic.Evaluate(new DesktopSnapshot(ptFg, new[] { ptWindow }, 1), policy, 5, T(47));
        Equal(1, CountEvents(r, "foreground_restored"), "izinli pencere geri döndü");

        // No foreground window at all is neutral.
        r = logic.Evaluate(new DesktopSnapshot(null, new[] { ptWindow }, 1), policy, 5, T(48));
        Equal(0, r.Events.Count, "öndeki pencere yokken olay yok");

        // Helper (tool) window of a forbidden program: ignored unless it takes the foreground.
        r = logic.Evaluate(new DesktopSnapshot(ptFg, new[] { ptWindow, new ProcWindow(400, Overlay, "", false) }, 1), policy, 5, T(49));
        Equal(0, r.Kills.Count, "yardımcı pencere kapatılmaz");
        r = logic.Evaluate(new DesktopSnapshot(new ForegroundSnapshot(400, Overlay, ""), new[] { ptWindow, new ProcWindow(400, Overlay, "", false) }, 1), policy, 5, T(50));
        Equal(1, r.Kills.Count, "öne geçen izinsiz pencere kapatılır");

        // Strict mode kills every process with a visible window.
        var strict = new EnforcementLogic(999);
        r = strict.Evaluate(new DesktopSnapshot(ptFg, new[] { ptWindow, new ProcWindow(400, Overlay, "", false) }, 1), MakePolicy(appWindowsOnly: false), 5, T(0));
        Equal(1, r.Kills.Count, "katı kipte yardımcı pencere de kapatılır");

        // Windows programs are never killed, except the configured ones.
        r = strict.Evaluate(new DesktopSnapshot(ptFg, new[]
        {
            new ProcWindow(500, @"C:\Windows\System32\cmd.exe", "Komut İstemi", true),
            new ProcWindow(501, @"C:\Windows\System32\notepad.exe", "Adsız - Not Defteri", true),
            new ProcWindow(502, null, "korumalı", true),
        }, 1), policy, 5, T(1));
        Equal(1, r.Kills.Count, "Windows altında yalnızca istisna kapatılır");
        Equal(501, r.Kills.FirstOrDefault()?.Pid ?? 0, "Not Defteri kapatılır");

        // Monitors.
        var monitors = new EnforcementLogic(999);
        r = monitors.Evaluate(new DesktopSnapshot(ptFg, new[] { ptWindow }, 2), policy, 5, T(0));
        Equal(1, CountEvents(r, "monitor_change"), "başlangıçta 2 monitör: uyarı");
        r = monitors.Evaluate(new DesktopSnapshot(ptFg, new[] { ptWindow }, 2), policy, 5, T(1));
        Equal(0, CountEvents(r, "monitor_change"), "değişmedikçe tekrar yok");
        r = monitors.Evaluate(new DesktopSnapshot(ptFg, new[] { ptWindow }, 1), policy, 5, T(2));
        Equal(1, CountEvents(r, "monitor_change"), "monitör sayısı değişti: uyarı");
    }

    private static void FfmpegTests()
    {
        Console.WriteLine("ffmpeg komutu");
        var settings = StreamSettings.From(
            new StreamConfig { User = "yerel", Pass = "yerel", Fps = 5, Width = 1280, BitrateKbps = 500 },
            new StreamDto { Url = "rtsp://192.168.1.10:8554/s/2021001", User = "sinavajan", Pass = "p@ss:1/2", Fps = 3 });
        Equal("sinavajan", settings.User, "sunucunun kullanıcısı öncelikli");
        Equal(3, settings.Fps, "sunucunun fps değeri öncelikli");
        Equal(1280, settings.Width, "genişlik agent.json'dan");
        var joined = string.Join(' ', FfmpegCommand.Build(settings));
        Check(joined.Contains("-f gdigrab -framerate 3 -i desktop"), "gdigrab girişi");
        Check(joined.Contains("-vf scale=1280:-2"), "ölçekleme");
        Check(joined.Contains("-c:v libx264 -preset ultrafast -tune zerolatency"), "kodlayıcı");
        Check(joined.Contains("-b:v 500k -maxrate 500k -bufsize 1000k -g 6 -pix_fmt yuv420p"), "bit hızı ve GOP");
        Check(joined.EndsWith("-f rtsp -rtsp_transport tcp rtsp://sinavajan:p%40ss%3A1%2F2@192.168.1.10:8554/s/2021001"), "RTSP hedefi ve kodlanmış şifre");
        Check(!FfmpegCommand.ForLog(FfmpegCommand.Build(settings), settings.Pass).Contains("p%40ss"), "günlükte şifre gizli");
        var fallback = StreamSettings.From(new StreamConfig(), new StreamDto { Url = "rtsp://h:8554/s/1" });
        Equal("sinavajan", fallback.User, "sunucu vermezse agent.json kullanıcısı");
        Equal("rtsp://a:b@h:8554/s/1", FfmpegCommand.UrlWithCredentials("rtsp://x:y@h:8554/s/1", "a", "b"), "var olan kimlik değiştirilir");
    }

    private static void DiscoveryParseTests()
    {
        Console.WriteLine("Keşif yanıtı");
        var sender = new IPEndPoint(IPAddress.Parse("192.168.2.10"), 47000);
        var json = "{\"ip\":\"192.168.2.10\",\"port\":8000,\"sinif_adi\":\"B-102\",\"ogretmen_adi\":\"Ayşe Öğretmen\",\"v\":1}";
        var info = Discovery.Parse(Encoding.UTF8.GetBytes(json), sender);
        Equal("192.168.2.10", info?.Host, "sunucu adresi");
        Equal(8000, info?.Port ?? 0, "port");
        Equal("Sınıf: B-102 — Öğretmen: Ayşe Öğretmen", info?.Display, "gösterim metni");
        Check(Discovery.Parse(Encoding.UTF8.GetBytes("çöp"), sender) == null, "bozuk yanıt yok sayılır");
        Check(Discovery.Parse(Encoding.UTF8.GetBytes("{\"port\":8000}"), sender) == null, "adsız yanıt yok sayılır");
    }

    /// <summary>Talks to a running teacher server exactly like the real agent does.</summary>
    private static async Task IntegrationAsync(string? serverUrl)
    {
        Console.WriteLine("Sunucu ile uçtan uca");
        ServerInfo server;
        if (serverUrl != null)
        {
            var uri = new Uri(serverUrl);
            server = new ServerInfo { Host = uri.Host, Port = uri.Port };
        }
        else
        {
            var found = await Discovery.FindAsync(47000, TimeSpan.FromSeconds(5));
            Check(found.Count >= 1, "UDP keşif en az bir sunucu bulmalı");
            if (found.Count == 0) return;
            server = found[0];
            Console.WriteLine($"  keşif: {server.Display} ({server.Key})");
        }

        using var api = new ApiClient(server.Host, server.Port);
        var info = await api.GetInfoAsync();
        Check(info.SinifAdi.Length > 0, "/api/info sınıf adı");

        var numara = "9" + Random.Shared.Next(1000000, 9999999);
        var request = new LoginRequest
        {
            Numara = numara, Ad = "Çağrı", Soyad = "Işık", Hostname = "CORE-SMOKE",
            Mac = NetInfo.MacAddressFor(server.Host), AgentVersion = "smoke",
        };
        var session = await api.LoginAsync(request);
        api.Token = session.Token;
        Check(session.Token.Length > 20, "token");
        Check(session.Allowlist.Patterns.Count > 0, "izin listesi desenleri");
        Check(session.Allowlist.Version == session.AllowlistVersion, "izin listesi sürümü tutarlı");
        Check(session.Stream.Url.EndsWith("/s/" + numara), $"yayın adresi ({session.Stream.Url})");
        Check(session.Settings.ForegroundToleranceS > 0, "ön pencere toleransı");
        Equal("Çağrı", session.Student.Ad, "Türkçe karakterli ad gidip geliyor");
        var policy = new Policy(session.Allowlist, @"C:\Windows", Array.Empty<string?>());
        Equal(PathClass.Allowed, policy.Classify(Pt), "sunucunun listesiyle PT izinli");
        Equal(PathClass.Forbidden, policy.Classify(@"C:\Windows\System32\notepad.exe"), "sunucunun listesiyle Not Defteri kapatılır");

        var status = await api.HeartbeatAsync(new HeartbeatRequest
        {
            FgProcess = "PacketTracer.exe", FgPath = Pt, FgTitle = "Cisco Packet Tracer", Monitors = 1,
            FfmpegAlive = false, ExamStateSeen = session.ExamState,
        });
        Check(status.ExamState is "WAITING" or "RUNNING" or "ENDED", $"heartbeat durumu ({status.ExamState})");
        Check(Math.Abs(status.ServerTime - NetInfo.UnixNow()) < 300, "sunucu saati");

        await api.SendEventAsync(new EventRequest
        {
            Type = "process_killed", Ts = NetInfo.UnixNow(),
            Details = new Dictionary<string, object?> { ["name"] = "chrome.exe", ["path"] = Chrome, ["title"] = "Şahin'in sekmesi" },
        });
        var config = await api.GetConfigAsync();
        Equal(session.Allowlist.Version, config.Allowlist.Version, "/api/config sürümü");

        try
        {
            using var bad = new ApiClient(server.Host, server.Port) { Token = "yanlis" };
            await bad.HeartbeatAsync(new HeartbeatRequest());
            Check(false, "geçersiz token reddedilmeli");
        }
        catch (ApiException ex)
        {
            Equal(401, ex.Status, "geçersiz token -> 401");
            Check(ex.Message.Length > 0, "Türkçe hata metni");
        }

        if (status.ExamState == "RUNNING")
        {
            var file = await api.DownloadExamFileAsync();
            Check(file.Length > 0, "sınav dosyası indirildi");
            var work = file.Concat(Encoding.UTF8.GetBytes("\ncore-smoke " + numara)).ToArray();
            var submit = await api.SubmitAsync(work, auto: false);
            Equal(NetInfo.Sha256Hex(work), submit.Sha256, "sunucunun SHA-256 değeri yerelle aynı");
            Equal($"{numara}_CagriIsik.pka", submit.Filename, "teslim dosya adı");
            Console.WriteLine($"  teslim: {submit.Filename} {submit.Sha256[..16]}…");
        }
        else
        {
            try
            {
                await api.DownloadExamFileAsync();
                Check(false, "sınav başlamadan dosya verilmemeli");
            }
            catch (ApiException ex)
            {
                Equal(409, ex.Status, "sınav başlamadan dosya -> 409");
            }
            Console.WriteLine($"  (sınav {status.ExamState}; indirme/teslim adımı için sınavı başlatıp yeniden çalıştırın)");
        }

        try
        {
            using var dead = new ApiClient("127.0.0.1", 9);
            await dead.GetInfoAsync();
            Check(false, "kapalı porta bağlanılmamalı");
        }
        catch (ApiException ex)
        {
            Check(ex.IsNetwork, "ulaşılamayan sunucu ağ hatası olarak bildirilir");
        }
    }
}
