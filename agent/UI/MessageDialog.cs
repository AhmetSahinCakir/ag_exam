namespace SinavAjan.UI;

public enum DialogTone
{
    Info,
    Question,
    Warning,
    Error,
}

/// <summary>
/// The agent's own message window, in the same calm style as its other screens: a short
/// headline, an explanation, and buttons that say what they do ("Evet, teslim et" / "Vazgeç")
/// instead of the system's Yes / No.
/// </summary>
public sealed class MessageDialog : Form
{
    private const int ContentWidth = 392; // logical pixels

    private readonly Button _initialFocus;
    private bool _confirmed;

    private MessageDialog(DialogTone tone, string title, string message, string confirmText, string? cancelText,
        bool recommendCancel, bool standalone)
    {
        Text = "Sınav Ajanı";
        Font = Theme.Regular(10F);
        ForeColor = Theme.Text;
        BackColor = Theme.Background;
        AutoScaleMode = AutoScaleMode.Dpi;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        ShowInTaskbar = standalone;
        TopMost = true; // the student just asked for it: never hidden behind another window
        StartPosition = FormStartPosition.CenterScreen;

        var width = LogicalToDeviceUnits(ContentWidth);
        var pad = LogicalToDeviceUnits(28);
        var buttonHeight = LogicalToDeviceUnits(40);

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            Padding = new Padding(pad, LogicalToDeviceUnits(26), pad, LogicalToDeviceUnits(24)),
            BackColor = Theme.Background,
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, width));

        layout.Controls.Add(new StatusLabel
        {
            Text = title,
            Font = Theme.Semibold(13.5F),
            DotColor = tone switch
            {
                DialogTone.Warning => Theme.Waiting,
                DialogTone.Error => Theme.Bad,
                _ => Theme.Accent,
            },
            MaximumSize = new Size(width, 0),
            Margin = new Padding(0, 0, 0, LogicalToDeviceUnits(12)),
        });
        layout.Controls.Add(new PlainLabel
        {
            Text = message,
            Font = Theme.Regular(10F),
            MaximumSize = new Size(width, 0),
            Margin = new Padding(0, 0, 0, LogicalToDeviceUnits(24)),
        });

        if (cancelText == null)
        {
            var ok = Theme.PrimaryButton(confirmText, buttonHeight);
            ok.Width = width;
            ok.Click += (_, _) => Close();
            layout.Controls.Add(ok);
            AcceptButton = ok;
            CancelButton = ok;
            _initialFocus = ok;
        }
        else
        {
            // "Vazgeç" is always on the left and the action on the right. The highlighted
            // button is the one we recommend; Enter never triggers something irreversible.
            var cancel = recommendCancel
                ? Theme.PrimaryButton(cancelText, buttonHeight)
                : Theme.SecondaryButton(cancelText, buttonHeight);
            var confirm = recommendCancel
                ? Theme.SecondaryButton(confirmText, buttonHeight)
                : Theme.PrimaryButton(confirmText, buttonHeight);
            cancel.Click += (_, _) => Close();
            confirm.Click += (_, _) =>
            {
                _confirmed = true;
                Close();
            };

            var gap = LogicalToDeviceUnits(10);
            var row = new TableLayoutPanel
            {
                ColumnCount = 2,
                RowCount = 1,
                Width = width,
                Height = buttonHeight,
                Margin = Padding.Empty,
                BackColor = Theme.Background,
            };
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            row.RowStyles.Add(new RowStyle(SizeType.Absolute, buttonHeight));
            cancel.Dock = DockStyle.Fill;
            cancel.Margin = new Padding(0, 0, gap / 2, 0);
            confirm.Dock = DockStyle.Fill;
            confirm.Margin = new Padding(gap - gap / 2, 0, 0, 0);
            row.Controls.Add(cancel, 0, 0);
            row.Controls.Add(confirm, 1, 0);
            layout.Controls.Add(row);

            AcceptButton = cancel;
            CancelButton = cancel;
            _initialFocus = cancel;
        }

        Controls.Add(layout);

        // Exactly as tall as the content.
        var content = layout.GetPreferredSize(new Size(width + 2 * pad, 0)).Height;
        ClientSize = new Size(width + 2 * pad, content);
    }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        _initialFocus.Select();
    }

    /// <summary>Shows a message with a single button.</summary>
    public static void Show(IWin32Window? owner, DialogTone tone, string title, string message,
        string buttonText = "Tamam")
    {
        using var dialog = new MessageDialog(tone, title, message, buttonText, null, false, owner == null);
        if (owner == null) dialog.ShowDialog();
        else dialog.ShowDialog(owner);
    }

    /// <summary>
    /// Asks before doing something. Returns true only when the student pressed
    /// <paramref name="confirmText"/>; closing the window or pressing Esc/Enter means "Vazgeç".
    /// </summary>
    /// <param name="recommendCancel">Highlight "Vazgeç" instead of the action (going on is risky).</param>
    public static bool Confirm(IWin32Window? owner, DialogTone tone, string title, string message,
        string confirmText, string cancelText = "Vazgeç", bool recommendCancel = false)
    {
        using var dialog = new MessageDialog(tone, title, message, confirmText, cancelText, recommendCancel,
            owner == null);
        if (owner == null) dialog.ShowDialog();
        else dialog.ShowDialog(owner);
        return dialog._confirmed;
    }
}
