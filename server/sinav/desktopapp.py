"""What the installed application does around the server.

The desktop shortcut starts ``run.py --app`` without a console window. In that mode:

* only one copy runs: a second start just shows the panel window of the first again;
* MediaMTX is started (hidden) and stopped together with the server;
* everything that is written lives under %LOCALAPPDATA%\\SinavIzleme (the program folder under
  "Program Files" is read-only for an ordinary user);
* what would be printed goes to sistem.log, and a problem that stops the start is shown in a
  message box.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_TITLE = "Sınav İzleme Sistemi"
APP_FOLDER = "SinavIzleme"
LOG_NAME = "sistem.log"
MAX_LOG_BYTES = 2 * 1024 * 1024

# No console window for helper programs (the application itself has none either).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never through a proxy


def home_dir() -> Path:
    """The folder the application writes to: settings made in the panel, logs, exam state."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME") or str(Path.home())
    return Path(base) / APP_FOLDER


def redirect_output(home: Path) -> Path:
    """Send everything the program prints to sistem.log (a windowless program has no console)."""
    log = home / LOG_NAME
    try:
        if log.stat().st_size > MAX_LOG_BYTES:
            log.replace(home / "sistem.eski.log")
    except OSError:
        pass
    stream = open(log, "a", encoding="utf-8", errors="replace", buffering=1)  # noqa: SIM115
    stream.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} başlatıldı ====\n")
    sys.stdout = stream
    sys.stderr = stream
    return log


def show_error(text: str) -> None:
    """Tell the person at the computer why the system could not start."""
    print(f"HATA: {text}")
    if os.name == "nt":
        try:
            import ctypes

            # MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
            ctypes.windll.user32.MessageBoxW(None, text, APP_TITLE, 0x10 | 0x10000 | 0x40000)
        except (OSError, AttributeError):
            pass


MUTEX_NAME = "Local\\SinavIzleme.TekKopya"
_instance_lock = None  # kept for the life of the process


def claim_single_instance() -> bool:
    """True for the first copy of the application; False when another one is starting or
    running (for the same user)."""
    global _instance_lock
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        _instance_lock = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except (OSError, AttributeError):
        return True


def instance_running() -> bool:
    """True while a copy of the application (started with --app) is alive in this session."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenMutexW(0x00100000, False, MUTEX_NAME)  # SYNCHRONIZE
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    except (OSError, AttributeError):
        return False


def probe(port: int) -> str:
    """Who has the server's port on this computer: "free", "ours" or "other"."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            pass
    except OSError:
        return "free"
    try:
        with _OPENER.open(f"http://127.0.0.1:{port}/api/info", timeout=3) as response:
            info = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return "other"
    return "ours" if isinstance(info, dict) and "instance_id" in info and "exam_state" in info else "other"


def show_running_panel(port: int) -> bool:
    """Ask the copy that is already running to show its panel window again."""
    request = urllib.request.Request(f"http://127.0.0.1:{port}/panel/api/open-window", data=b"{}",
                                     headers={"X-Panel": "1", "Content-Type": "application/json"},
                                     method="POST")
    try:
        with _OPENER.open(request, timeout=10):
            return True
    except (OSError, urllib.error.URLError):
        return False


def stop_running(port: int, seconds: float = 20.0) -> bool:
    """Close the copy that is running on this computer (used before an update or removal of
    the program). Returns True when nothing of ours is running any more."""
    if probe(port) != "ours":
        return True
    request = urllib.request.Request(f"http://127.0.0.1:{port}/panel/api/shutdown", data=b"{}",
                                     headers={"X-Panel": "1", "Content-Type": "application/json"},
                                     method="POST")
    try:
        with _OPENER.open(request, timeout=10):
            pass
    except (OSError, urllib.error.URLError):
        pass
    # Gone means: the port is closed AND the process has left (its files can be replaced).
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if probe(port) == "free" and not instance_running():
            time.sleep(0.5)
            return True
        time.sleep(0.5)
    return False


class MediaServer:
    """MediaMTX as a hidden helper of the server: started with it, restarted if it dies,
    stopped with it."""

    RESTART_DELAY_S = 2.0

    def __init__(self, executable: Path, config: Path, workdir: Path):
        self.executable = executable
        self.config = config
        self.workdir = workdir
        self._process: subprocess.Popen[bytes] | None = None
        self._stopping = threading.Event()
        self._watcher: threading.Thread | None = None

    def start(self) -> None:
        """Raises OSError when MediaMTX cannot be started."""
        self._kill_leftovers()
        self._spawn()
        self._watcher = threading.Thread(target=self._watch, name="mediamtx", daemon=True)
        self._watcher.start()

    def _spawn(self) -> None:
        self._process = subprocess.Popen(  # noqa: S603 - our own helper, fixed arguments
            [str(self.executable), str(self.config)], cwd=str(self.workdir),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW)
        print(f"MediaMTX başlatıldı (pid {self._process.pid})")

    def _watch(self) -> None:
        while not self._stopping.wait(1.0):
            process = self._process
            if process is None or process.poll() is None:
                continue
            print(f"MediaMTX kapandı (kod {process.returncode}); yeniden başlatılıyor")
            if self._stopping.wait(self.RESTART_DELAY_S):
                return
            try:
                self._spawn()
            except OSError as exc:
                print(f"MediaMTX yeniden başlatılamadı: {exc}")

    def _kill_leftovers(self) -> None:
        """A copy left behind by a start that was cut short would keep the ports busy."""
        # By name, and only for MediaMTX itself: never for whatever else was passed in.
        if os.name != "nt" or self.executable.name.lower() != "mediamtx.exe":
            return
        try:
            subprocess.run(["taskkill", "/im", self.executable.name, "/f"], check=False,  # noqa: S603, S607
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass

    def stop(self) -> None:
        self._stopping.set()
        process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        print("MediaMTX durduruldu")
