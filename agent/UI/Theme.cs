using System.Drawing.Drawing2D;

namespace SinavAjan.UI;

/// <summary>Colours, fonts and the few small controls shared by all agent windows.</summary>
internal static class Theme
{
    public static readonly Color Background = Color.White;
    public static readonly Color Text = Color.FromArgb(29, 37, 48);
    public static readonly Color Muted = Color.FromArgb(104, 114, 127);
    public static readonly Color Line = Color.FromArgb(201, 206, 214);
    public static readonly Color Accent = Color.FromArgb(43, 98, 217);
    public static readonly Color AccentDark = Color.FromArgb(34, 79, 179);
    public static readonly Color AccentDisabled = Color.FromArgb(185, 198, 230);
    public static readonly Color Hover = Color.FromArgb(241, 243, 246);
    public static readonly Color Good = Color.FromArgb(47, 158, 98);
    public static readonly Color Waiting = Color.FromArgb(194, 130, 10);
    public static readonly Color Bad = Color.FromArgb(204, 61, 61);

    public static Font Regular(float size) => new("Segoe UI", size, FontStyle.Regular);

    public static Font Semibold(float size) => new("Segoe UI Semibold", size, FontStyle.Regular);

    public static Button PrimaryButton(string text, int height)
    {
        var button = BaseButton(text, height);
        button.BackColor = Accent;
        button.ForeColor = Color.White;
        button.Font = Semibold(10.5F);
        button.FlatAppearance.BorderSize = 0;
        button.FlatAppearance.MouseOverBackColor = AccentDark;
        button.FlatAppearance.MouseDownBackColor = AccentDark;
        button.EnabledChanged += (_, _) => button.BackColor = button.Enabled ? Accent : AccentDisabled;
        return button;
    }

    public static Button SecondaryButton(string text, int height)
    {
        var button = BaseButton(text, height);
        button.BackColor = Background;
        button.ForeColor = Text;
        button.Font = Regular(10F);
        button.FlatAppearance.BorderSize = 1;
        button.FlatAppearance.BorderColor = Line;
        button.FlatAppearance.MouseOverBackColor = Hover;
        button.FlatAppearance.MouseDownBackColor = Hover;
        return button;
    }

    private static Button BaseButton(string text, int height) => new()
    {
        Text = text,
        Height = height,
        FlatStyle = FlatStyle.Flat,
        UseMnemonic = false,
        Cursor = Cursors.Hand,
        Anchor = AnchorStyles.Left | AnchorStyles.Right,
        Margin = Padding.Empty,
    };
}

/// <summary>
/// A text field with a thin, calm border that turns to the accent colour while it has the focus.
/// </summary>
internal sealed class InputBox : Panel
{
    public TextBox TextBox { get; }

    public InputBox(Font font, int horizontalPadding, int verticalPadding)
    {
        BackColor = Theme.Line; // shows through as the 1px border
        Padding = new Padding(1);
        Margin = Padding.Empty;

        var inner = new Panel
        {
            Dock = DockStyle.Fill,
            BackColor = Theme.Background,
            Padding = new Padding(horizontalPadding, verticalPadding, horizontalPadding, verticalPadding),
            Cursor = Cursors.IBeam,
        };
        TextBox = new TextBox
        {
            BorderStyle = BorderStyle.None,
            Font = font,
            Dock = DockStyle.Top,
            BackColor = Theme.Background,
            ForeColor = Theme.Text,
        };
        inner.Controls.Add(TextBox);
        Controls.Add(inner);
        Height = TextBox.PreferredHeight + 2 * verticalPadding + 2;

        inner.Click += (_, _) => TextBox.Focus();
        TextBox.Enter += (_, _) => BackColor = Theme.Accent;
        TextBox.Leave += (_, _) => BackColor = Theme.Line;
    }
}

/// <summary>
/// A label whose text starts exactly at its left edge. The standard Label insets its text
/// by an amount that grows with the font size, so headings, captions and text boxes would
/// not share one left edge.
/// </summary>
internal class PlainLabel : Label
{
    private const TextFormatFlags Flags = TextFormatFlags.NoPadding | TextFormatFlags.WordBreak |
                                          TextFormatFlags.NoPrefix | TextFormatFlags.TextBoxControl;

    public PlainLabel()
    {
        AutoSize = true;
        UseMnemonic = false;
        Margin = Padding.Empty;
        BackColor = Color.Transparent;
        ForeColor = Theme.Text;
    }

    /// <summary>Space reserved to the left of the text (used by <see cref="StatusLabel"/>).</summary>
    protected virtual int LeadingSpace => 0;

    public override Size GetPreferredSize(Size proposedSize)
    {
        if (string.IsNullOrEmpty(Text)) return Size.Empty;
        var limit = MaximumSize.Width > 0 ? MaximumSize.Width : 4096;
        var textLimit = Math.Max(1, limit - LeadingSpace);
        var size = TextRenderer.MeasureText(Text, Font, new Size(textLimit, int.MaxValue), Flags);
        return new Size(Math.Min(limit, size.Width + LeadingSpace + 1), size.Height);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var area = new Rectangle(LeadingSpace, 0, Math.Max(0, Width - LeadingSpace), Height);
        TextRenderer.DrawText(e.Graphics, Text, Font, area, ForeColor, Flags);
    }
}

/// <summary>One line of status text with a small coloured dot in front of it.</summary>
internal sealed class StatusLabel : PlainLabel
{
    private Color _dotColor = Theme.Muted;

    public Color DotColor
    {
        get => _dotColor;
        set
        {
            if (_dotColor == value) return;
            _dotColor = value;
            Invalidate();
        }
    }

    private int DotSize => Math.Max(6, (int)Math.Round(Font.Height * 0.42));

    protected override int LeadingSpace => DotSize + Math.Max(4, Font.Height / 3);

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        if (string.IsNullOrEmpty(Text)) return;
        var size = DotSize;
        var top = (Math.Min(Height, Font.Height) - size) / 2 + 1;
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using var brush = new SolidBrush(_dotColor);
        e.Graphics.FillEllipse(brush, 0, top, size, size);
    }
}
