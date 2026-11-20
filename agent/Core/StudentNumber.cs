namespace SinavAjan.Core;

/// <summary>The student number typed at login: exactly ten digits, nothing else.</summary>
public static class StudentNumber
{
    public const int Digits = 10;

    public const string Rule = "Öğrenci numarası 10 haneli olmalı ve yalnızca rakamlardan oluşmalı.";

    /// <summary>True for 0-9 only; other characters (letters, spaces, other scripts' digits) are not.</summary>
    public static bool IsDigit(char ch) => ch is >= '0' and <= '9';

    public static bool IsValid(string? text)
    {
        if (text == null || text.Length != Digits) return false;
        foreach (var ch in text)
        {
            if (!IsDigit(ch)) return false;
        }
        return true;
    }
}
