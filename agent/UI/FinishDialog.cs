namespace SinavAjan.UI;

/// <summary>
/// Final message ("Teslim alındı" / "Sınav sona erdi"). Closes by itself after a while so
/// that the agent always exits.
/// </summary>
public sealed class FinishDialog : Form
{
    private const int AutoCloseSeconds = 180;
    private const int ContentWidth = 380; // logical pixels

    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 1000 };
    private readonly Button _close;
    private int _left = AutoCloseSeconds;

    public FinishDialog(FinishInfo info)
    {
        Text = "Sınav Ajanı";
        Font = Theme.Regular(10F);
        ForeColor = Theme.Text;
        BackColor = Theme.Background;
        AutoScaleMode = AutoScaleMode.Dpi;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        ShowInTaskbar = true;
        TopMost = true;
        StartPosition = FormStartPosition.CenterScreen;

        var width = LogicalToDeviceUnits(ContentWidth);
        var pad = LogicalToDeviceUnits(28);

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            Padding = new Padding(pad, pad, pad, LogicalToDeviceUnits(24)),
            BackColor = Theme.Background,
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, width));

        var title = new StatusLabel
        {
            Text = info.Title,
            Font = Theme.Semibold(15F),
            DotColor = info.Success ? Theme.Good : Theme.Bad,
            MaximumSize = new Size(width, 0),
            Margin = new Padding(0, 0, 0, LogicalToDeviceUnits(12)),
        };
        var message = new PlainLabel
        {
            Text = info.Message,
            Font = Theme.Regular(10F),
            MaximumSize = new Size(width, 0),
            Margin = new Padding(0, 0, 0, LogicalToDeviceUnits(24)),
        };
        _close = Theme.PrimaryButton("Kapat", LogicalToDeviceUnits(40));
        _close.Width = width;
        _close.Click += (_, _) => Close();

        layout.Controls.Add(title);
        layout.Controls.Add(message);
        layout.Controls.Add(_close);
        Controls.Add(layout);
        AcceptButton = _close;

        // Exactly as tall as the content.
        var content = layout.GetPreferredSize(new Size(width + 2 * pad, 0)).Height;
        ClientSize = new Size(width + 2 * pad, content);

        UpdateCloseText();
        _timer.Tick += (_, _) =>
        {
            _left--;
            if (_left <= 0) Close();
            else UpdateCloseText();
        };
        _timer.Start();
    }

    private void UpdateCloseText() => _close.Text = $"Kapat ({_left})";

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        _close.Select();
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        _timer.Dispose();
        base.OnFormClosed(e);
    }
}
