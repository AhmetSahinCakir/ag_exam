using System.Runtime.InteropServices;

namespace SinavAjan.UI;

public enum ToastTone
{
    Info,
    Warning,
}

/// <summary>
/// Small notice in the bottom-right corner: a headline and one or two lines of text on a
/// light card, with a coloured strip that tells a warning from plain information.
/// It never takes the keyboard focus away from Packet Tracer.
/// </summary>
public sealed class ToastForm : Form
{
    private const int WS_EX_TOPMOST = 0x00000008;
    private const int WS_EX_TOOLWINDOW = 0x00000080;
    private const int WS_EX_NOACTIVATE = 0x08000000;
    private const int CS_DROPSHADOW = 0x00020000;
    private const int DWMWA_WINDOW_CORNER_PREFERENCE = 33;
    private const int DWMWCP_ROUND = 2;

    private static ToastForm? _current;

    private readonly System.Windows.Forms.Timer _timer = new();
    private readonly Color _stripColor;
    private readonly int _stripWidth;

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

    private ToastForm(string title, string text, ToastTone tone, int seconds)
    {
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        ShowInTaskbar = false;
        BackColor = Theme.Background;
        AutoScaleMode = AutoScaleMode.Dpi;
        DoubleBuffered = true;

        _stripColor = tone == ToastTone.Warning ? Theme.Waiting : Theme.Accent;
        _stripWidth = LogicalToDeviceUnits(5);

        var area = Screen.PrimaryScreen?.WorkingArea ?? new Rectangle(0, 0, 1280, 720);
        var padX = LogicalToDeviceUnits(18);
        var padY = LogicalToDeviceUnits(14);
        var width = Math.Min(LogicalToDeviceUnits(360), area.Width / 2);
        var textWidth = width - _stripWidth - 2 * padX;
        var left = _stripWidth + padX;

        var heading = new PlainLabel
        {
            Text = title,
            Font = Theme.Semibold(10.5F),
            ForeColor = Theme.Text,
            Location = new Point(left, padY),
            MaximumSize = new Size(textWidth, 0),
        };
        Controls.Add(heading);
        var bottom = padY + heading.GetPreferredSize(Size.Empty).Height;

        if (text.Length > 0)
        {
            var body = new PlainLabel
            {
                Text = text,
                Font = Theme.Regular(10F),
                ForeColor = Theme.Muted,
                Location = new Point(left, bottom + LogicalToDeviceUnits(4)),
                MaximumSize = new Size(textWidth, 0),
            };
            Controls.Add(body);
            bottom = body.Top + body.GetPreferredSize(Size.Empty).Height;
        }

        ClientSize = new Size(width, bottom + padY);
        var margin = LogicalToDeviceUnits(16);
        Location = new Point(area.Right - Width - margin, area.Bottom - Height - margin);

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
            parameters.ClassStyle |= CS_DROPSHADOW;
            return parameters;
        }
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        try
        {
            // Rounded corners on Windows 11; Windows 10 ignores the request.
            var round = DWMWCP_ROUND;
            DwmSetWindowAttribute(Handle, DWMWA_WINDOW_CORNER_PREFERENCE, ref round, sizeof(int));
        }
        catch (Exception ex) when (ex is DllNotFoundException or EntryPointNotFoundException)
        {
            // Purely cosmetic.
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        using var border = new Pen(Theme.Line);
        e.Graphics.DrawRectangle(border, 0, 0, Width - 1, Height - 1);
        using var strip = new SolidBrush(_stripColor);
        e.Graphics.FillRectangle(strip, 0, 0, _stripWidth, Height);
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
    public static void ShowNotice(string title, string text, ToastTone tone = ToastTone.Warning, int seconds = 7)
    {
        _current?.Close();
        _current = new ToastForm(title, text, tone, seconds);
        _current.Show();
    }

    public static void CloseCurrent() => _current?.Close();
}
