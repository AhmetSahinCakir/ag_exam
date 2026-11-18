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
        BackColor = Color.FromArgb(38, 48, 60);
        AutoScaleMode = AutoScaleMode.Dpi;

        var pad = LogicalToDeviceUnits(16);
        var area = Screen.PrimaryScreen?.WorkingArea ?? new Rectangle(0, 0, 1280, 720);
        var label = new PlainLabel
        {
            Text = text,
            Font = Theme.Regular(10.5F),
            ForeColor = Color.White,
            Location = new Point(pad, pad),
            MaximumSize = new Size(Math.Min(LogicalToDeviceUnits(420), area.Width / 2), 0),
        };
        Controls.Add(label);

        var size = label.GetPreferredSize(Size.Empty);
        ClientSize = new Size(size.Width + 2 * pad, size.Height + 2 * pad);
        Location = new Point(area.Right - Width - pad, area.Bottom - Height - pad);

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
