"""The settings a person changes in the panel ("Diğer → Ayarlar").

config.yaml stays the base (ports, technical lists); what is entered in the panel is kept in
data/settings.json and laid over it. A value that was never entered in the panel is not stored,
so the base value keeps applying.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from .config import Policy

MAX_PROGRAMS = 50
MAX_NOTE = 400

# Screen picture sent by the student program. "normal" leaves the base values alone (the
# program's own: 5 pictures a second, 1280 px wide, quality 23, at most 500 kbit/s).
# bitrate_kbps is an upper limit; "crf" is the picture quality (lower = sharper, larger).
QUALITY: dict[str, dict[str, int | None]] = {
    "low": {"fps": 3, "width": 960, "bitrate_kbps": 300, "crf": 26},
    "normal": {"fps": None, "width": None, "bitrate_kbps": None, "crf": None},
    "high": {"fps": 6, "width": 1600, "bitrate_kbps": 900, "crf": 21},
}

# How a student is named in the panel (under the screens, in the list). Files and records
# always carry the number.
STUDENT_LABELS = ("name", "number", "both")
# How the panel itself looks: colours, and the size of the names under the screens and in the list.
THEMES = ("dark", "light")
TEXT_SIZES = ("small", "normal", "large")

# key -> (lowest, highest) of the numbers that can be entered in the panel
LIMITS: dict[str, tuple[int, int]] = {
    "foreground_tolerance_s": (1, 120),
    "kill_countdown_s": (0, 120),
    "disconnect_s": (4, 300),
    "close_wait_min": (1, 60),
}

_PROGRAM_NAME = re.compile(r'^[^\\/:*?"<>|%]+\.exe$', re.IGNORECASE)
_PATH_START = re.compile(r"^([A-Za-z]:\\|%[A-Za-z0-9_()]+%\\)")


class SettingsError(ValueError):
    """Raised with a Turkish message when a value entered in the panel cannot be used."""


def clean_program(text: Any) -> str:
    """One entry of "İzin verilen programlar": a program's file name (putty.exe) or a folder.

    Returns the entry as it is stored and shown. Raises SettingsError when it cannot be used.
    """
    value = " ".join(str(text or "").replace("\u00a0", " ").split()).strip('"').strip("'").strip()
    if not value:
        raise SettingsError("Program adı boş olamaz.")
    if len(value) > 200:
        raise SettingsError("Program adı çok uzun.")
    if "\\" in value or "/" in value or ":" in value or "%" in value:
        value = re.sub(r"\\{2,}", r"\\", value.replace("/", "\\"))
        if not _PATH_START.match(value):
            raise SettingsError(f"“{value}”: klasör yolu C:\\… biçiminde yazılmalı.")
        if any(char in value for char in '"<>|'):
            raise SettingsError(f"“{value}”: geçersiz karakter var.")
        # "C:\**" would allow every program on the computer.
        fixed = re.sub(r"^([A-Za-z]:|%[^%]+%)", "", value).replace("*", "").replace("?", "").replace("\\", "")
        if len(fixed) < 3:
            raise SettingsError(f"“{value}” çok geniş: bütün programlara izin vermiş olur.")
        return value
    if "." not in value:
        value += ".exe"
    if not _PROGRAM_NAME.match(value):
        raise SettingsError(f"“{value}”: programın dosya adını yazın (ör. putty.exe).")
    return value


def program_pattern(entry: str) -> str:
    """The allowlist pattern for an entry: a file name is allowed wherever it is installed."""
    if "\\" in entry:
        return entry
    return "**\\" + entry


def _number(raw: dict[str, Any], key: str, label: str) -> int | None:
    if key not in raw or raw[key] is None or raw[key] == "":
        return None
    low, high = LIMITS[key]
    try:
        number = int(float(str(raw[key]).replace(",", ".")))
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{label}: bir sayı yazın.") from exc
    if not low <= number <= high:
        raise SettingsError(f"{label}: {low} ile {high} arasında olmalı.")
    return number


def clean(raw: Any) -> dict[str, Any]:
    """Validate what the panel (or settings.json) holds. Unknown keys are dropped."""
    if not isinstance(raw, dict):
        raise SettingsError("Ayarlar okunamadı.")
    result: dict[str, Any] = {}

    if "programs" in raw:
        programs = raw["programs"]
        if not isinstance(programs, list):
            raise SettingsError("İzin verilen programlar bir liste olmalı.")
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in programs:
            entry = clean_program(item)
            if entry.lower() in seen:
                continue
            seen.add(entry.lower())
            cleaned.append(entry)
        if len(cleaned) > MAX_PROGRAMS:
            raise SettingsError(f"En çok {MAX_PROGRAMS} program eklenebilir.")
        result["programs"] = cleaned

    label = raw.get("student_label")
    if label not in (None, ""):
        if label not in STUDENT_LABELS:
            raise SettingsError("Öğrenci gösterimi: ad soyad, numara ya da ikisi birlikte olmalı.")
        result["student_label"] = label

    theme = raw.get("theme")
    if theme not in (None, ""):
        if theme not in THEMES:
            raise SettingsError("Tema: koyu ya da açık olmalı.")
        result["theme"] = theme

    text_size = raw.get("text_size")
    if text_size not in (None, ""):
        if text_size not in TEXT_SIZES:
            raise SettingsError("Yazı boyutu: küçük, normal ya da büyük olmalı.")
        result["text_size"] = text_size

    quality = raw.get("quality")
    if quality not in (None, ""):
        if quality not in QUALITY:
            raise SettingsError("Görüntü kalitesi: düşük, normal ya da yüksek olmalı.")
        result["quality"] = quality

    labels = {
        "foreground_tolerance_s": "Başka pencere uyarısı süresi",
        "kill_countdown_s": "Programları kapatmadan önceki süre",
        "disconnect_s": "Bağlantı yok sayılma süresi",
        "close_wait_min": "Panel kapanınca bekleme süresi",
    }
    for key, label in labels.items():
        number = _number(raw, key, label)
        if number is not None:
            result[key] = number

    if "retention_note" in raw and raw["retention_note"] is not None:
        note = " ".join(str(raw["retention_note"]).split())
        if len(note) > MAX_NOTE:
            raise SettingsError(f"Bilgilendirme yazısı en çok {MAX_NOTE} karakter olabilir.")
        result["retention_note"] = note
    return result


class Base:
    """The values that come from config.yaml (what applies when nothing was entered)."""

    def __init__(self, cfg: Any):
        self.capture(cfg)

    def capture(self, cfg: Any) -> None:
        self.policy: Policy = cfg.policy
        self.disconnect_s: float = cfg.disconnect_s
        self.close_after_busy_s: float = cfg.close_after_busy_s
        self.retention_note: str = cfg.retention_note
        self.stream = (cfg.stream_fps, cfg.stream_width, cfg.stream_bitrate_kbps, cfg.stream_crf)


def apply(cfg: Any, base: Base, settings: dict[str, Any]) -> None:
    """Lay the panel's settings over the base values, into cfg (what the server uses)."""
    patterns = list(base.policy.patterns)
    known = {pattern.lower() for pattern in patterns}
    for entry in settings.get("programs", []):
        pattern = program_pattern(entry)
        if pattern.lower() not in known:
            known.add(pattern.lower())
            patterns.append(pattern)
    cfg.policy = replace(
        base.policy,
        patterns=patterns,
        foreground_tolerance_s=float(settings.get("foreground_tolerance_s", base.policy.foreground_tolerance_s)),
        kill_countdown_s=int(settings.get("kill_countdown_s", base.policy.kill_countdown_s)),
    )
    cfg.disconnect_s = float(settings.get("disconnect_s", base.disconnect_s))
    cfg.close_after_busy_s = (settings["close_wait_min"] * 60.0 if "close_wait_min" in settings
                              else base.close_after_busy_s)
    cfg.retention_note = settings.get("retention_note", base.retention_note)

    preset = QUALITY.get(settings.get("quality") or "normal", QUALITY["normal"])
    fps, width, bitrate, crf = base.stream
    cfg.stream_fps = preset["fps"] or fps
    cfg.stream_width = preset["width"] or width
    cfg.stream_bitrate_kbps = preset["bitrate_kbps"] or bitrate
    cfg.stream_crf = preset["crf"] or crf


def view(base: Base, settings: dict[str, Any]) -> dict[str, Any]:
    """What the settings window shows: the values in force, and the ones "varsayılan" means."""
    defaults = {
        "programs": [],
        "quality": "normal",
        "student_label": "name",
        "theme": "dark",
        "text_size": "normal",
        "foreground_tolerance_s": int(base.policy.foreground_tolerance_s),
        "kill_countdown_s": int(base.policy.kill_countdown_s),
        "disconnect_s": int(base.disconnect_s),
        "close_wait_min": max(1, round(base.close_after_busy_s / 60)),
        "retention_note": base.retention_note,
    }
    values = dict(defaults)
    values.update(settings)
    return {
        "values": values,
        "defaults": defaults,
        "limits": {key: {"min": low, "max": high} for key, (low, high) in LIMITS.items()},
        "max_note": MAX_NOTE,
    }
