namespace SinavAjan.UI;

/// <summary>
/// Small notice in the bottom-right corner ("Chrome sınav sırasında kullanılamaz.").
/// It never takes the keyboard focus away from Packet Tracer.
/// </summary>
public sealed class ToastForm : Form
{
    private const int WS_EX_TOPMOST = 0x00000008;
    private const int WS_EX_TOOLWINDOW = 0x00000080;
    private const int WS_EX_NOACTIVATE = 0x08000000;

    private static ToastForm? _current;

    private readonly System.Windows.Forms.Timer _timer = new();

    private ToastForm(string text, int seconds)
    {
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        ShowInTaskbar = false;
        BackColor = Color.FromArgb(32, 36, 44);
        ForeColor = Color.White;
        AutoScaleMode = AutoScaleMode.Dpi;
        Padding = new Padding(14);

        var label = new Label
        {
            Text = text,
            AutoSize = true,
            Font = new Font("Segoe UI", 11F, FontStyle.Bold),
            ForeColor = Color.White,
            BackColor = Color.Transparent,
            Location = new Point(14, 14),
        };
        Controls.Add(label);

        var area = Screen.PrimaryScreen?.WorkingArea ?? new Rectangle(0, 0, 1280, 720);
        label.MaximumSize = new Size(Math.Min(520, area.Width / 2), 0);
        ClientSize = new Size(label.PreferredWidth + 28, label.PreferredHeight + 28);
        Location = new Point(area.Right - Width - 16, area.Bottom - Height - 16);

        _timer.Interval = Math.Max(1, seconds) * 1000;
        _timer.Tick += (_, _) => Close();
    }

    protected override bool ShowWithoutActivation => true;

    protected override CreateParams CreateParams
    {
        get
        {
            var parameters = base.CreateParams;
            parameters.ExStyle |= WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;
            return parameters;
        }
    }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        _timer.Start();
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        _timer.Dispose();
        if (ReferenceEquals(_current, this)) _current = null;
        base.OnFormClosed(e);
    }

    /// <summary>Shows a notice, replacing the previous one. Call on the UI thread.</summary>
    public static void ShowNotice(string text, int seconds = 6)
    {
        _current?.Close();
        _current = new ToastForm(text, seconds);
        _current.Show();
    }

    public static void CloseCurrent() => _current?.Close();
}
