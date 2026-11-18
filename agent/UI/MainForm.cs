using System.Net;
using System.Text.RegularExpressions;
using SinavAjan.Core;

namespace SinavAjan.UI;

/// <summary>
/// The agent window. Steps: find the server → confirm class/teacher → log in → wait →
/// countdown → small side panel during the exam → final message.
/// </summary>
public sealed class MainForm : Form
{
    private const string AppTitle = "Sınav Ajanı";
    private static readonly Regex NumaraPattern = new("^[A-Za-z0-9]{1,20}$", RegexOptions.CultureInvariant);
    private static readonly Color Good = Color.FromArgb(22, 120, 50);
    private static readonly Color Bad = Color.FromArgb(190, 30, 30);
    private static readonly Color Muted = Color.FromArgb(90, 96, 105);

    private readonly AgentConfig _config;
    private readonly Panel _host = new() { Dock = DockStyle.Fill };
    private readonly Panel _bottom = new() { Dock = DockStyle.Bottom };
    private readonly LinkLabel _cleanLink = new();
    private readonly System.Windows.Forms.Timer _uiTimer = new() { Interval = 500 };

    private ApiClient? _api;
    private ServerInfo? _server;
    private ExamController? _controller;
    private Phase? _shownPhase;
    private bool _closeAllowed;
    private bool _searching;

    // Controls that are refreshed while a screen is shown.
    private Label? _connectionLabel;
    private Label? _streamLabel;
    private Label? _noteLabel;
    private Label? _countdownLabel;
    private Label? _remainingLabel;
    private Button? _submitButton;

    public MainForm(AgentConfig config)
    {
        _config = config;
        Text = AppTitle;
        Font = new Font("Segoe UI", 10F);
        AutoScaleMode = AutoScaleMode.Dpi;
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(Px(620), Px(480));

        _host.Padding = new Padding(Px(24), Px(20), Px(24), Px(8));
        _bottom.Height = Px(34);
        _bottom.Padding = new Padding(Px(24), Px(6), Px(24), 0);
        _cleanLink.Text = "Sınav dosyalarımı temizle";
        _cleanLink.AutoSize = true;
        _cleanLink.Dock = DockStyle.Left;
        _cleanLink.LinkClicked += (_, _) => CleanFiles();
        _bottom.Controls.Add(_cleanLink);

        Controls.Add(_host);
        Controls.Add(_bottom);

        _uiTimer.Tick += (_, _) => UpdateDynamic();
    }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        _ = DiscoverAsync();
    }

    // ------------------------------------------------------------- layout helpers

    private int Px(int logical) => LogicalToDeviceUnits(logical);

    private int WrapWidth => Math.Max(Px(160), _host.ClientSize.Width - _host.Padding.Horizontal - Px(6));

    private TableLayoutPanel NewScreen()
    {
        _connectionLabel = _streamLabel = _noteLabel = _countdownLabel = _remainingLabel = null;
        _submitButton = null;
        AcceptButton = null;
        foreach (var control in _host.Controls.Cast<Control>().ToArray())
        {
            _host.Controls.Remove(control);
            control.Dispose();
        }
        var table = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, AutoScroll = true };
        table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        _host.Controls.Add(table);
        return table;
    }

    private Label AddText(TableLayoutPanel screen, string text, float size = 10F, bool bold = false,
        Color? color = null, int gap = 10)
    {
        var label = new Label
        {
            Text = text,
            AutoSize = true,
            UseMnemonic = false, // names may contain "&"
            Font = new Font("Segoe UI", size, bold ? FontStyle.Bold : FontStyle.Regular),
            MaximumSize = new Size(WrapWidth, 0),
            Margin = new Padding(0, 0, 0, Px(gap)),
        };
        if (color != null) label.ForeColor = color.Value;
        screen.Controls.Add(label);
        return label;
    }

    private FlowLayoutPanel AddRow(TableLayoutPanel screen, int gap = 10)
    {
        var row = new FlowLayoutPanel
        {
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            WrapContents = true,
            Margin = new Padding(0, 0, 0, Px(gap)),
        };
        screen.Controls.Add(row);
        return row;
    }

    private Button NewButton(string text, bool primary = false)
    {
        var button = new Button
        {
            Text = text,
            AutoSize = true,
            UseMnemonic = false,
            Padding = new Padding(Px(12), Px(4), Px(12), Px(4)),
            Margin = new Padding(0, 0, Px(8), 0),
        };
        if (primary) button.Font = new Font("Segoe UI", 10F, FontStyle.Bold);
        return button;
    }

    private TextBox AddField(TableLayoutPanel screen, string caption, int maxLength)
    {
        AddText(screen, caption, gap: 2);
        var box = new TextBox { Width = Px(320), MaxLength = maxLength, Margin = new Padding(0, 0, 0, Px(10)) };
        screen.Controls.Add(box);
        return box;
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
        var screen = NewScreen();
        AddText(screen, "Sınav sunucusu aranıyor…", 16F, bold: true, gap: 16);
        AddText(screen, "Bağlı olduğunuz Wi-Fi ağında öğretmen bilgisayarı aranıyor. Bu işlem birkaç saniye sürer.",
            color: Muted, gap: 16);
        screen.Controls.Add(new ProgressBar
        {
            Style = ProgressBarStyle.Marquee,
            MarqueeAnimationSpeed = 30,
            Width = Px(360),
            Height = Px(14),
        });
    }

    private void ShowNotFound(string? problem)
    {
        var screen = NewScreen();
        AddText(screen, "Sınav sunucusu bulunamadı.", 16F, bold: true, color: Bad, gap: 12);
        AddText(screen, problem ?? "Öğretmeninizin verdiği Wi-Fi ağına bağlı olduğunuzdan emin olun.", 11F, gap: 16);

        var retryRow = AddRow(screen, gap: 24);
        var retry = NewButton("Tekrar dene", primary: true);
        retry.Click += (_, _) => _ = DiscoverAsync();
        retryRow.Controls.Add(retry);

        AddText(screen, "Otomatik arama çalışmıyorsa öğretmeninizin söylediği IP adresini elle girin:",
            color: Muted, gap: 4);
        var manualRow = AddRow(screen);
        var address = new TextBox { Width = Px(200), MaxLength = 64, PlaceholderText = "ör. 192.168.1.10" };
        address.Margin = new Padding(0, Px(4), Px(8), 0);
        var connect = NewButton("Bağlan");
        var error = AddText(screen, "", color: Bad);

        async Task ConnectManualAsync()
        {
            var (host, port) = ParseAddress(address.Text);
            if (host == null)
            {
                error.Text = "Geçerli bir IP adresi girin (ör. 192.168.1.10).";
                return;
            }
            connect.Enabled = false;
            error.Text = "Bağlanılıyor…";
            await ConfirmServerAsync(new ServerInfo { Host = host, Port = port });
        }

        connect.Click += async (_, _) => await ConnectManualAsync();
        manualRow.Controls.Add(address);
        manualRow.Controls.Add(connect);
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
        var screen = NewScreen();
        AddText(screen, "Birden fazla sınav sunucusu bulundu", 16F, bold: true, gap: 8);
        AddText(screen, "Sınavına gireceğiniz sınıfı ve öğretmeni seçin. Emin değilseniz öğretmeninize sorun.",
            gap: 12);
        var list = new ListBox
        {
            Width = WrapWidth,
            Height = Px(170),
            Font = new Font("Segoe UI", 12F, FontStyle.Bold),
            IntegralHeight = false,
            Margin = new Padding(0, 0, 0, Px(12)),
        };
        foreach (var server in servers) list.Items.Add($"{server.Display}   ({server.Host})");
        list.SelectedIndex = 0;
        screen.Controls.Add(list);

        var row = AddRow(screen);
        var choose = NewButton("Seç", primary: true);
        var retry = NewButton("Tekrar ara");
        choose.Click += async (_, _) =>
        {
            if (list.SelectedIndex < 0) return;
            choose.Enabled = false;
            await ConfirmServerAsync(servers[list.SelectedIndex]);
        };
        list.DoubleClick += (_, _) => choose.PerformClick();
        retry.Click += (_, _) => _ = DiscoverAsync();
        row.Controls.Add(choose);
        row.Controls.Add(retry);
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
            ShowNotFound($"{server.Host} adresindeki sunucuya bağlanılamadı ({ex.Message}) " +
                         "Doğru Wi-Fi ağına bağlı olduğunuzdan emin olun; sorun sürerse öğretmeninize haber verin.");
            return;
        }
        if (IsDisposed) return;
        ShowConfirm(server);
    }

    private void ShowConfirm(ServerInfo server)
    {
        var screen = NewScreen();
        AddText(screen, "Sınav sunucusu bulundu:", color: Muted, gap: 8);
        AddText(screen, $"Sınıf: {server.SinifAdi}", 24F, bold: true, gap: 2);
        AddText(screen, $"Öğretmen: {server.OgretmenAdi}", 24F, bold: true, gap: 18);
        AddText(screen, "Bu, sınavına gireceğiniz sınıf ve öğretmen mi?", 11F, gap: 12);

        var row = AddRow(screen, gap: 18);
        var yes = NewButton("Doğru", primary: true);
        var no = NewButton("Yanlış");
        row.Controls.Add(yes);
        row.Controls.Add(no);

        var hint = AddText(screen, "", color: Bad, gap: 10);
        AddText(screen,
            "Giriş yaptığınız andan itibaren, sınavı teslim edene veya ajanı kapatana kadar ekranınızın tamamı " +
            "öğretmen bilgisayarına aktarılır ve kaydedilir. " + server.RetentionNote,
            9F, color: Muted);

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
            hint.Text = "Yanlış Wi-Fi ağına bağlısınız. Öğretmeninizin verdiği ağa bağlanın, sonra “Tekrar ara”ya basın.";
            no.Text = "Tekrar ara";
            yes.Enabled = false;
        };
        AcceptButton = yes;
        yes.Select();
    }

    // ---------------------------------------------------------------------- login

    private void ShowLogin()
    {
        var screen = NewScreen();
        AddText(screen, _server!.Display, 11F, bold: true, color: Muted, gap: 12);
        AddText(screen, "Giriş", 16F, bold: true, gap: 12);
        var numara = AddField(screen, "Öğrenci numarası", 20);
        var ad = AddField(screen, "Ad", 60);
        var soyad = AddField(screen, "Soyad", 60);

        var row = AddRow(screen, gap: 8);
        var login = NewButton("Giriş yap", primary: true);
        var back = NewButton("Geri");
        row.Controls.Add(login);
        row.Controls.Add(back);
        var error = AddText(screen, "", color: Bad);

        back.Click += (_, _) => _ = DiscoverAsync();
        login.Click += async (_, _) =>
        {
            var request = new LoginRequest
            {
                Numara = numara.Text.Trim(),
                Ad = ad.Text.Trim(),
                Soyad = soyad.Text.Trim(),
            };
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
            error.ForeColor = Muted;
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
                error.ForeColor = Bad;
                error.Text = ex.Message;
                login.Enabled = back.Enabled = true;
            }
        };
        AcceptButton = login;
        numara.Select();
    }

    private void StartSession(LoginRequest request, LoginResponse session)
    {
        _bottom.Visible = false; // cleaning is not possible during a session
        LocalLog.Write($"giriş yapıldı: {session.Student.Numara} @ {_server!.Key}");
        _controller = new ExamController(_api!, _config, request, session);
        _controller.Changed += RefreshUi;
        _controller.Notice += text => ToastForm.ShowNotice(text);
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
                    ShowSidePanel();
                    break;
            }
        }
        UpdateDynamic();
    }

    private void ShowWaiting()
    {
        var screen = NewScreen();
        AddText(screen, _server!.Display, 11F, bold: true, color: Muted, gap: 4);
        AddText(screen, $"{_controller!.Numara} — {_controller.FullName}", 11F, gap: 18);
        AddText(screen, "Sınavın başlamasını bekleyin", 22F, bold: true, gap: 18);
        _connectionLabel = AddText(screen, "", 11F, gap: 4);
        _streamLabel = AddText(screen, "", 11F, gap: 16);
        _noteLabel = AddText(screen, "", color: Bad, gap: 12);
        AddText(screen,
            "Bu sırada Packet Tracer'ı açıp Cisco hesabınızla giriş yapın ve “Keep me logged in” seçeneğini " +
            "işaretleyin. Sınav başladığında tarayıcılar ve izin verilmeyen diğer programlar kapatılır; " +
            "kaydetmediğiniz işleri şimdi kaydedin. Bu pencereyi kapatmayın.",
            color: Muted);
    }

    private void ShowCountdown()
    {
        TopMost = true;
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        Activate();
        var screen = NewScreen();
        AddText(screen, "Sınav başlıyor.", 24F, bold: true, color: Bad, gap: 8);
        var seconds = (int)Math.Ceiling((_controller!.CountdownEndsUtc - DateTime.UtcNow).TotalSeconds);
        AddText(screen, $"İzin verilmeyen programlar {Math.Max(0, seconds)} saniye içinde kapatılacak.", 14F,
            bold: true, gap: 8);
        _countdownLabel = AddText(screen, "", 64F, bold: true, color: Bad, gap: 8);
        _noteLabel = AddText(screen, "", 11F, color: Muted, gap: 8);
        AddText(screen, "Açık işlerinizi hemen kaydedin. Sınav dosyası Packet Tracer ile kendiliğinden açılacak.",
            11F);
    }

    private void ShowSidePanel()
    {
        // The window turns into a small always-on-top panel at the right edge of the screen.
        FormBorderStyle = FormBorderStyle.FixedToolWindow;
        TopMost = true;
        Text = "Sınav";
        _host.Padding = new Padding(Px(12), Px(10), Px(12), Px(10));
        ClientSize = new Size(Px(280), Px(330));
        var area = Screen.FromControl(this).WorkingArea;
        Location = new Point(area.Right - Width - Px(8), area.Top + Px(80));

        var screen = NewScreen();
        AddText(screen, "Sınav sürüyor", 13F, bold: true, color: Good, gap: 2);
        AddText(screen, $"{_controller!.Numara} — {_controller.FullName}", 9F, color: Muted, gap: 8);
        _remainingLabel = AddText(screen, "", 13F, bold: true, gap: 6);
        _connectionLabel = AddText(screen, "", 9.5F, gap: 2);
        _streamLabel = AddText(screen, "", 9.5F, gap: 8);

        _submitButton = new Button
        {
            Text = "Teslim et",
            Font = new Font("Segoe UI", 12F, FontStyle.Bold),
            Width = WrapWidth,
            Height = Px(46),
            Margin = new Padding(0, 0, 0, Px(8)),
        };
        _submitButton.Click += async (_, _) => await SubmitClickedAsync();
        screen.Controls.Add(_submitButton);

        var open = new Button
        {
            Text = "Sınav dosyasını aç",
            Width = WrapWidth,
            Height = Px(30),
            Margin = new Padding(0, 0, 0, Px(8)),
        };
        open.Click += (_, _) => _controller?.OpenExamFile();
        screen.Controls.Add(open);

        _noteLabel = AddText(screen, "", 9F, color: Bad, gap: 0);
    }

    private void UpdateDynamic()
    {
        var controller = _controller;
        if (controller == null || IsDisposed || controller.Phase == Phase.Finished) return;

        if (_connectionLabel != null)
        {
            _connectionLabel.Text = controller.Online
                ? "●  Sunucu bağlantısı: var"
                : "●  Sunucu bağlantısı: YOK — yeniden deneniyor…";
            _connectionLabel.ForeColor = controller.Online ? Good : Bad;
        }
        if (_streamLabel != null)
        {
            var alive = controller.StreamAlive;
            _streamLabel.Text = alive ? "●  Ekran yayını: gönderiliyor" : "●  Ekran yayını: bağlanıyor…";
            _streamLabel.ForeColor = alive ? Good : Bad;
        }
        if (_countdownLabel != null)
        {
            var seconds = (int)Math.Ceiling((controller.CountdownEndsUtc - DateTime.UtcNow).TotalSeconds);
            _countdownLabel.Text = Math.Max(0, seconds).ToString();
        }
        if (_remainingLabel != null)
        {
            var remaining = controller.Remaining;
            if (remaining == null)
            {
                _remainingLabel.Text = "";
            }
            else if (remaining.Value <= TimeSpan.Zero)
            {
                _remainingLabel.Text = "Süre doldu";
                _remainingLabel.ForeColor = Bad;
            }
            else
            {
                var left = remaining.Value;
                _remainingLabel.Text = left.TotalHours >= 1
                    ? $"Kalan süre: {(int)left.TotalHours}:{left.Minutes:00}:{left.Seconds:00}"
                    : $"Kalan süre: {left.Minutes:00}:{left.Seconds:00}";
                _remainingLabel.ForeColor = left.TotalMinutes < 5 ? Bad : ForeColor;
            }
        }
        if (_noteLabel != null)
        {
            var note = controller.SessionProblem.Length > 0 ? controller.SessionProblem : controller.StatusNote;
            if (_noteLabel.Text != note) _noteLabel.Text = note;
        }
        if (_submitButton != null && !controller.Submitting && !_submitButton.Enabled)
        {
            _submitButton.Enabled = true;
            _submitButton.Text = "Teslim et";
        }
    }

    private async Task SubmitClickedAsync()
    {
        var controller = _controller;
        if (controller == null || controller.Submitting) return;

        switch (controller.CheckBeforeSubmit())
        {
            case SubmitCheck.NoFile:
                MessageBox.Show(this, "Sınav dosyası bulunamadı. “Sınav dosyasını aç” düğmesini deneyin veya " +
                                      "öğretmeninize haber verin.", AppTitle, MessageBoxButtons.OK,
                    MessageBoxIcon.Warning);
                return;
            case SubmitCheck.NotSaved:
                MessageBox.Show(this, "Önce Packet Tracer'da Ctrl+S ile kaydedin.", AppTitle, MessageBoxButtons.OK,
                    MessageBoxIcon.Warning);
                return;
        }

        var answer = MessageBox.Show(this,
            "Teslim etmek istediğinize emin misiniz? Teslimden sonra değişiklik yapamazsınız.",
            AppTitle, MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2);
        if (answer != DialogResult.Yes) return;

        if (_submitButton != null)
        {
            _submitButton.Enabled = false;
            _submitButton.Text = "Yükleniyor…";
        }
        var error = await controller.SubmitAsync();
        if (error != null && !IsDisposed && controller.Phase != Phase.Finished)
        {
            MessageBox.Show(this, $"Teslim yüklenemedi: {error}\n\nBağlantınızı kontrol edip tekrar deneyin.",
                AppTitle, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    // --------------------------------------------------------------------- ending

    private void OnFinished(FinishInfo info)
    {
        if (IsDisposed) return;
        _uiTimer.Stop();
        ToastForm.CloseCurrent();
        Hide();

        bool clean;
        using (var dialog = new FinishDialog(info))
        {
            dialog.ShowDialog();
            clean = dialog.CleanRequested;
        }
        if (clean)
        {
            var error = AgentPaths.DeleteAll();
            if (error != null)
            {
                MessageBox.Show($"Dosyalar silinemedi: {error}\n\nKlasörü elle silebilirsiniz:\n{AgentPaths.Root}",
                    AppTitle, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }
        _closeAllowed = true;
        Close();
    }

    private void CleanFiles()
    {
        if (!Directory.Exists(AgentPaths.Root))
        {
            MessageBox.Show(this, "Bu bilgisayarda silinecek sınav dosyası yok.", AppTitle, MessageBoxButtons.OK,
                MessageBoxIcon.Information);
            return;
        }
        var answer = MessageBox.Show(this,
            "Bu bilgisayardaki tüm sınav dosyalarınız (indirilen ve üzerinde çalıştığınız .pka dosyaları) ve " +
            "ajanın günlük kaydı silinecek:\n\n" + AgentPaths.Root +
            "\n\nTeslim etmediğiniz çalışmalar da silinir. Devam edilsin mi?",
            AppTitle, MessageBoxButtons.YesNo, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2);
        if (answer != DialogResult.Yes) return;

        var error = AgentPaths.DeleteAll();
        MessageBox.Show(this,
            error == null ? "Sınav dosyalarınız silindi." : $"Dosyalar silinemedi: {error}",
            AppTitle, MessageBoxButtons.OK, error == null ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
    }

    protected override async void OnFormClosing(FormClosingEventArgs e)
    {
        base.OnFormClosing(e);
        var controller = _controller;
        if (_closeAllowed || controller == null || controller.Phase == Phase.Finished) return;
        if (e.CloseReason is CloseReason.WindowsShutDown or CloseReason.TaskManagerClosing) return;

        var text = controller.Phase == Phase.Waiting
            ? "Ajanı kapatırsanız sınava katılamazsınız ve bu durum öğretmeninize bildirilir.\n\nKapatılsın mı?"
            : "Sınav devam ediyor.\n\nAjanı kapatırsanız bu durum öğretmeninize bildirilir ve dosyanız TESLİM " +
              "EDİLMEZ. Teslim etmek için “Hayır” deyip “Teslim et” düğmesini kullanın.\n\nYine de kapatılsın mı?";
        e.Cancel = true; // decided below; closing continues asynchronously
        var answer = MessageBox.Show(this, text, AppTitle, MessageBoxButtons.YesNo, MessageBoxIcon.Warning,
            MessageBoxDefaultButton.Button2);
        if (answer != DialogResult.Yes) return;

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
        _controller?.Dispose(); // stops ffmpeg; the Job Object guarantees it even on a crash
        _api?.Dispose();
        base.OnFormClosed(e);
    }
}
