namespace SinavAjan.UI;

/// <summary>
/// Final message ("Teslim alındı" / "Sınav sona erdi"). The text can be selected and
/// copied (SHA-256). Closes by itself after a while so that the agent always exits.
/// </summary>
public sealed class FinishDialog : Form
{
    private const int AutoCloseSeconds = 180;

    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 1000 };
    private readonly Button _close;
    private int _left = AutoCloseSeconds;

    /// <summary>True when the student asked to delete the local exam files.</summary>
    public bool CleanRequested { get; private set; }

    public FinishDialog(FinishInfo info)
    {
        Text = "Sınav Ajanı";
        Font = new Font("Segoe UI", 10F);
        AutoScaleMode = AutoScaleMode.Dpi;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        ShowInTaskbar = true;
        TopMost = true;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(LogicalToDeviceUnits(600), LogicalToDeviceUnits(360));
        Padding = new Padding(LogicalToDeviceUnits(18));

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3 };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var title = new Label
        {
            Text = info.Title,
            AutoSize = true,
            Font = new Font("Segoe UI", 18F, FontStyle.Bold),
            ForeColor = info.Success ? Color.FromArgb(22, 120, 50) : Color.FromArgb(190, 30, 30),
            Margin = new Padding(0, 0, 0, 12),
        };
        var message = new TextBox
        {
            Text = info.Message,
            Multiline = true,
            ReadOnly = true,
            BorderStyle = BorderStyle.None,
            BackColor = SystemColors.Control,
            Dock = DockStyle.Fill,
            ScrollBars = ScrollBars.Vertical,
            TabStop = false,
        };

        var buttons = new FlowLayoutPanel
        {
            FlowDirection = FlowDirection.RightToLeft,
            Dock = DockStyle.Fill,
            AutoSize = true,
            Margin = new Padding(0, 12, 0, 0),
        };
        _close = new Button { AutoSize = true, Padding = new Padding(12, 4, 12, 4) };
        _close.Click += (_, _) => Close();
        buttons.Controls.Add(_close);

        // Deleting is only offered when the server confirmed the submission.
        if (info.Success)
        {
            var clean = new Button
            {
                Text = "Sınav dosyalarımı temizle ve kapat",
                AutoSize = true,
                Padding = new Padding(12, 4, 12, 4),
            };
            clean.Click += (_, _) =>
            {
                CleanRequested = true;
                Close();
            };
            buttons.Controls.Add(clean);
        }

        layout.Controls.Add(title, 0, 0);
        layout.Controls.Add(message, 0, 1);
        layout.Controls.Add(buttons, 0, 2);
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

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        _timer.Dispose();
        base.OnFormClosed(e);
    }
}
