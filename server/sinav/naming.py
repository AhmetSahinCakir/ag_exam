"""Turkish-aware name normalisation and submission file naming."""

from __future__ import annotations

import re
import unicodedata

# Explicit map from the spec: ç→c, ğ→g, ı→i, İ→I, ö→o, ş→s, ü→u (both cases).
_TR_MAP = str.maketrans(
    {
        "ç": "c", "Ç": "C",
        "ğ": "g", "Ğ": "G",
        "ı": "i", "İ": "I",
        "ö": "o", "Ö": "O",
        "ş": "s", "Ş": "S",
        "ü": "u", "Ü": "U",
    }
)

# A student number is exactly this many digits, nothing else.
NUMARA_DIGITS = 10
NUMARA_RE = re.compile(rf"^[0-9]{{{NUMARA_DIGITS}}}$")
NUMARA_RULE = f"Öğrenci numarası {NUMARA_DIGITS} haneli olmalı ve yalnızca rakamlardan oluşmalı."


def ascii_fold(text: str) -> str:
    """Convert Turkish (and other accented) letters to plain ASCII."""
    text = text.translate(_TR_MAP)
    # Remaining accents (â, î, û, é ...) are decomposed and the marks dropped.
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if ord(ch) < 128)


def name_key(text: str) -> str:
    """Comparison key: case-insensitive, Turkish-insensitive, whitespace-collapsed.

    After folding, every I variant (I, İ, ı, i) becomes "i", so "IŞIK",
    "Işık" and "isik" all compare equal.
    """
    return " ".join(ascii_fold(text).lower().split())


def header_key(text: str) -> str:
    """Key for spreadsheet headers: like name_key but without any separators."""
    return re.sub(r"[^a-z0-9]", "", ascii_fold(str(text)).lower())


def camel_name(*parts: str) -> str:
    """'ahmet şahin', 'ÇAKIR' -> 'AhmetSahinCakir'."""
    words: list[str] = []
    for part in parts:
        for word in ascii_fold(part).split():
            word = re.sub(r"[^A-Za-z0-9]", "", word)
            if word:
                words.append(word[0].upper() + word[1:].lower())
    return "".join(words) or "Isimsiz"


def submission_basename(numara: str, ad: str, soyad: str) -> str:
    """File name without extension: <numara>_<AdSoyad>."""
    return f"{numara}_{camel_name(ad, soyad)}"


def normalise_mac(raw: str) -> str:
    """Return AA:BB:CC:DD:EE:FF, or '' when the value is not a usable MAC."""
    digits = re.sub(r"[^0-9A-Fa-f]", "", raw or "")
    if len(digits) != 12 or set(digits) == {"0"}:
        return ""
    digits = digits.upper()
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def natural_key(numara: str) -> tuple:
    """Sort key that orders numeric student numbers numerically."""
    return (0, int(numara), "") if numara.isdigit() else (1, 0, numara.lower())
