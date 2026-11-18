namespace SinavAjan.UI;

/// <summary>
/// Final message ("Teslim alındı" / "Sınav sona erdi"). The text can be selected and
/// copied (SHA-256). Closes by itself after a while so that the agent always exits.
/// </summary>
public sealed class FinishDialog : Form
{
    private const int AutoCloseSeconds = 180;
    private const int ContentWidth = 480; // logical pixels; a SHA-256 value fits on one line

    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 1000 };
    private readonly Button _close;
    private int _left = AutoCloseSeconds;

    /// <summary>True when the student asked to delete the local exam files.</summary>
    public bool CleanRequested { get; private set; }

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
        ClientSize = new Size(width + 2 * pad, LogicalToDeviceUnits(info.Success ? 360 : 330));

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 4,
            Padding = new Padding(pad, pad, pad, LogicalToDeviceUnits(22)),
            BackColor = Theme.Background,
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, width));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var title = new StatusLabel
        {
            Text = info.Title,
            Font = Theme.Semibold(15F),
            DotColor = info.Success ? Theme.Good : Theme.Bad,
            MaximumSize = new Size(width, 0),
            Margin = new Padding(0, 0, 0, LogicalToDeviceUnits(14)),
        };
        var message = new TextBox
        {
            Text = info.Message,
            Multiline = true,
            ReadOnly = true,
            BorderStyle = BorderStyle.None,
            BackColor = Theme.Background,
            ForeColor = Theme.Text,
            Font = Theme.Regular(10F),
            Dock = DockStyle.Fill,
            Margin = new Padding(0, 0, 0, LogicalToDeviceUnits(16)),
            TabStop = false,
        };

        _close = Theme.PrimaryButton("Kapat", LogicalToDeviceUnits(40));
        _close.Width = width;
        _close.Margin = new Padding(0, 0, 0, LogicalToDeviceUnits(8));
        _close.Click += (_, _) => Close();

        layout.Controls.Add(title, 0, 0);
        layout.Controls.Add(message, 0, 1);
        layout.Controls.Add(_close, 0, 2);

        // Deleting is only offered when the server confirmed the submission.
        if (info.Success)
        {
            var clean = Theme.SecondaryButton("Sınav dosyalarını bu bilgisayardan sil ve kapat",
                LogicalToDeviceUnits(36));
            clean.Width = width;
            clean.Click += (_, _) =>
            {
                CleanRequested = true;
                Close();
            };
            layout.Controls.Add(clean, 0, 3);
        }

        Controls.Add(layout);
        AcceptButton = _close;

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
