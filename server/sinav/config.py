"""Loads and validates server/config.yaml."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_ALLOW = [
    "C:\\Program Files\\Cisco Packet Tracer*\\",
    "C:\\Program Files (x86)\\Cisco Packet Tracer*\\",
]

DEFAULT_WINDOWS_KILL = [
    "notepad.exe",
    "mspaint.exe",
    "write.exe",
    "wordpad.exe",
    "SnippingTool.exe",
    "mstsc.exe",
    "msra.exe",
    "quickassist.exe",
]


class ConfigError(ValueError):
    """Raised with a Turkish message when config.yaml is unusable."""


@dataclass
class Policy:
    """Application-control policy sent to agents (the "allowlist")."""

    patterns: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOW))
    windows_kill: list[str] = field(default_factory=lambda: list(DEFAULT_WINDOWS_KILL))
    never_kill: list[str] = field(default_factory=list)
    app_windows_only: bool = True
    foreground_tolerance_s: float = 5.0
    kill_countdown_s: int = 10

    @property
    def version(self) -> str:
        blob = json.dumps(
            [
                self.patterns,
                self.windows_kill,
                self.never_kill,
                self.app_windows_only,
                self.foreground_tolerance_s,
                self.kill_countdown_s,
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]

    def to_agent(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "patterns": self.patterns,
            "windows_kill": self.windows_kill,
            "never_kill": self.never_kill,
            "app_windows_only": self.app_windows_only,
        }


@dataclass
class Config:
    path: Path
    sinif_adi: str = "Sınıf"
    ogretmen_adi: str = "Öğretmen"
    port: int = 8000
    discovery_port: int = 47000
    panel_as_app: bool = True  # open the panel in its own window (no tabs, no address bar)
    rtsp_port: int = 8554
    stream_user: str = "sinavajan"
    stream_pass: str = "sinav-yayin-2026"
    stream_fps: int | None = None
    stream_width: int | None = None
    stream_bitrate_kbps: int | None = None
    mediamtx_api: str = "http://127.0.0.1:9997"
    mediamtx_webrtc: str = "http://127.0.0.1:8889"
    policy: Policy = field(default_factory=Policy)
    disconnect_s: float = 10.0
    dir_data: Path = Path("../data")
    dir_dist: Path = Path("../dist")
    retention_note: str = ""
    mtime: float = 0.0


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"config.yaml: '{key}' bir bölüm (alt anahtarlar) olmalı.")
    return value


def _str_list(raw: dict[str, Any], key: str, default: list[str]) -> list[str]:
    if key not in raw:
        return list(default)
    value = raw[key]
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"config.yaml: '{key}' bir liste olmalı.")
    return [str(item).strip() for item in value if str(item).strip()]


def _opt_int(raw: dict[str, Any], key: str, low: int, high: int) -> int | None:
    value = raw.get(key)
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"config.yaml: '{key}' bir sayı olmalı.") from exc
    if not low <= number <= high:
        raise ConfigError(f"config.yaml: '{key}' {low}–{high} aralığında olmalı.")
    return number


def _number(raw: dict[str, Any], key: str, default: float, low: float, high: float) -> float:
    value = raw.get(key, default)
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"config.yaml: '{key}' bir sayı olmalı.") from exc
    if not low <= number <= high:
        raise ConfigError(f"config.yaml: '{key}' {low:g}–{high:g} aralığında olmalı.")
    return number


def parse_policy(raw: dict[str, Any]) -> Policy:
    thresholds = _section(raw, "esikler")
    return Policy(
        patterns=_str_list(raw, "izin_listesi", DEFAULT_ALLOW),
        windows_kill=_str_list(raw, "windows_altinda_kapatilacaklar", DEFAULT_WINDOWS_KILL),
        never_kill=_str_list(raw, "kapatma_disi", []),
        app_windows_only=bool(raw.get("sadece_uygulama_pencereleri", True)),
        foreground_tolerance_s=_number(thresholds, "on_pencere_toleransi_sn", 5, 1, 120),
        kill_countdown_s=int(_number(thresholds, "kapatma_geri_sayim_sn", 10, 0, 120)),
    )


def load_config(path: str | Path) -> Config:
    path = Path(path).resolve()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigError(f"Ayar dosyası okunamadı: {path} ({exc})") from exc
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"config.yaml biçimi hatalı: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml üst düzeyde anahtar: değer çiftlerinden oluşmalı.")

    server = _section(raw, "sunucu")
    stream = _section(raw, "yayin")
    mediamtx = _section(raw, "mediamtx")
    thresholds = _section(raw, "esikler")
    folders = _section(raw, "klasorler")
    base = path.parent

    def folder(key: str, default: str) -> Path:
        return (base / str(folders.get(key) or default)).resolve()

    cfg = Config(
        path=path,
        sinif_adi=str(raw.get("sinif_adi") or "Sınıf").strip(),
        ogretmen_adi=str(raw.get("ogretmen_adi") or "Öğretmen").strip(),
        port=int(_number(server, "port", 8000, 1, 65535)),
        discovery_port=int(_number(server, "kesif_portu", 47000, 1, 65535)),
        panel_as_app=str(server.get("panel_penceresi") or "uygulama").strip().lower() != "tarayici",
        rtsp_port=int(_number(stream, "rtsp_portu", 8554, 1, 65535)),
        stream_user=str(stream.get("kullanici") or "").strip(),
        stream_pass=str(stream.get("sifre") or "").strip(),
        stream_fps=_opt_int(stream, "fps", 1, 30),
        stream_width=_opt_int(stream, "genislik", 320, 3840),
        stream_bitrate_kbps=_opt_int(stream, "bitrate_kbps", 50, 8000),
        mediamtx_api=str(mediamtx.get("api") or "http://127.0.0.1:9997").rstrip("/"),
        mediamtx_webrtc=str(mediamtx.get("webrtc") or "http://127.0.0.1:8889").rstrip("/"),
        policy=parse_policy(raw),
        disconnect_s=_number(thresholds, "kopma_suresi_sn", 10, 4, 300),
        dir_data=folder("veri", "../data"),
        dir_dist=folder("dagitim", "../dist"),
        retention_note=" ".join(str(raw.get("kayit_saklama_notu") or "").split()),
        mtime=path.stat().st_mtime,
    )
    return cfg


def reload_policy(cfg: Config) -> bool:
    """Re-read only the policy part of config.yaml if the file changed.

    Returns True when the policy version changed. A broken file is ignored
    (the previous policy stays in force) and the error is raised to the caller.
    """
    mtime = cfg.path.stat().st_mtime
    if mtime == cfg.mtime:
        return False
    cfg.mtime = mtime
    raw = yaml.safe_load(cfg.path.read_text(encoding="utf-8-sig")) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml üst düzeyde anahtar: değer çiftlerinden oluşmalı.")
    new_policy = parse_policy(raw)
    changed = new_policy.version != cfg.policy.version
    cfg.policy = new_policy
    return changed
