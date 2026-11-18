using System.Net;
using System.Text.RegularExpressions;
using SinavAjan.Core;
using SinavAjan.Win;

namespace SinavAjan.UI;

/// <summary>
/// The agent window. Steps: find the server → confirm class/teacher → log in → wait →
/// countdown → small panel during the exam → final message.
/// Every screen is one centred column so that headings, fields and buttons share the same edges.
/// </summary>
public sealed class MainForm : Form
{
    private const string AppTitle = "Sınav Ajanı";
    private const string PanelTitle = "Sınav";
    private const int ContentWidth = 340; // logical pixels
    private const int PanelWidth = 228;
    private static readonly Regex NumaraPattern = new("^[A-Za-z0-9]{1,20}$", RegexOptions.CultureInvariant);

    private readonly AgentConfig _config;
    private readonly TableLayoutPanel _frame;
    private readonly System.Windows.Forms.Timer _uiTimer = new() { Interval = 500 };

    private TableLayoutPanel _screen = new();
    private int _contentWidth;
    private ApiClient? _api;
    private ServerInfo? _server;
    private ExamController? _controller;
    private Phase? _shownPhase;
    private bool _closeAllowed;
    private bool _searching;
    private string _panelLayoutKey = "";
    private string _panelStage = "";

    // Controls that are refreshed while a screen is shown.
    private StatusLabel? _statusLabel;
    private PlainLabel? _noteLabel;
    private PlainLabel? _infoLabel;   // planned start (waiting) / time left (exam), when there is one
    private int _infoGap;
    private PlainLabel? _countdownLabel;
    private Button? _submitButton;
    private Button? _downloadButton;
    private string _downloadButtonText = "";

    public MainForm(AgentConfig config)
    {
        _config = config;
        Text = AppTitle;
        Font = Theme.Regular(10F);
        ForeColor = Theme.Text;
        BackColor = Theme.Background;
        AutoScaleMode = AutoScaleMode.Dpi;
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(Px(460), Px(500));

        _frame = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 3,
            RowCount = 1,
            BackColor = Theme.Background,
        };
        _frame.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        _frame.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, Px(ContentWidth)));
        _frame.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        _frame.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        Controls.Add(_frame);

        _uiTimer.Tick += (_, _) =>
        {
            _controller?.TickClock();
            UpdateDynamic();
            CheckVirtualDesktop();
        };
    }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        _ = DiscoverAsync();
    }

    // ------------------------------------------------------------- layout helpers

    private int Px(int logical) => LogicalToDeviceUnits(logical);

    /// <summary>Starts an empty screen: a single column of the given width, centred in the window.</summary>
    private void NewScreen(int logicalWidth = ContentWidth, int topPadding = 36)
    {
        _statusLabel = null;
        _noteLabel = _infoLabel = _countdownLabel = null;
        _submitButton = _downloadButton = null;
        AcceptButton = null;

        _frame.SuspendLayout();
        foreach (var control in _frame.Controls.Cast<Control>().ToArray())
        {
            _frame.Controls.Remove(control);
            control.Dispose();
        }
        _contentWidth = Px(logicalWidth);
        _frame.ColumnStyles[1].Width = _contentWidth;
        _screen = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            Margin = Padding.Empty,
            Padding = new Padding(0, Px(topPadding), 0, 0),
            BackColor = Theme.Background,
        };
        _screen.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, _contentWidth));
        _frame.Controls.Add(_screen, 1, 0);
        _frame.ResumeLayout();
    }

    private T Add<T>(T control, int gap) where T : Control
    {
        control.Margin = new Padding(0, 0, 0, Px(gap));
        _screen.Controls.Add(control);
        return control;
    }

    private PlainLabel AddLabel(string text, Font font, Color color, int gap) =>
        Add(new PlainLabel { Text = text, Font = font, ForeColor = color, MaximumSize = new Size(_contentWidth, 0) }, gap);

    private PlainLabel AddTitle(string text, int gap = 10) => AddLabel(text, Theme.Semibold(15F), Theme.Text, gap);

    private PlainLabel AddText(string text, int gap = 12) => AddLabel(text, Theme.Regular(10F), Theme.Text, gap);

    private PlainLabel AddNote(string text, int gap = 12, Color? color = null) =>
        AddLabel(text, Theme.Regular(9F), color ?? Theme.Muted, gap);

    private StatusLabel AddStatus(int gap) =>
        Add(new StatusLabel { Font = Theme.Regular(10F), MaximumSize = new Size(_contentWidth, 0) }, gap);

    private Button AddPrimary(string text, int gap = 8, int height = 40)
    {
        var button = Theme.PrimaryButton(text, Px(height));
        button.Width = _contentWidth;
        return Add(button, gap);
    }

    private Button AddSecondary(string text, int gap = 8, int height = 36)
    {
        var button = Theme.SecondaryButton(text, Px(height));
        button.Width = _contentWidth;
        return Add(button, gap);
    }

    private TextBox AddInput(string accessibleName, int maxLength, int gap)
    {
        var input = new InputBox(Theme.Regular(11F), Px(9), Px(7))
        {
            Width = _contentWidth,
            Anchor = AnchorStyles.Left | AnchorStyles.Right,
        };
        input.TextBox.MaxLength = maxLength;
        input.TextBox.AccessibleName = accessibleName;
        Add(input, gap);
        return input.TextBox;
    }

    private TextBox AddField(string caption, int maxLength)
    {
        AddLabel(caption, Theme.Regular(9F), Theme.Muted, 4);
        return AddInput(caption, maxLength, 14);
    }

    // ------------------------------------------------------------------ discovery

    private async Task DiscoverAsync()
    {
        if (_searching) return;
        _searching = true;
        try
        {
            ShowSearching();
            List<ServerInfo> servers;
            try
            {
                servers = await Discovery.FindAsync(_config.DiscoveryPort, TimeSpan.FromSeconds(5));
            }
            catch (Exception ex)
            {
                LocalLog.Write($"keşif hatası: {ex}");
                servers = new List<ServerInfo>();
            }
            if (IsDisposed) return;

            if (servers.Count == 0) ShowNotFound(null);
            else if (servers.Count == 1) await ConfirmServerAsync(servers[0]);
            else ShowServerList(servers);
        }
        finally
        {
            _searching = false;
        }
    }

    private void ShowSearching()
    {
        NewScreen();
        AddTitle("Sınav sunucusu aranıyor");
        AddNote("Bağlı olduğunuz Wi-Fi ağında sınav sunucusu aranıyor. Bu birkaç saniye sürer.", 20);
        Add(new ProgressBar
        {
            Style = ProgressBarStyle.Marquee,
            MarqueeAnimationSpeed = 30,
            Width = _contentWidth,
            Height = Px(6),
        }, 0);
    }

    private void ShowNotFound(string? problem)
    {
        NewScreen();
        AddTitle("Sınav sunucusu bulunamadı");
        AddText(problem ?? "Sınav için verilen Wi-Fi ağına bağlı olduğunuzdan emin olun.", 18);
        var retry = AddPrimary("Tekrar dene", 30);

        AddNote("Otomatik arama çalışmıyorsa size söylenen IP adresini yazın:", 6);
        var address = AddInput("Sunucu IP adresi", 64, 8);
        address.PlaceholderText = "ör. 192.168.1.10";
        var connect = AddSecondary("Bağlan", 10);
        var error = AddNote("", 0, Theme.Bad);

        connect.Click += async (_, _) =>
        {
            var (host, port) = ParseAddress(address.Text);
            if (host == null)
            {
                error.Text = "Geçerli bir IP adresi yazın (ör. 192.168.1.10).";
                return;
            }
            connect.Enabled = false;
            error.ForeColor = Theme.Muted;
            error.Text = "Bağlanılıyor…";
            await ConfirmServerAsync(new ServerInfo { Host = host, Port = port });
        };
        retry.Click += (_, _) => _ = DiscoverAsync();

        AcceptButton = retry;
        address.Enter += (_, _) => AcceptButton = connect;
        address.Leave += (_, _) => AcceptButton = retry;
        retry.Select();
    }

    private static (string? Host, int Port) ParseAddress(string input)
    {
        var text = input.Trim();
        if (text.StartsWith("http://", StringComparison.OrdinalIgnoreCase)) text = text[7..];
        text = text.TrimEnd('/');
        var port = 8000;
        var colon = text.LastIndexOf(':');
        if (colon > 0)
        {
            if (!int.TryParse(text[(colon + 1)..], out port) || port is < 1 or > 65535) return (null, 0);
            text = text[..colon];
        }
        return IPAddress.TryParse(text, out var ip) && ip.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork
            ? (ip.ToString(), port)
            : (null, 0);
    }

    private void ShowServerList(List<ServerInfo> servers)
    {
        NewScreen();
        AddTitle("Birden fazla sınav bulundu");
        AddText("Sınavına gireceğiniz sınıfı seçin.", 14);
        var list = Add(new ListBox
        {
            Width = _contentWidth,
            Height = Px(150),
            Font = Theme.Regular(11F),
            BorderStyle = BorderStyle.FixedSingle,
            IntegralHeight = false,
        }, 14);
        foreach (var server in servers)
        {
            list.Items.Add(server.OgretmenAdi.Length > 0 ? $"{server.SinifAdi} — {server.OgretmenAdi}" : server.SinifAdi);
        }
        list.SelectedIndex = 0;

        var choose = AddPrimary("Seç");
        var retry = AddSecondary("Tekrar ara", 0);
        choose.Click += async (_, _) =>
        {
            if (list.SelectedIndex < 0) return;
            choose.Enabled = false;
            await ConfirmServerAsync(servers[list.SelectedIndex]);
        };
        list.DoubleClick += (_, _) => choose.PerformClick();
        retry.Click += (_, _) => _ = DiscoverAsync();
        AcceptButton = choose;
    }

    /// <summary>Checks that the server answers over HTTP and shows the class/teacher for confirmation.</summary>
    private async Task ConfirmServerAsync(ServerInfo server)
    {
        try
        {
            using var probe = new ApiClient(server.Host, server.Port);
            var info = await probe.GetInfoAsync();
            server.SinifAdi = info.SinifAdi;
            server.OgretmenAdi = info.OgretmenAdi;
            server.RetentionNote = info.RetentionNote;
        }
        catch (ApiException ex)
        {
            LocalLog.Write($"sunucu doğrulanamadı ({server.Key}): {ex.Message}");
            if (IsDisposed) return;
            ShowNotFound($"{server.Host} adresindeki sunucuya bağlanılamadı. Doğru Wi-Fi ağına bağlı " +
                         "olduğunuzdan emin olun.");
            return;
        }
        if (IsDisposed) return;
        ShowConfirm(server);
    }

    private void ShowConfirm(ServerInfo server)
    {
        NewScreen();
        AddNote("Sınav sunucusu bulundu", 12);
        // Large on purpose: a student on the wrong Wi-Fi network must notice it here.
        var hasName = server.OgretmenAdi.Length > 0;
        AddLabel($"Sınıf: {server.SinifAdi}", Theme.Semibold(19F), Theme.Text, hasName ? 4 : 20);
        if (hasName) AddLabel(server.OgretmenAdi, Theme.Semibold(13F), Theme.Muted, 20);
        AddText("Bu sizin sınıfınız mı?", 14);

        var yes = AddPrimary("Doğru");
        var no = AddSecondary("Yanlış", 12);
        var hint = AddNote("", 12, Theme.Bad);
        AddNote(("Giriş yaptığınız andan teslim edene ya da programı kapatana kadar ekranınız izlenir ve " +
                 "kaydedilebilir. " + server.RetentionNote).Trim(), 0);

        yes.Click += (_, _) =>
        {
            _server = server;
            _api?.Dispose();
            _api = new ApiClient(server.Host, server.Port);
            ShowLogin();
        };
        var rejected = false;
        no.Click += (_, _) =>
        {
            if (rejected)
            {
                _ = DiscoverAsync(); // second click: "Tekrar ara"
                return;
            }
            rejected = true;
            hint.Text = "Yanlış Wi-Fi ağına bağlısınız. Sınav için verilen ağa bağlanın, sonra “Tekrar ara”ya basın.";
            no.Text = "Tekrar ara";
            yes.Enabled = false;
        };
        AcceptButton = yes;
        yes.Select();
    }

    // ---------------------------------------------------------------------- login

    private void ShowLogin()
    {
        NewScreen();
        AddNote(_server!.Display, 14);
        AddTitle("Giriş", 18);
        var numara = AddField("Öğrenci numarası", 20);
        var ad = AddField("Ad", 60);
        var soyad = AddField("Soyad", 60);

        var login = AddPrimary("Giriş yap");
        var back = AddSecondary("Geri", 12);
        var error = AddNote("", 0, Theme.Bad);

        back.Click += (_, _) => _ = DiscoverAsync();
        login.Click += async (_, _) =>
        {
            var request = new LoginRequest
            {
                Numara = numara.Text.Trim(),
                Ad = ad.Text.Trim(),
                Soyad = soyad.Text.Trim(),
            };
            error.ForeColor = Theme.Bad;
            if (!NumaraPattern.IsMatch(request.Numara))
            {
                error.Text = "Öğrenci numarası yalnızca harf ve rakamlardan oluşmalı.";
                numara.Focus();
                return;
            }
            if (request.Ad.Length == 0 || request.Soyad.Length == 0)
            {
                error.Text = "Ad ve soyad boş bırakılamaz.";
                return;
            }

            login.Enabled = back.Enabled = false;
            error.ForeColor = Theme.Muted;
            error.Text = "Giriş yapılıyor…";
            try
            {
                request.Hostname = Environment.MachineName;
                request.Mac = NetInfo.MacAddressFor(_server.Host);
                request.AgentVersion = Program.Version;
                var session = await _api!.LoginAsync(request);
                _api.Token = session.Token;
                if (IsDisposed) return;
                StartSession(request, session);
            }
            catch (ApiException ex)
            {
                if (IsDisposed) return;
                error.ForeColor = Theme.Bad;
                error.Text = ex.Message;
                login.Enabled = back.Enabled = true;
            }
        };
        AcceptButton = login;
        numara.Select();
    }

    private void StartSession(LoginRequest request, LoginResponse session)
    {
        LocalLog.Write($"giriş yapıldı: {session.Student.Numara} @ {_server!.Key}");
        _controller = new ExamController(_api!, _config, request, session);
        _controller.Changed += RefreshUi;
        _controller.Notice += (title, text, seconds) => ToastForm.ShowNotice(title, text, ToastTone.Warning, seconds);
        _controller.Finished += OnFinished;
        _shownPhase = null;
        _controller.Start();
        RefreshUi();
        _uiTimer.Start();
    }

    // ---------------------------------------------------------------- exam screens

    private void RefreshUi()
    {
        if (IsDisposed || _controller == null) return;
        var phase = _controller.Phase;
        if (phase != _shownPhase)
        {
            var previous = _shownPhase;
            _shownPhase = phase;
            switch (phase)
            {
                case Phase.Waiting:
                    ShowWaiting();
                    break;
                case Phase.Countdown:
                    ShowCountdown();
                    break;
                case Phase.Running:
                    ShowExamPanel();
                    break;
                case Phase.Ended:
                    // The exam is over but nothing was handed in: the panel stays where it is.
                    // It is not pushed to the front; a notice is shown and its taskbar button blinks.
                    if (previous == Phase.Running) BuildExamPanel();
                    else ShowExamPanel();
                    if (IsHandleCreated) NativeMethods.FlashTaskbar(Handle);
                    break;
            }
        }
        UpdateDynamic();
    }

    private void ShowWaiting()
    {
        NewScreen();
        AddTitle("Sınavın başlamasını bekleyin", 6);
        AddNote($"{_controller!.Numara} — {_controller.FullName}", 20);
        _infoLabel = AddLabel("", Theme.Semibold(10.5F), Theme.Text, 0);
        _infoGap = 14;
        _statusLabel = AddStatus(20);
        _noteLabel = AddNote("", 12, Theme.Bad);
        AddNote("Bu sırada Packet Tracer'ı açıp Cisco hesabınızla giriş yapın ve “Keep me logged in” seçeneğini " +
                "işaretleyin. Sınav başladığında tarayıcılar ve izin verilmeyen diğer programlar kapatılır; " +
                "kaydetmediğiniz işleri şimdi kaydedin.", 12);
        AddNote("Bu pencereyi kapatmayın.", 0);
    }

    private void ShowCountdown()
    {
        TopMost = true;
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        Activate();
        NewScreen();
        AddTitle("Sınav başlıyor.", 8);
        var seconds = (int)Math.Ceiling((_controller!.CountdownEndsUtc - DateTime.UtcNow).TotalSeconds);
        AddText($"İzin verilmeyen programlar {Math.Max(0, seconds)} saniye içinde kapatılacak.", 14);
        _countdownLabel = AddLabel("", Theme.Semibold(44F), Theme.Accent, 14);
        _noteLabel = AddNote("", 10);
        AddNote("Açık işlerinizi hemen kaydedin. Geri sayım bitince sınav dosyasını indirebileceksiniz.", 0);
    }

    /// <summary>
    /// During the exam the window becomes a small panel at the right edge of the screen. It is an
    /// ordinary window: it does not stay above Packet Tracer and never pushes itself to the front;
    /// the student opens it from the taskbar when needed. It can be moved or minimised.
    /// </summary>
    private void ShowExamPanel()
    {
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        MinimizeBox = true;
        TopMost = false;
        Text = PanelTitle;

        BuildExamPanel();
        var area = Screen.FromControl(this).WorkingArea;
        Location = new Point(area.Right - Width - Px(12), area.Top + Px(72));
    }

    private static string PanelStage(ExamController controller) =>
        (controller.Phase == Phase.Ended ? "ended|" : "") +
        (controller.ExamFileReady ? "ready|" + controller.ExamFilePath : "download");

    /// <summary>
    /// The panel shows only what the student does next: first "download the exam file" (to a
    /// place they choose), and once the file is on the computer, "submit".
    /// </summary>
    private void BuildExamPanel()
    {
        var controller = _controller!;
        _panelStage = PanelStage(controller);

        var ended = controller.Phase == Phase.Ended;
        NewScreen(PanelWidth, topPadding: 16);
        AddLabel(ended ? "Sınav bitti" : "Sınav sürüyor", Theme.Semibold(11F), Theme.Text, 2);
        AddNote($"{controller.Numara} — {controller.FullName}", 12);
        _infoLabel = AddLabel("", Theme.Semibold(10F), Theme.Text, 0);
        _infoGap = 10;
        _statusLabel = AddStatus(16);

        if (ended)
        {
            // Nothing closes when the exam ends: the file can still be handed in, as a late submission.
            _submitButton = AddPrimary("Teslim et", 12, 42);
            _submitButton.Click += async (_, _) => await SubmitClickedAsync();
            AddNote("Dosyanızı hemen teslim edin. Sınav bittiği için teslim geç olarak kaydedilecek.", 8, Theme.Bad);
            if (controller.ExamFileReady)
            {
                AddNote($"İndirilen dosya: {Path.GetFileName(controller.ExamFilePath)}", 10);
            }
        }
        else if (!controller.ExamFileReady)
        {
            _downloadButtonText = "Sınav dosyasını indir";
            _downloadButton = AddPrimary(_downloadButtonText, 10, 42);
            AddNote("Dosyayı nereye kaydedeceğinizi siz seçersiniz.", 10);
        }
        else
        {
            _submitButton = AddPrimary("Teslim et", 8, 42);
            _submitButton.Click += async (_, _) => await SubmitClickedAsync();
            _downloadButtonText = "Sınav dosyasını yeniden indir";
            _downloadButton = AddSecondary(_downloadButtonText, 12, 34);

            AddNote($"İndirilen dosya: {Path.GetFileName(controller.ExamFilePath)}", 4);
            AddNote("Bitirince Packet Tracer'da Ctrl+S ile kaydedin, “Teslim et”e basıp dosyanızı seçin.", 10);
        }
        if (_downloadButton != null) _downloadButton.Click += async (_, _) => await DownloadClickedAsync();
        _noteLabel = AddNote("", 0, Theme.Bad);

        _panelLayoutKey = "\0"; // forces FitExamPanel in UpdateDynamic
        UpdateDynamic();
    }

    /// <summary>Makes the exam panel exactly as tall as its content.</summary>
    private void FitExamPanel()
    {
        var content = _screen.GetPreferredSize(new Size(_contentWidth, 0)).Height;
        ClientSize = new Size(_contentWidth + Px(32), content + Px(16));
    }

    private void UpdateDynamic()
    {
        var controller = _controller;
        if (controller == null || IsDisposed || controller.Phase == Phase.Finished) return;

        // The exam panel changes its buttons once the exam file has been downloaded.
        var panelShown = _shownPhase is Phase.Running or Phase.Ended && controller.Phase == _shownPhase;
        if (panelShown && PanelStage(controller) != _panelStage)
        {
            BuildExamPanel();
            return;
        }

        if (_statusLabel != null)
        {
            string text;
            Color color;
            if (!controller.Online)
            {
                (text, color) = ("Sunucuya ulaşılamıyor — yeniden deneniyor…", Theme.Bad);
            }
            else if (!controller.StreamAlive)
            {
                (text, color) = ("Ekran aktarımı başlatılıyor…", Theme.Waiting);
            }
            else
            {
                text = controller.Phase == Phase.Waiting ? "Bağlı — ekranınız aktarılıyor" : "Bağlı";
                color = Theme.Good;
            }
            if (_statusLabel.Text != text) _statusLabel.Text = text;
            _statusLabel.DotColor = color;
        }

        if (_countdownLabel != null)
        {
            var seconds = (int)Math.Ceiling((controller.CountdownEndsUtc - DateTime.UtcNow).TotalSeconds);
            var text = Math.Max(0, seconds).ToString();
            if (_countdownLabel.Text != text) _countdownLabel.Text = text;
        }

        var note = "";
        if (_noteLabel != null)
        {
            note = controller.SessionProblem.Length > 0 ? controller.SessionProblem : controller.StatusNote;
            if (_noteLabel.Text != note) _noteLabel.Text = note;
        }

        if (_downloadButton != null && !controller.Downloading && !_downloadButton.Enabled)
        {
            _downloadButton.Enabled = true;
            _downloadButton.Text = _downloadButtonText;
        }
        if (_submitButton != null && !controller.Submitting && !_submitButton.Enabled)
        {
            _submitButton.Enabled = true;
            _submitButton.Text = "Teslim et";
        }

        // Shown only when a start time was planned / a time limit was set: the planned time
        // while waiting, a countdown during the exam (red in the last ten minutes).
        var info = "";
        var infoColor = Theme.Text;
        if (controller.Phase == Phase.Waiting && controller.PlannedStart is { } planned)
        {
            info = $"Sınav saat {planned:HH:mm} için planlandı.";
        }
        else if (controller.Phase == Phase.Running && controller.RemainingSeconds is { } left)
        {
            info = ExamClock.Remaining(left);
            if (ExamClock.InLastMinutes(left)) infoColor = Theme.Bad;
        }
        if (_infoLabel != null)
        {
            if (_infoLabel.Text != info)
            {
                _infoLabel.Text = info;
                _infoLabel.Margin = new Padding(0, 0, 0, info.Length > 0 ? Px(_infoGap) : 0);
            }
            if (_infoLabel.ForeColor != infoColor) _infoLabel.ForeColor = infoColor;
        }

        var layoutKey = note + (info.Length > 0 ? "\u0001" : "");
        if (panelShown && layoutKey != _panelLayoutKey)
        {
            _panelLayoutKey = layoutKey;
            FitExamPanel();
        }
    }

    /// <summary>"Sınav dosyasını indir": the student picks where to save the file.</summary>
    private async Task DownloadClickedAsync()
    {
        var controller = _controller;
        if (controller == null || controller.Downloading) return;

        string target;
        using (var dialog = new SaveFileDialog
               {
                   Title = "Sınav dosyasını kaydet",
                   FileName = "sinav.pka",
                   Filter = "Packet Tracer etkinliği (*.pka)|*.pka",
                   DefaultExt = "pka",
                   AddExtension = true,
                   OverwritePrompt = true,
                   InitialDirectory = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
               })
        {
            if (dialog.ShowDialog(this) != DialogResult.OK) return;
            target = dialog.FileName;
        }

        if (_downloadButton != null)
        {
            _downloadButton.Enabled = false;
            _downloadButton.Text = "İndiriliyor…";
        }
        var error = await controller.DownloadExamFileAsync(target);
        if (IsDisposed || controller.Phase == Phase.Finished) return;
        if (error != null)
        {
            MessageDialog.Show(this, DialogTone.Error, "Sınav dosyası indirilemedi", error);
            return;
        }
        ToastForm.ShowNotice("Sınav dosyası indirildi", "Packet Tracer'da File → Open ile açabilirsiniz.",
            ToastTone.Info);
    }

    /// <summary>
    /// "Teslim et": the student picks the file to hand in. It is read and checked on this
    /// computer first, so that a wrong or untouched file is noticed before it is uploaded.
    /// </summary>
    private async Task SubmitClickedAsync()
    {
        var controller = _controller;
        if (controller == null || controller.Submitting) return;

        string path;
        using (var dialog = new OpenFileDialog
               {
                   Title = "Teslim edilecek dosyayı seçin",
                   Filter = "Packet Tracer etkinliği (*.pka)|*.pka",
                   CheckFileExists = true,
                   Multiselect = false,
               })
        {
            // Start where the exam file was saved, with that file already filled in.
            var known = controller.ExamFilePath;
            var folder = known.Length > 0 ? Path.GetDirectoryName(known) : null;
            if (!string.IsNullOrEmpty(folder) && Directory.Exists(folder))
            {
                dialog.InitialDirectory = folder;
                if (File.Exists(known)) dialog.FileName = Path.GetFileName(known);
            }
            if (dialog.ShowDialog(this) != DialogResult.OK) return;
            path = dialog.FileName;
        }
        if (IsDisposed || !controller.CanSubmit) return;

        var candidate = await controller.InspectSubmissionAsync(path);
        if (IsDisposed || !controller.CanSubmit) return;

        var name = Path.GetFileName(path);
        var refusal = candidate.Error.Length > 0
            ? candidate.Error
            : candidate.Problem switch
            {
                SubmitProblem.NotPka => $"“{name}” bir Packet Tracer dosyası değil. Yalnızca .pka uzantılı dosya " +
                                        "teslim edilebilir.",
                SubmitProblem.Empty => $"“{name}” boş bir dosya. Doğru dosyayı seçtiğinizden emin olun.",
                SubmitProblem.TooBig => $"“{name}” çok büyük (en fazla 50 MB). Doğru dosyayı seçtiğinizden emin olun.",
                _ => "",
            };
        if (refusal.Length > 0)
        {
            MessageDialog.Show(this, DialogTone.Warning, "Bu dosya teslim edilemez", refusal);
            return;
        }

        // The student sees the file's name and when it was last saved - not where it is stored.
        var saved = candidate.LastWriteLocal;
        var confirmed = candidate.Problem switch
        {
            SubmitProblem.SameAsExamFile => MessageDialog.Confirm(this, DialogTone.Warning,
                "Dosyada değişiklik yok",
                $"“{name}” indirdiğiniz sınav dosyasının aynısı; içine hiçbir değişiklik kaydedilmemiş.\n\n" +
                "Packet Tracer'da Ctrl+S ile kaydettiğinizden ve doğru dosyayı seçtiğinizden emin olun.",
                "Yine de teslim et", recommendCancel: true),
            SubmitProblem.SavedBeforeDownload => MessageDialog.Confirm(this, DialogTone.Warning,
                "Yanlış dosya olabilir",
                $"“{name}” sınav dosyasını indirmenizden önce kaydedilmiş (son kayıt: {saved:dd.MM.yyyy HH:mm}).\n\n" +
                "Doğru dosyayı seçtiğinizden emin olun.",
                "Yine de teslim et", recommendCancel: true),
            _ => MessageDialog.Confirm(this, DialogTone.Question,
                "Teslim edilsin mi?",
                $"Dosya: {name}\nSon kayıt: {saved:HH:mm}\n\n" +
                (controller.Phase == Phase.Ended
                    ? "Sınav bittiği için bu teslim geç teslim olarak kaydedilecek."
                    : "Teslimden sonra değişiklik yapamazsınız."),
                "Evet, teslim et"),
        };
        if (!confirmed || IsDisposed || !controller.CanSubmit) return;

        if (_submitButton != null)
        {
            _submitButton.Enabled = false;
            _submitButton.Text = "Yükleniyor…";
        }
        var error = await controller.SubmitAsync(candidate);
        if (error != null && !IsDisposed && controller.Phase != Phase.Finished)
        {
            MessageDialog.Show(this, DialogTone.Error, "Teslim yüklenemedi",
                $"{error}\n\nBağlantınızı kontrol edip yeniden deneyin.");
        }
    }

    /// <summary>Reports when the student switches to another virtual desktop during the exam.</summary>
    private void CheckVirtualDesktop()
    {
        var controller = _controller;
        if (controller == null || IsDisposed || !IsHandleCreated || !controller.CanSubmit) return;
        if (VirtualDesktop.IsOnCurrentDesktop(Handle) is { } onCurrent) controller.ReportDesktop(onCurrent);
    }

    // --------------------------------------------------------------------- ending

    private void OnFinished(FinishInfo info)
    {
        if (IsDisposed) return;
        _uiTimer.Stop();
        ToastForm.CloseCurrent();
        Hide();

        using (var dialog = new FinishDialog(info))
        {
            dialog.ShowDialog();
        }
        _closeAllowed = true;
        Close();
    }

    protected override async void OnFormClosing(FormClosingEventArgs e)
    {
        base.OnFormClosing(e);
        var controller = _controller;
        if (_closeAllowed || controller == null || controller.Phase == Phase.Finished) return;
        if (e.CloseReason is CloseReason.WindowsShutDown or CloseReason.TaskManagerClosing) return;

        var text = controller.Phase switch
        {
            Phase.Waiting => "Programı kapatırsanız sınava katılamazsınız.",
            Phase.Ended => "Sınav bitti ama dosyanızı teslim etmediniz. Programı kapatırsanız dosyanız teslim " +
                           "edilmemiş olur.\n\nTeslim etmek için “Vazgeç” deyip “Teslim et” düğmesini kullanın.",
            _ => "Sınav devam ediyor. Programı kapatırsanız bu durum kaydedilir ve dosyanız teslim " +
                 "edilmez.\n\nTeslim etmek için “Vazgeç” deyip “Teslim et” düğmesini kullanın.",
        };
        e.Cancel = true; // decided below; closing continues asynchronously
        if (!MessageDialog.Confirm(this, DialogTone.Warning, "Program kapatılsın mı?", text, "Yine de kapat",
                recommendCancel: true))
        {
            return;
        }

        _closeAllowed = true;
        _uiTimer.Stop();
        Enabled = false;
        await controller.ExitByUserAsync();
        Close();
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        _uiTimer.Dispose();
        ToastForm.CloseCurrent();
        _controller?.Dispose(); // stops the screen stream; the Job Object guarantees it even on a crash
        _api?.Dispose();
        base.OnFormClosed(e);
    }
}
