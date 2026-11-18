"""Exam state: students, sessions, events, submissions. In memory, persisted to JSON.

Everything here runs on the asyncio event-loop thread, so no locking is needed.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import os
import secrets
import shutil
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config
from .naming import NUMARA_RE, name_key, natural_key, normalise_mac, submission_basename
from .roster import RosterEntry

log = logging.getLogger("sinav")

WAITING = "WAITING"
RUNNING = "RUNNING"
ENDED = "ENDED"

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_ALERTS_IN_SNAPSHOT = 300

# Created inside the exam folder the teacher chooses in the panel.
RECORDINGS_DIRNAME = "Kayıtlar"
SUBMISSIONS_DIRNAME = "Teslimler"
ALERTS_DIRNAME = "Uyarılar"          # one file per student with that student's warnings
EVENTS_CSV_NAME = "olay-kaydi.csv"

# What agents are told while the teacher closes the exam for everybody ("Yeni sınav",
# "Sistemi kapat"): the program exits. Nothing is ever handed in automatically.
CLOSED = "CLOSED"
# A file that arrives this long after "Sınavı bitir" still counts as on time (an upload that
# was already on its way).
LATE_GRACE_S = 10

# A submitted file whose size is outside exam-file-size x [MIN, MAX] is reported as suspicious.
SIZE_RATIO_MIN = 0.3
SIZE_RATIO_MAX = 5

INFO = "info"
WARNING = "warning"
CRITICAL = "critical"


class ApiError(Exception):
    """An error that is reported to the caller as {"error": message}."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Submission:
    version: int
    filename: str
    sha256: str
    size: int
    ts: float
    late: bool = False  # handed in by the student after the exam had ended
    auto: bool = False  # unused; only kept so that state files of older versions still load


@dataclass
class Student:
    numara: str
    ad: str
    soyad: str
    typed_ad: str = ""
    typed_soyad: str = ""
    roster: str = "no_roster"  # no_roster | ok | name_mismatch | not_in_list
    token: str = ""
    ip: str = ""
    hostname: str = ""
    mac: str = ""
    agent_version: str = ""
    login_ts: float = 0.0
    login_count: int = 0
    last_hb_ts: float = 0.0
    fg_process: str = ""
    fg_path: str = ""
    fg_title: str = ""
    monitors: int = 0
    ffmpeg_alive: bool = False
    exam_state_seen: str = ""
    warn_count: int = 0
    ev_count: int = 0
    ack_id: int = 0  # alerts up to this event id were marked as seen by the teacher
    submitted: bool = False
    exited: bool = False
    submissions: list[Submission] = field(default_factory=list)

    # Runtime only (not persisted)
    last_hb_mono: float = 0.0
    stream_ready: bool = False
    stream_changed_mono: float = 0.0
    connected: bool = True
    lost_reason: str = ""
    lost_since_ts: float = 0.0
    file_present: bool = True  # the latest submission file is really in the submissions folder
    closed_seen: bool = False  # the agent has been told that the exam is being closed

    _RUNTIME = ("last_hb_mono", "stream_ready", "stream_changed_mono", "connected",
                "lost_reason", "lost_since_ts", "file_present", "closed_seen")

    @property
    def full_name(self) -> str:
        return f"{self.ad} {self.soyad}".strip()

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        for key in self._RUNTIME:
            data.pop(key, None)
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Student":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k not in cls._RUNTIME}
        known["submissions"] = [Submission(**s) for s in data.get("submissions", [])]
        return cls(**known)


@dataclass
class Event:
    id: int
    ts: float
    numara: str
    name: str
    type: str
    severity: str
    alert: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _clean(value: Any, limit: int = 80) -> str:
    """Single-line, trimmed, length-limited text from untrusted input."""
    text = " ".join(str(value if value is not None else "").split())
    return text[:limit]


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def describe_agent_event(kind: str, d: dict[str, Any]) -> tuple[str, bool, bool, str]:
    """Map an agent event to (severity, show_in_alert_feed, counts_as_warning, message)."""
    name = _clean(d.get("name") or d.get("process") or "?", 120)
    title = _clean(d.get("title"), 160)
    title_part = f" — pencere: “{title}”" if title else ""

    if kind == "process_killed":
        return WARNING, True, True, f"{name} kapatıldı{title_part}"
    if kind == "process_kill_failed":
        return WARNING, True, True, f"{name} kapatılamadı ({_clean(d.get('error'), 120) or 'bilinmeyen hata'})"
    if kind == "foreign_foreground":
        seconds = d.get("seconds")
        extra = f" ({int(seconds)} sn){title_part}" if isinstance(seconds, (int, float)) else title_part
        return WARNING, True, True, f"Packet Tracer dışında bir pencere önde: {name}{extra}"
    if kind == "foreground_change":
        return INFO, False, False, f"Öndeki pencere: {name}{title_part}"
    if kind == "foreground_restored":
        seconds = d.get("seconds")
        extra = f" ({int(seconds)} sn sonra)" if isinstance(seconds, (int, float)) else ""
        return INFO, False, False, f"İzinli pencere yeniden önde{extra}"
    if kind == "monitor_change":
        count = d.get("count", "?")
        previous = d.get("previous")
        extra = f" (önceki: {previous})" if previous not in (None, count) else ""
        return WARNING, True, True, f"Monitör sayısı: {count}{extra}"
    if kind == "ffmpeg_restart":
        reason = _clean(d.get("reason"), 160)
        return INFO, False, False, "Ekran yayını yeniden başlatıldı" + (f" ({reason})" if reason else "")
    if kind == "ffmpeg_missing":
        return CRITICAL, True, True, "Ekran aktarımı başlatılamadı (antivirüs engellemiş olabilir) — ekran yayını yok"
    if kind == "reconnect":
        seconds = d.get("seconds")
        extra = f" ({int(seconds)} sn kesinti)" if isinstance(seconds, (int, float)) else ""
        return INFO, False, False, f"Ajan sunucuya yeniden ulaştı{extra}"
    if kind == "exam_file_ready":
        return INFO, False, False, "Sınav dosyası indirildi"
    if kind == "exam_file_kept":
        return INFO, False, False, "Önceki oturumdan kalan sınav dosyasıyla devam ediliyor"
    if kind == "enforcement_started":
        return INFO, False, False, "Uygulama denetimi başladı"
    if kind == "desktop_switch":
        return WARNING, True, True, "Başka bir masaüstüne geçti"
    if kind == "desktop_return":
        seconds = d.get("seconds")
        extra = f" ({int(seconds)} sn sonra)" if isinstance(seconds, (int, float)) else ""
        return INFO, False, False, f"Sınav masaüstüne geri döndü{extra}"
    if kind == "agent_exit":
        return WARNING, True, True, "Ajan öğrenci tarafından kapatıldı"
    if kind == "submit_failed":
        return WARNING, True, True, f"Teslim yüklenemedi: {_clean(d.get('error'), 160) or '?'}"
    return INFO, False, False, f"Ajan olayı: {_clean(kind, 40)}"


class Store:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.state = WAITING
        self.exam_id = ""
        self.started_at = 0.0
        self.ended_at = 0.0
        # Optional time limit. Students see a countdown to ends_at. Nothing ends by itself:
        # when the time is up the panel shows "süre aşıldı" and the teacher ends the exam.
        self.duration_min = 0
        self.ends_at = 0.0
        self.time_up_noted = False
        # Chosen in the "Sınavı başlat" window. Students cannot tell: their screens are
        # streamed to the teacher either way; this only decides whether they are kept on disk.
        self.record_enabled = True
        # A start planned for a later time of day: {"at": unix time, "duration_min", "record"}.
        self.scheduled: dict[str, Any] | None = None
        self.exam_file: dict[str, Any] | None = None
        # Chosen by the teacher in the panel before the exam. Two folders are created in it:
        # "Kayıtlar" (screen recordings) and "Teslimler" (submitted files).
        self.exam_dir: Path | None = None
        # Files that were already in "Teslimler" when the folder was chosen, or that do not
        # belong to any student: never treated as a submission.
        self.ignored_files: set[str] = set()
        self.recording_applied: str | None = None  # record path last sent to MediaMTX
        self.folder_error = ""
        self.closing = False  # agents are being told that the exam is closed
        self.panel_clients = 0  # panel windows that are open right now
        self.roster: dict[str, RosterEntry] = {}
        self.roster_name = ""
        self.students: dict[str, Student] = {}
        self.tokens: dict[str, str] = {}
        self.mac_history: dict[str, list[str]] = {}
        self.events: list[Event] = []
        self.alerts: deque[Event] = deque(maxlen=MAX_ALERTS_IN_SNAPSHOT)
        self.next_event_id = 1
        self.general_ack_id = 0  # the same as Student.ack_id, for alerts that belong to no student
        self.stream_alerts_seen: set[str] = set()

        self.mediamtx_ok = False
        self.mediamtx_checked = False
        self.discovery_error = ""
        self.config_error = ""

        self._waiters: set[asyncio.Event] = set()
        self._dirty = False

        self.cfg.dir_data.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths

    @property
    def state_path(self) -> Path:
        return self.cfg.dir_data / "state.json"

    @property
    def events_path(self) -> Path:
        return self.cfg.dir_data / "events.jsonl"

    @property
    def exam_file_path(self) -> Path:
        return self.cfg.dir_data / "exam" / "sinav.pka"

    @property
    def settings_path(self) -> Path:
        return self.cfg.dir_data / "settings.json"

    @property
    def dir_submissions(self) -> Path | None:
        return self.exam_dir / SUBMISSIONS_DIRNAME if self.exam_dir else None

    @property
    def dir_recordings(self) -> Path | None:
        return self.exam_dir / RECORDINGS_DIRNAME if self.exam_dir else None

    @property
    def dir_alerts(self) -> Path | None:
        return self.exam_dir / ALERTS_DIRNAME if self.exam_dir else None

    @property
    def record_path(self) -> str:
        """MediaMTX recordPath for the chosen exam folder ("" = do not record).

        Nothing is recorded before the exam starts (students are still logging in to
        Packet Tracer then), nor when the teacher started the exam without recording.
        """
        if self.dir_recordings is None or self.state == WAITING or not self.record_enabled:
            return ""
        return str(self.dir_recordings / "%path" / "%Y-%m-%d_%H-%M-%S_%z")

    @property
    def index_path(self) -> Path | None:
        return self.dir_submissions / "index.csv" if self.exam_dir else None

    # -------------------------------------------------------------- listeners

    def subscribe(self) -> asyncio.Event:
        waiter = asyncio.Event()
        self._waiters.add(waiter)
        return waiter

    def unsubscribe(self, waiter: asyncio.Event) -> None:
        self._waiters.discard(waiter)

    def changed(self, persist: bool = True) -> None:
        if persist:
            self._dirty = True
        for waiter in self._waiters:
            waiter.set()

    # ------------------------------------------------------------ persistence

    def save(self) -> None:
        data = {
            "state": self.state,
            "exam_id": self.exam_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_min": self.duration_min,
            "ends_at": self.ends_at,
            "time_up_noted": self.time_up_noted,
            "record_enabled": self.record_enabled,
            "scheduled": self.scheduled,
            "exam_file": self.exam_file,
            "exam_dir": str(self.exam_dir) if self.exam_dir else "",
            "ignored_files": sorted(self.ignored_files),
            "roster_name": self.roster_name,
            "roster": [asdict(e) for e in self.roster.values()],
            "students": [s.to_json() for s in self.students.values()],
            "mac_history": self.mac_history,
            "next_event_id": self.next_event_id,
            "general_ack_id": self.general_ack_id,
        }
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.state_path)
        self._dirty = False

    def save_if_dirty(self) -> None:
        if self._dirty:
            try:
                self.save()
            except OSError as exc:
                log.error("Durum dosyası yazılamadı: %s", exc)

    def load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.state = data.get("state", WAITING)
            self.exam_id = data.get("exam_id", "")
            self.started_at = float(data.get("started_at") or 0)
            self.ended_at = float(data.get("ended_at") or 0)
            self.duration_min = int(data.get("duration_min") or 0)
            self.ends_at = float(data.get("ends_at") or 0)
            self.time_up_noted = bool(data.get("time_up_noted", False))
            self.record_enabled = bool(data.get("record_enabled", True))
            self.scheduled = data.get("scheduled") or None
            self.exam_file = data.get("exam_file")
            self.exam_dir = Path(data["exam_dir"]) if data.get("exam_dir") else None
            self.ignored_files = set(data.get("ignored_files") or [])
            self.roster_name = data.get("roster_name", "")
            self.roster = {e["numara"]: RosterEntry(**e) for e in data.get("roster", [])}
            self.mac_history = {k: list(v) for k, v in data.get("mac_history", {}).items()}
            self.next_event_id = int(data.get("next_event_id") or 1)
            self.general_ack_id = int(data.get("general_ack_id") or 0)
            now_mono = time.monotonic()
            for raw in data.get("students", []):
                st = Student.from_json(raw)
                # Give every restored session a fresh grace period.
                st.last_hb_mono = now_mono
                st.stream_changed_mono = now_mono
                self.students[st.numara] = st
                if st.token:
                    self.tokens[st.token] = st.numara
            if self.exam_file and not self.exam_file_path.exists():
                self.exam_file = None
        except Exception as exc:  # noqa: BLE001 - a broken state file must not stop the exam
            broken = self.state_path.with_name(f"state.bozuk-{int(time.time())}.json")
            log.error("Durum dosyası okunamadı (%s); %s olarak ayrıldı.", exc, broken.name)
            try:
                os.replace(self.state_path, broken)
            except OSError:
                pass
            self.__init__(self.cfg)
            return

        if self.events_path.exists():
            try:
                with self.events_path.open(encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = Event(**json.loads(line))
                        except (ValueError, TypeError):
                            continue
                        self.events.append(event)
                        if event.alert:
                            self.alerts.append(event)
                if self.events:
                    self.next_event_id = max(self.next_event_id, self.events[-1].id + 1)
            except OSError as exc:
                log.error("Olay kaydı okunamadı: %s", exc)
        log.info("Önceki durum yüklendi: %s, %d öğrenci, %d olay",
                 self.state, len(self.students), len(self.events))

    # ----------------------------------------------------------------- events

    def add_event(
        self,
        numara: str,
        kind: str,
        severity: str,
        message: str,
        details: dict[str, Any] | None = None,
        *,
        alert: bool | None = None,
        counts: bool | None = None,
    ) -> Event:
        if alert is None:
            alert = severity != INFO
        if counts is None:
            counts = alert and severity != INFO
        st = self.students.get(numara) if numara else None
        event = Event(
            id=self.next_event_id,
            ts=time.time(),
            numara=numara,
            name=st.full_name if st else "",
            type=kind,
            severity=severity,
            alert=alert,
            message=message,
            details=details or {},
        )
        self.next_event_id += 1
        self.events.append(event)
        if alert:
            self.alerts.append(event)
        if st is not None:
            st.ev_count += 1
            if counts:
                st.warn_count += 1
        try:
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_json(), ensure_ascii=False) + "\n")
        except OSError as exc:
            log.error("Olay kaydı yazılamadı: %s", exc)
        if st is not None and alert and severity != INFO:
            self.write_student_alerts(numara)
        self.changed()
        return event

    # ----------------------------------------------- warnings, one file per student

    def write_student_alerts(self, numara: str) -> None:
        """(Re)write "Uyarılar/<numara>_<AdSoyad>.csv" with every warning of that student."""
        folder = self.dir_alerts
        st = self.students.get(numara)
        if folder is None or st is None:
            return
        rows = [e for e in self.events if e.numara == numara and e.alert and e.severity != INFO]
        name = f"{submission_basename(st.numara, st.ad, st.soyad)}.csv"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob(f"{numara}_*.csv"):
                if old.name != name:
                    old.unlink()  # the student's name changed (list uploaded later)
            if not rows:
                return
            buffer = io.StringIO()
            writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
            writer.writerow(["zaman", "numara", "ad_soyad", "onem", "uyari"])
            for e in rows:
                writer.writerow([_fmt_time(e.ts), st.numara, st.full_name,
                                 "kritik" if e.severity == CRITICAL else "uyarı", e.message])
            # BOM so that Excel opens Turkish characters correctly.
            (folder / name).write_bytes(("\ufeff" + buffer.getvalue()).encode("utf-8"))
        except OSError as exc:
            log.error("Uyarı dosyası yazılamadı (%s): %s", name, exc)

    def write_all_student_alerts(self) -> None:
        for numara in list(self.students):
            self.write_student_alerts(numara)

    def events_for(self, numara: str) -> list[dict[str, Any]]:
        return [e.to_json() for e in self.events if e.numara == numara]

    def export_csv(self) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
        writer.writerow(["zaman", "numara", "ad_soyad", "tur", "onem", "uyari", "mesaj", "detay"])
        severity_tr = {INFO: "bilgi", WARNING: "uyarı", CRITICAL: "kritik"}
        for e in self.events:
            writer.writerow([
                _fmt_time(e.ts),
                e.numara,
                e.name,
                e.type,
                severity_tr.get(e.severity, e.severity),
                "evet" if e.alert else "",
                e.message,
                json.dumps(e.details, ensure_ascii=False) if e.details else "",
            ])
        # BOM so that Excel opens Turkish characters correctly.
        return ("\ufeff" + buffer.getvalue()).encode("utf-8")

    def ack(self, numara: str | None) -> None:
        """Mark the alerts of one student (or, with None, every alert) as seen."""
        targets = [self.students[numara]] if numara and numara in self.students else (
            list(self.students.values()) if numara is None else [])
        seen = self.next_event_id - 1
        for st in targets:
            st.warn_count = 0
            st.ack_id = seen
        if numara is None:
            self.general_ack_id = seen
        self.changed()

    # --------------------------------------------------------------- settings

    def load_settings(self) -> None:
        """Class and teacher names edited in the panel override config.yaml."""
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            self.cfg.sinif_adi = _clean(data.get("sinif_adi"), 60) or self.cfg.sinif_adi
            self.cfg.ogretmen_adi = _clean(data.get("ogretmen_adi"), 60) or self.cfg.ogretmen_adi

    def set_identity(self, sinif_adi: Any, ogretmen_adi: Any) -> None:
        if self.state == RUNNING:
            raise ApiError(409, "Sınav sürerken sınıf bilgileri değiştirilemez.")
        sinif = _clean(sinif_adi, 60)
        ogretmen = _clean(ogretmen_adi, 60)
        if not sinif or not ogretmen:
            raise ApiError(422, "Sınıf (salon) adı ve ad soyad boş bırakılamaz.")
        self.cfg.sinif_adi, self.cfg.ogretmen_adi = sinif, ogretmen
        try:
            self.settings_path.write_text(
                json.dumps({"sinif_adi": sinif, "ogretmen_adi": ogretmen}, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError as exc:
            raise ApiError(500, f"Ayar kaydedilemedi: {exc}") from exc
        self.changed()

    # ------------------------------------------------------------ exam control

    def set_exam_dir(self, raw: Any) -> Path:
        """The teacher picked the exam folder; create "Kayıtlar" and "Teslimler" in it."""
        if self.state != WAITING:
            raise ApiError(409, "Sınav klasörü yalnızca sınav başlamadan önce seçilebilir.")
        text = str(raw or "").strip().strip('"')
        if not text:
            raise ApiError(422, "Klasör seçilmedi.")
        path = Path(text).expanduser()
        if not path.is_absolute():
            raise ApiError(422, "Klasörün tam yolunu verin (ör. D:\\Sinavlar\\Vize).")
        try:
            path.mkdir(parents=True, exist_ok=True)
            (path / RECORDINGS_DIRNAME).mkdir(exist_ok=True)
            (path / SUBMISSIONS_DIRNAME).mkdir(exist_ok=True)
            (path / ALERTS_DIRNAME).mkdir(exist_ok=True)
            probe = path / SUBMISSIONS_DIRNAME / ".yazma-denemesi"
            probe.write_bytes(b"")
            probe.unlink()
        except OSError as exc:
            raise ApiError(400, f"Bu klasör kullanılamıyor: {exc}") from exc
        self.exam_dir = path.resolve()
        # Whatever is already in "Teslimler" is not a submission of this exam.
        self.ignored_files = {item.name for item in self.dir_submissions.iterdir() if item.is_file()}
        self.add_event("", "exam_dir_selected", INFO, f"Sınav klasörü seçildi: {self.exam_dir}")
        self.write_all_student_alerts()  # warnings from before the folder was chosen
        return self.exam_dir

    def set_exam_file(self, filename: str, data: bytes) -> dict[str, Any]:
        if self.state != WAITING:
            raise ApiError(409, "Sınav dosyası yalnızca sınav başlamadan önce yüklenebilir.")
        self._check_pka(filename, data)
        self.exam_file_path.parent.mkdir(parents=True, exist_ok=True)
        self.exam_file_path.write_bytes(data)
        self.exam_file = {
            "name": _clean(Path(filename).name, 120),
            "sha256": _sha256(data),
            "size": len(data),
            "uploaded_at": time.time(),
        }
        self.add_event("", "exam_file_uploaded", INFO,
                       f"Sınav dosyası yüklendi: {self.exam_file['name']} ({len(data)} bayt)")
        return self.exam_file

    def set_roster(self, entries: list[RosterEntry], filename: str) -> int:
        self.roster = {e.numara: e for e in entries}
        self.roster_name = _clean(Path(filename).name, 120)
        self.add_event("", "roster_uploaded", INFO,
                       f"Öğrenci listesi yüklendi: {self.roster_name} ({len(entries)} öğrenci)")
        # Re-check everyone who is already logged in.
        for st in self.students.values():
            self._apply_roster(st, st.typed_ad or st.ad, st.typed_soyad or st.soyad)
        self.write_all_student_alerts()  # the file names follow the names in the list
        self.changed()
        return len(entries)

    def start_exam(self, duration_min: Any = None, record: Any = True, start_at: Any = None) -> None:
        """“Sınavı başlat”: the exam file becomes downloadable and the allowlist is enforced.

        duration_min: optional time limit, shown to the students as a countdown. The exam never
                      ends by itself; the teacher ends it.
        record:       keep the screen streams on disk ("Kayıtlar").
        start_at:     unix time for a start later today; None = now.
        """
        if self.state == RUNNING:
            raise ApiError(409, "Sınav zaten başladı.")
        if self.state == ENDED:
            raise ApiError(409, "Sınav sona erdi. Yeni bir sınav için önce “Yeni sınav”a basın.")
        if self.exam_dir is None:
            raise ApiError(409, "Önce sınav klasörünü seçin.")
        if not self.exam_file:
            # Starting the exam shares the file with the students: without a file there is no exam.
            raise ApiError(409, "Önce sınav dosyasını (.pka) yükleyin.")

        duration = 0
        if duration_min not in (None, "", 0):
            try:
                duration = int(duration_min)
            except (TypeError, ValueError) as exc:
                raise ApiError(422, "Sınav süresi dakika olarak bir sayı olmalı.") from exc
            if not 1 <= duration <= 600:
                raise ApiError(422, "Sınav süresi 1 ile 600 dakika arasında olmalı.")
        record = bool(record)

        now = time.time()
        if start_at not in (None, "", 0):
            try:
                at = float(start_at)
            except (TypeError, ValueError) as exc:
                raise ApiError(422, "Başlangıç saati anlaşılamadı.") from exc
            if at > now + 24 * 3600:
                raise ApiError(422, "Başlangıç saati en fazla 24 saat sonrası olabilir.")
            if at > now + 5:
                self.scheduled = {"at": at, "duration_min": duration, "record": record}
                self.add_event("", "exam_scheduled", INFO,
                               f"Sınavın {datetime.fromtimestamp(at).strftime('%H:%M')} saatinde başlaması planlandı")
                return
        self._begin_exam(duration, record)

    def cancel_schedule(self) -> None:
        if self.state != WAITING or not self.scheduled:
            raise ApiError(409, "Planlanmış bir başlangıç yok.")
        self.scheduled = None
        self.add_event("", "exam_schedule_cancelled", INFO, "Planlanan başlangıç iptal edildi")

    def _begin_exam(self, duration: int, record: bool) -> None:
        try:
            # Whatever is in "Teslimler" before the exam starts is not a submission of this exam.
            self.dir_submissions.mkdir(parents=True, exist_ok=True)
            self.dir_recordings.mkdir(parents=True, exist_ok=True)
            self.ignored_files |= {item.name for item in self.dir_submissions.iterdir() if item.is_file()}
        except OSError as exc:
            raise ApiError(400, f"Sınav klasörüne ulaşılamıyor: {exc}") from exc
        self.scheduled = None
        self.state = RUNNING
        self.exam_id = secrets.token_hex(8)
        self.started_at = time.time()
        self.ended_at = 0.0
        self.duration_min = duration
        self.ends_at = self.started_at + duration * 60 if duration else 0.0
        self.record_enabled = record
        parts = ["Sınav başladı; sınav dosyası öğrencilerle paylaşıldı"]
        parts.append(f"süre {duration} dakika" if duration else "süre sınırı yok")
        parts.append("ekranlar kaydediliyor" if record else "ekranlar kaydedilmiyor")
        self.add_event("", "exam_started", INFO, " — ".join(parts),
                       {"duration_min": duration, "record": record})

    def extend_exam(self, minutes: Any) -> float:
        """Give extra time to a running exam.

        The deadline moves by that many minutes; when the time was already up (or there was
        no time limit) it is counted from now.
        """
        if self.state != RUNNING:
            raise ApiError(409, "Devam eden bir sınav yok.")
        try:
            extra = int(minutes)
        except (TypeError, ValueError) as exc:
            raise ApiError(422, "Ek süre dakika olarak bir sayı olmalı.") from exc
        if not 1 <= extra <= 120:
            raise ApiError(422, "Ek süre 1 ile 120 dakika arasında olmalı.")
        self.ends_at = max(self.ends_at, time.time()) + extra * 60
        self.duration_min = max(1, round((self.ends_at - self.started_at) / 60))
        self.time_up_noted = False
        self.add_event("", "exam_extended", INFO,
                       f"{extra} dakika ek süre verildi; süre {datetime.fromtimestamp(self.ends_at).strftime('%H:%M')} "
                       "saatinde doluyor")
        return self.ends_at

    def end_exam(self) -> None:
        if self.state != RUNNING:
            raise ApiError(409, "Devam eden bir sınav yok.")
        self.state = ENDED
        self.ended_at = time.time()
        self.add_event("", "exam_ended", INFO, "Sınav bitirildi")
        self.write_events_csv()

    def check_clock(self) -> None:
        """Planned start and time limit; called once per second."""
        now = time.time()
        if self.state == WAITING and self.scheduled and now >= float(self.scheduled["at"]):
            plan = self.scheduled
            try:
                self._begin_exam(int(plan.get("duration_min") or 0), bool(plan.get("record", True)))
            except ApiError as exc:
                self.scheduled = None
                self.add_event("", "exam_start_failed", CRITICAL, f"Planlanan sınav başlatılamadı: {exc.message}")
        elif self.state == RUNNING and self.ends_at and now >= self.ends_at and not self.time_up_noted:
            # The exam goes on; only the teacher is told.
            self.time_up_noted = True
            self.add_event("", "time_up", WARNING, "Sınav süresi doldu (sınav sürüyor; bitirmek için “Sınavı bitir”)")

    def write_events_csv(self) -> None:
        """Keep a copy of the event log next to the recordings and submissions."""
        if self.exam_dir is None:
            return
        try:
            (self.exam_dir / EVENTS_CSV_NAME).write_bytes(self.export_csv())
        except OSError as exc:
            log.error("Olay kaydı sınav klasörüne yazılamadı: %s", exc)

    def reset(self) -> None:
        """Forget the finished exam and return to WAITING. Nothing in the exam folder is touched."""
        if self.state == RUNNING:
            raise ApiError(409, "Sınav sürerken sıfırlanamaz. Önce sınavı bitirin.")
        self.write_events_csv()  # includes what happened after the exam ended (automatic submissions)
        if self.events_path.exists():
            # The raw log is never deleted: it moves next to the server data.
            archive = self.cfg.dir_data / "arsiv"
            archive.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            shutil.move(str(self.events_path), str(archive / f"olaylar_{stamp}.jsonl"))

        keep = {key: getattr(self, key) for key in (
            "roster", "roster_name", "_waiters", "mediamtx_ok", "mediamtx_checked",
            "discovery_error", "config_error", "recording_applied", "panel_clients")}
        self.__init__(self.cfg)
        for key, value in keep.items():
            setattr(self, key, value)
        self.add_event("", "exam_reset", INFO, "Yeni sınav hazırlandı")
        self.save()

    # --------------------------------------------------------------- agent API

    def _apply_roster(self, st: Student, typed_ad: str, typed_soyad: str) -> None:
        """Set display name and roster status; emit a warning when the status changes."""
        previous = st.roster
        if not self.roster:
            status = "no_roster"
            st.ad, st.soyad = typed_ad, typed_soyad
        else:
            entry = self.roster.get(st.numara)
            if entry is None:
                status = "not_in_list"
                st.ad, st.soyad = typed_ad, typed_soyad
            else:
                same = name_key(f"{entry.ad} {entry.soyad}") == name_key(f"{typed_ad} {typed_soyad}")
                status = "ok" if same else "name_mismatch"
                st.ad, st.soyad = entry.ad, entry.soyad
        st.roster = status
        if status == previous:
            return
        if status == "name_mismatch":
            entry = self.roster[st.numara]
            self.add_event(
                st.numara, "name_mismatch", WARNING,
                f"Ad uyuşmuyor — listede: {entry.ad} {entry.soyad}, girişte: {typed_ad} {typed_soyad}",
            )
        elif status == "not_in_list":
            self.add_event(
                st.numara, "not_in_roster", WARNING,
                f"Numara öğrenci listesinde yok (girişte: {typed_ad} {typed_soyad})",
            )

    def login(self, body: dict[str, Any], ip: str, server_host: str) -> dict[str, Any]:
        numara = _clean(body.get("numara"), 40)
        ad = _clean(body.get("ad"), 60)
        soyad = _clean(body.get("soyad"), 60)
        if not NUMARA_RE.match(numara):
            raise ApiError(422, "Öğrenci numarası yalnızca harf ve rakam içerebilir (en fazla 20 karakter).")
        if not ad or not soyad:
            raise ApiError(422, "Ad ve soyad boş bırakılamaz.")
        hostname = _clean(body.get("hostname"), 64)
        mac = normalise_mac(str(body.get("mac") or ""))
        agent_version = _clean(body.get("agent_version"), 32)

        now = time.time()
        now_mono = time.monotonic()
        where = f"IP {ip}, bilgisayar {hostname or '?'}, MAC {mac or '?'}"

        st = self.students.get(numara)
        relogin = st is not None and st.login_count > 0
        same_machine = True
        if st is not None and relogin:
            if mac and st.mac:
                same_machine = mac == st.mac
            else:
                same_machine = ip == st.ip and hostname.lower() == st.hostname.lower()
            active = (
                bool(st.token)
                and not st.submitted
                and not st.exited
                and self.state != ENDED
                and now_mono - st.last_hb_mono < self.cfg.disconnect_s
            )
            if active and not same_machine:
                self.add_event(
                    numara, "duplicate_login", WARNING,
                    f"Aynı numarayla ikinci oturum açma girişimi reddedildi — {where}",
                    {"ip": ip, "hostname": hostname, "mac": mac},
                )
                raise ApiError(
                    409,
                    "Bu numarayla başka bir bilgisayarda açık bir oturum var. "
                    "Numaranızı kontrol edin.",
                )

        if st is None:
            st = Student(numara=numara, ad=ad, soyad=soyad)
            self.students[numara] = st
        previous_where = f"IP {st.ip}, bilgisayar {st.hostname or '?'}, MAC {st.mac or '?'}"
        was_submitted = st.submitted

        if st.token:
            self.tokens.pop(st.token, None)
        st.token = secrets.token_urlsafe(32)
        self.tokens[st.token] = numara
        st.typed_ad, st.typed_soyad = ad, soyad
        st.ip, st.hostname, st.mac, st.agent_version = ip, hostname, mac, agent_version
        st.login_ts = now
        st.login_count += 1
        st.last_hb_ts = now
        st.last_hb_mono = now_mono
        st.stream_changed_mono = now_mono
        st.connected = True
        st.lost_reason = ""
        st.exited = False
        st.submitted = False
        st.ffmpeg_alive = False

        details = {"ip": ip, "hostname": hostname, "mac": mac, "agent_version": agent_version}
        if relogin:
            self.add_event(numara, "relogin", INFO, f"Yeniden bağlandı — {where}", details)
            if not same_machine:
                self.add_event(
                    numara, "machine_change", WARNING,
                    f"Farklı bir bilgisayardan yeniden giriş yaptı — önceki: {previous_where}", details,
                )
            if was_submitted and self.state == RUNNING:
                self.add_event(numara, "relogin_after_submit", WARNING,
                               "Teslim ettikten sonra yeniden giriş yaptı")
        else:
            self.add_event(numara, "login", INFO, f"Giriş yaptı — {where}", details)

        self._apply_roster(st, ad, soyad)

        if mac:
            seen = self.mac_history.setdefault(mac, [])
            if numara not in seen:
                others = list(seen)
                seen.append(numara)
                if others:
                    self.add_event(
                        numara, "mac_reuse", CRITICAL,
                        f"Bu bilgisayardan daha önce {', '.join(others)} giriş yapmıştı (MAC {mac})",
                        {"mac": mac, "others": others},
                    )

        self.changed()
        stream: dict[str, Any] = {
            "url": f"rtsp://{server_host}:{self.cfg.rtsp_port}/{numara}",
            "user": self.cfg.stream_user,
            "pass": self.cfg.stream_pass,
        }
        if self.cfg.stream_fps:
            stream["fps"] = self.cfg.stream_fps
        if self.cfg.stream_width:
            stream["width"] = self.cfg.stream_width
        if self.cfg.stream_bitrate_kbps:
            stream["bitrate_kbps"] = self.cfg.stream_bitrate_kbps

        response = {
            "token": st.token,
            "allowlist": self.cfg.policy.to_agent(),
            "settings": self.agent_settings(),
            "stream": stream,
            "student": {
                "numara": st.numara,
                "ad": st.ad,
                "soyad": st.soyad,
                "last_sha256": st.submissions[-1].sha256 if st.submissions else "",
            },
        }
        response.update(self.exam_status())
        return response

    def agent_settings(self) -> dict[str, Any]:
        return {
            "foreground_tolerance_s": self.cfg.policy.foreground_tolerance_s,
            "kill_countdown_s": self.cfg.policy.kill_countdown_s,
            "heartbeat_interval_s": 2,
        }

    def exam_status(self) -> dict[str, Any]:
        return {
            "exam_state": CLOSED if self.closing else self.state,
            "exam_id": self.exam_id,
            "allowlist_version": self.cfg.policy.version,
            "server_time": time.time(),
            "started_at": self.started_at,
            # 0 = no time limit / no planned start.
            "ends_at": self.ends_at if self.state == RUNNING else 0,
            "scheduled_at": float(self.scheduled["at"]) if self.scheduled and self.state == WAITING else 0,
        }

    def auth(self, token: str) -> Student:
        numara = self.tokens.get(token or "")
        st = self.students.get(numara) if numara else None
        if st is None:
            raise ApiError(401, "Oturum geçersiz. Yeniden giriş yapın.")
        return st

    def heartbeat(self, st: Student, body: dict[str, Any]) -> dict[str, Any]:
        st.last_hb_ts = time.time()
        st.last_hb_mono = time.monotonic()
        st.exited = False
        st.fg_process = _clean(body.get("fg_process"), 120)
        st.fg_path = _clean(body.get("fg_path"), 300)
        st.fg_title = _clean(body.get("fg_title"), 200)
        try:
            st.monitors = max(0, min(int(body.get("monitors") or 0), 64))
        except (TypeError, ValueError):
            st.monitors = 0
        st.ffmpeg_alive = bool(body.get("ffmpeg_alive"))
        st.exam_state_seen = _clean(body.get("exam_state_seen"), 16)
        self.changed(persist=False)
        status = self.exam_status()
        status["submitted"] = st.submitted and st.file_present
        if self.closing:
            st.closed_seen = True
        return status

    def close_grace_s(self) -> float:
        """How long the system keeps running after the panel window was closed.

        Short when nobody is connected. Long while student programs are connected, so that
        an accidental close or a browser crash does not end an exam: reopening the panel
        within this time keeps everything running.
        """
        busy = self.state == RUNNING or bool(self.open_agents())
        return self.cfg.close_after_busy_s if busy else self.cfg.close_after_s

    def open_agents(self) -> list[Student]:
        """Students whose program is still running and has nothing handed in."""
        now_mono = time.monotonic()
        return [st for st in self.students.values()
                if st.token and not st.submitted and not st.exited
                and now_mono - st.last_hb_mono < self.cfg.disconnect_s]

    def agent_event(self, st: Student, kind: str, details: Any, agent_ts: Any) -> None:
        kind = _clean(kind, 40)
        if not kind:
            raise ApiError(422, "Olay türü eksik.")
        clean_details: dict[str, Any] = {}
        if isinstance(details, dict):
            for key, value in list(details.items())[:20]:
                if isinstance(value, bool) or value is None:
                    clean_details[_clean(key, 40)] = value
                elif isinstance(value, (int, float)):
                    clean_details[_clean(key, 40)] = value
                else:
                    clean_details[_clean(key, 40)] = _clean(value, 300)
        if isinstance(agent_ts, (int, float)):
            clean_details["agent_ts"] = agent_ts
        severity, alert, counts, message = describe_agent_event(kind, clean_details)
        if kind == "agent_exit":
            st.exited = True
        self.add_event(st.numara, kind, severity, message, clean_details, alert=alert, counts=counts)

    # ------------------------------------------------------------- submissions

    @staticmethod
    def _check_pka(filename: str, data: bytes) -> None:
        if not filename.lower().endswith(".pka"):
            raise ApiError(400, "Yalnızca .pka uzantılı dosyalar kabul edilir.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ApiError(413, "Dosya çok büyük (en fazla 50 MB).")
        if not data:
            raise ApiError(400, "Dosya boş.")

    def submit(self, st: Student, filename: str, data: bytes, claimed_sha: str = "",
               stale: bool = False, original_name: str = "") -> dict[str, Any]:
        """A student uploaded a file. It counts only once it is really in the submissions folder."""
        if self.state == WAITING:
            raise ApiError(409, "Sınav henüz başlamadı; teslim alınamaz.")
        folder = self.dir_submissions
        if folder is None:
            raise ApiError(409, "Sınav klasörü seçilmemiş; teslim alınamıyor.")
        self._check_pka(filename, data)
        sha = _sha256(data)
        if claimed_sha and claimed_sha.strip().lower() != sha:
            # The bytes that arrived are not the bytes the student's computer sent.
            raise ApiError(400, "Dosya yüklenirken bozuldu. Yeniden deneyin.")

        base = submission_basename(st.numara, st.ad, st.soyad)
        version = len(st.submissions) + 1
        while True:
            name = f"{base}.pka" if version == 1 else f"{base}_v{version}.pka"
            target = folder / name
            if not target.exists():
                break
            version += 1  # never overwrite an existing file
        try:
            folder.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".yukleniyor")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            # Read it back: the submission is confirmed from the folder, not from memory.
            stored_ok = _sha256(target.read_bytes()) == sha
        except OSError as exc:
            log.error("Teslim dosyası yazılamadı (%s): %s", name, exc)
            raise ApiError(500, "Dosya kaydedilemedi. Yeniden deneyin.") from exc
        if not stored_ok:
            raise ApiError(500, "Dosya doğru kaydedilemedi. Yeniden deneyin.")

        submission = self._register_submission(
            st, name, data, sha, version, from_folder=False,
            original=_clean(Path((original_name or filename).replace("\\", "/")).name, 120), stale=stale)
        return {"sha256": sha, "filename": name, "version": version, "size": len(data), "verified": True,
                "late": submission.late}

    def _register_submission(self, st: Student, name: str, data: bytes, sha: str, version: int,
                             from_folder: bool, original: str = "",
                             stale: bool = False) -> Submission:
        now = time.time()
        # Handed in after the exam had ended.
        late = self.state == ENDED and now - self.ended_at > LATE_GRACE_S
        submission = Submission(version=version, filename=name, sha256=sha, size=len(data),
                                ts=now, late=late)
        st.submissions.append(submission)
        st.submitted = True
        st.file_present = True
        self._append_index(st, submission)

        if from_folder:
            label = "Teslim dosyası klasörde bulundu"
        else:
            label = "Geç teslim etti" if late else "Teslim etti"
        self.add_event(
            st.numara, "submit", INFO, f"{label}: {name}",
            {"filename": name, "sha256": sha, "size": len(data), "version": version,
             "from_folder": from_folder, "original": original, "late": late},
        )
        if late:
            minutes = max(1, round((now - self.ended_at) / 60))
            self.add_event(
                st.numara, "late_submission", WARNING,
                f"Geç teslim: dosyasını sınav bittikten {minutes} dakika sonra teslim etti",
                {"minutes": minutes, "filename": name},
            )

        exam_size = int(self.exam_file["size"]) if self.exam_file else 0
        unchanged = bool(self.exam_file) and sha == self.exam_file["sha256"]
        if unchanged:
            self.add_event(
                st.numara, "unchanged_submission", WARNING,
                "Teslim edilen dosya sınav dosyasının kendisi (hiç değişiklik kaydedilmemiş)",
                {"sha256": sha},
            )
        else:
            twins = sorted(
                (other for other in self.students.values()
                 if other.numara != st.numara and any(s.sha256 == sha for s in other.submissions)),
                key=lambda o: natural_key(o.numara),
            )
            for other in twins:
                self.add_event(
                    st.numara, "duplicate_hash", CRITICAL,
                    f"{other.numara} {other.full_name} ile birebir aynı dosyayı teslim etti",
                    {"sha256": sha, "other": other.numara},
                )
                self.add_event(
                    other.numara, "duplicate_hash", CRITICAL,
                    f"{st.numara} {st.full_name} ile birebir aynı dosyayı teslim etti",
                    {"sha256": sha, "other": st.numara},
                )
            if stale:
                self.add_event(
                    st.numara, "stale_submission", WARNING,
                    "Teslim edilen dosya, sınav dosyası indirilmeden önce kaydedilmiş — yanlış dosya olabilir",
                    {"original": original},
                )
            if exam_size and not (exam_size * SIZE_RATIO_MIN <= len(data) <= exam_size * SIZE_RATIO_MAX):
                # A Packet Tracer file cannot be opened here, but a very different size usually
                # means that the wrong file was chosen.
                self.add_event(
                    st.numara, "suspicious_size", WARNING,
                    f"Teslim edilen dosyanın boyutu sınav dosyasından çok farklı "
                    f"({len(data) // 1024} KB; sınav dosyası {exam_size // 1024} KB) — yanlış dosya olabilir",
                    {"size": len(data), "exam_size": exam_size},
                )
        self.changed()
        return submission

    def check_submission_folder(self) -> None:
        """Compare what the server believes with what is really in the "Teslimler" folder.

        * A student counts as "teslim etti" only while the submitted file is in the folder.
        * A file put into the folder by hand, named "<numara>_....pka", is taken as that
          student's submission.
        """
        folder = self.dir_submissions
        if folder is None:
            return
        try:
            names = {item.name: item for item in folder.iterdir()
                     if item.is_file() and item.suffix.lower() == ".pka"}
        except OSError as exc:
            message = f"Sınav klasörüne ulaşılamıyor: {folder}"
            if message != self.folder_error:
                log.error("%s (%s)", message, exc)
                self.folder_error = message
                self.changed(persist=False)
            return
        if self.folder_error:
            self.folder_error = ""
            self.changed(persist=False)
        if self.state == WAITING:
            return

        registered = set(self.ignored_files)
        for st in self.students.values():
            registered.update(sub.filename for sub in st.submissions)
            if not st.submissions:
                continue
            last = st.submissions[-1]
            present = last.filename in names
            if present == st.file_present:
                continue
            st.file_present = present
            if not present:
                self.add_event(st.numara, "submission_missing", CRITICAL,
                               f"Teslim dosyası klasörde bulunamıyor: {last.filename}")
            else:
                self.add_event(st.numara, "submission_back", INFO,
                               f"Teslim dosyası yeniden klasörde: {last.filename}", alert=False)

        now = time.time()
        for name in sorted(set(names) - registered):
            numara = name.split("_", 1)[0] if "_" in name else Path(name).stem
            st = self.students.get(numara)
            if st is None:
                self.ignored_files.add(name)
                self.add_event("", "unknown_submission_file", WARNING,
                               f"Teslimler klasöründe hiçbir öğrenciyle eşleşmeyen dosya var: {name}")
                continue
            path = names[name]
            try:
                if now - path.stat().st_mtime < 2:
                    continue  # may still be being copied; look again on the next pass
                data = path.read_bytes()
            except OSError:
                continue
            if not data or len(data) > MAX_UPLOAD_BYTES:
                self.ignored_files.add(name)
                continue
            self._register_submission(st, name, data, _sha256(data), len(st.submissions) + 1,
                                      from_folder=True)

    def streams_to_stop(self) -> list[str]:
        """Students whose file has arrived: their screen stream is no longer needed."""
        return [st.numara for st in self.students.values() if st.submitted and st.stream_ready]

    def _append_index(self, st: Student, sub: Submission) -> None:
        if self.index_path is None:
            return
        new = not self.index_path.exists()
        try:
            with self.index_path.open("a", newline="", encoding="utf-8-sig" if new else "utf-8") as handle:
                writer = csv.writer(handle, delimiter=";", lineterminator="\r\n")
                if new:
                    writer.writerow(["zaman", "numara", "ad", "soyad", "dosya", "sha256", "boyut",
                                     "gec_teslim", "surum", "ip", "bilgisayar", "mac"])
                writer.writerow([
                    _fmt_time(sub.ts), st.numara, st.ad, st.soyad, sub.filename, sub.sha256, sub.size,
                    "evet" if sub.late else "hayır", sub.version, st.ip, st.hostname, st.mac,
                ])
        except OSError as exc:
            log.error("index.csv yazılamadı: %s", exc)

    # ------------------------------------------------------- background checks

    def tick(self) -> None:
        """Clock (planned start, time limit) and connectivity check; called once per second."""
        self.check_clock()
        if self.state == ENDED:
            return
        now_mono = time.monotonic()
        limit = self.cfg.disconnect_s
        for st in self.students.values():
            if not st.token or st.submitted:
                continue
            hb_ok = now_mono - st.last_hb_mono < limit
            stream_ok = True
            if self.mediamtx_ok and not st.stream_ready and now_mono - st.stream_changed_mono >= limit:
                stream_ok = False
            if st.exited:
                connected, reason = False, "ajan kapatıldı"
            elif not hb_ok:
                connected, reason = False, "ajandan sinyal gelmiyor"
            elif not stream_ok:
                connected, reason = False, "ekran yayını yok"
            else:
                connected, reason = True, ""

            if connected == st.connected:
                if not connected and reason != st.lost_reason:
                    st.lost_reason = reason
                    self.changed(persist=False)
                continue
            st.connected = connected
            if not connected:
                st.lost_reason = reason
                st.lost_since_ts = time.time()
                if st.exited:
                    self.changed(persist=False)  # the agent_exit event already alerted
                else:
                    self.add_event(st.numara, "disconnected", CRITICAL,
                                   f"Bağlantı koptu — {reason}", alert=True, counts=False)
            else:
                seconds = int(time.time() - st.lost_since_ts) if st.lost_since_ts else 0
                st.lost_reason = ""
                self.add_event(st.numara, "connection_restored", INFO,
                               f"Bağlantı yeniden kuruldu ({seconds} sn sonra)", alert=True, counts=False)

    def apply_streams(self, ready_paths: set[str], publishers: dict[str, str]) -> None:
        """Update stream status from MediaMTX. publishers maps path -> publisher IP."""
        now_mono = time.monotonic()
        changed = not self.mediamtx_ok or not self.mediamtx_checked
        self.mediamtx_ok = True
        self.mediamtx_checked = True
        for st in self.students.values():
            ready = st.numara in ready_paths
            if ready != st.stream_ready:
                st.stream_ready = ready
                st.stream_changed_mono = now_mono
                changed = True

        if self.state != ENDED:
            for path, pub_ip in publishers.items():
                if not NUMARA_RE.match(path) or not pub_ip:
                    continue
                numara = path
                key = f"{numara}|{pub_ip}"
                if key in self.stream_alerts_seen:
                    continue
                st = self.students.get(numara)
                if st is None or not st.token:
                    self.stream_alerts_seen.add(key)
                    self.add_event("", "stream_without_login", WARNING,
                                   f"Giriş yapmamış bir numara için ekran yayını var: {numara} (IP {pub_ip})",
                                   {"numara": numara, "ip": pub_ip})
                elif st.ip and st.ip != pub_ip:
                    self.stream_alerts_seen.add(key)
                    self.add_event(numara, "stream_ip_mismatch", CRITICAL,
                                   f"Ekran yayını farklı bir IP adresinden geliyor: {pub_ip} (giriş IP'si {st.ip})",
                                   {"stream_ip": pub_ip, "login_ip": st.ip})
        if changed:
            self.changed(persist=False)

    def mediamtx_down(self) -> None:
        if self.mediamtx_ok or not self.mediamtx_checked:
            self.mediamtx_ok = False
            self.mediamtx_checked = True
            self.changed(persist=False)

    # ---------------------------------------------------------------- snapshot

    def _status(self, st: Student) -> str:
        if st.submissions and not st.file_present and (st.submitted or self.state == ENDED):
            return "nofile"  # submitted, but the file is no longer in the folder
        if self.state == ENDED:
            return "done" if st.submissions else "nosubmit"
        if st.submitted:
            return "done"
        if not st.connected:
            return "lost"
        if st.warn_count > 0:
            return "warn"
        return "ok"

    def snapshot(self, lan_ips: list[str] | None = None) -> dict[str, Any]:
        now_mono = time.monotonic()
        students = []
        summary = {"total": 0, "connected": 0, "warned": 0, "lost": 0, "submitted": 0}
        for st in sorted(self.students.values(), key=lambda s: natural_key(s.numara)):
            status = self._status(st)
            summary["total"] += 1
            if status == "done":
                summary["submitted"] += 1
            elif status in ("lost", "nosubmit", "nofile"):
                summary["lost"] += 1
            else:
                summary["connected"] += 1
            if st.warn_count > 0:
                summary["warned"] += 1
            last = st.submissions[-1] if st.submissions else None
            students.append({
                "numara": st.numara,
                "ad": st.ad,
                "soyad": st.soyad,
                "status": status,
                "lost_reason": st.lost_reason,
                "roster": st.roster,
                "ip": st.ip,
                "hostname": st.hostname,
                "mac": st.mac,
                "agent_version": st.agent_version,
                "login_ts": st.login_ts,
                "login_count": st.login_count,
                "last_seen_s": int(now_mono - st.last_hb_mono),
                "fg_process": st.fg_process,
                "fg_title": st.fg_title,
                "monitors": st.monitors,
                "ffmpeg_alive": st.ffmpeg_alive,
                "exam_state_seen": st.exam_state_seen,
                "stream_ready": st.stream_ready,
                "warn_count": st.warn_count,
                "ev_count": st.ev_count,
                "ack_id": st.ack_id,
                "submission": asdict(last) if last else None,
                "submission_count": len(st.submissions),
            })
        missing = [
            asdict(entry)
            for entry in sorted(self.roster.values(), key=lambda e: natural_key(e.numara))
            if entry.numara not in self.students
        ]
        return {
            "server_time": time.time(),
            "class": {"sinif_adi": self.cfg.sinif_adi, "ogretmen_adi": self.cfg.ogretmen_adi},
            "exam": {
                "state": self.state,
                "exam_id": self.exam_id,
                "started_at": self.started_at,
                "ended_at": self.ended_at,
                "duration_min": self.duration_min,
                "ends_at": self.ends_at,
                "record": self.record_enabled,
                "scheduled": self.scheduled,
                "file": self.exam_file,
                "folder": str(self.exam_dir) if self.exam_dir else "",
            },
            "roster": {"name": self.roster_name, "count": len(self.roster), "missing": missing},
            "health": {
                "mediamtx_ok": self.mediamtx_ok or not self.mediamtx_checked,
                "discovery_error": self.discovery_error,
                "config_error": self.config_error,
                "folder_error": self.folder_error,
                "recording": bool(self.recording_applied),
                "panel_clients": self.panel_clients,
                "lan_ips": lan_ips or [],
                "port": self.cfg.port,
            },
            "summary": summary,
            "students": students,
            "alerts": [e.to_json() for e in reversed(self.alerts)],
            "general_ack_id": self.general_ack_id,
            "webrtc_base": self.cfg.mediamtx_webrtc,
            "paths": {
                "submissions": str(self.dir_submissions) if self.exam_dir else "",
                "recordings": str(self.dir_recordings) if self.exam_dir else "",
                "alerts": str(self.dir_alerts) if self.exam_dir else "",
            },
            "retention_note": self.cfg.retention_note,
        }
