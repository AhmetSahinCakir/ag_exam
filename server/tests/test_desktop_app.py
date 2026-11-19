"""The parts of the installed application that sit around the server (run.py --app)."""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sinav import desktopapp  # noqa: E402


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class FakeServer:
    """Answers like the exam server (or like some other program) on a local port."""

    def __init__(self, ours: bool):
        calls = self.calls = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, payload: dict) -> None:
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                calls.append(("GET", self.path))
                self._send({"instance_id": "x", "exam_state": "WAITING"} if ours else {"hello": "world"})

            def do_POST(self):  # noqa: N802
                calls.append(("POST", self.path, self.headers.get("X-Panel")))
                self._send({"ok": True})
                if self.path == "/panel/api/shutdown":
                    threading.Thread(target=owner.close, daemon=True).start()

            def log_message(self, *args):  # keep the test output clean
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def test_probe_tells_a_free_port_our_server_and_another_program_apart():
    assert desktopapp.probe(free_port()) == "free"
    ours, other = FakeServer(ours=True), FakeServer(ours=False)
    try:
        assert desktopapp.probe(ours.port) == "ours"
        assert desktopapp.probe(other.port) == "other"
    finally:
        ours.close()
        other.close()


def test_a_second_start_shows_the_panel_of_the_running_copy():
    server = FakeServer(ours=True)
    try:
        assert desktopapp.show_running_panel(server.port) is True
        assert ("POST", "/panel/api/open-window", "1") in server.calls
    finally:
        server.close()
    assert desktopapp.show_running_panel(free_port()) is False


def test_stop_closes_the_running_copy_and_waits_until_it_is_gone():
    assert desktopapp.stop_running(free_port(), seconds=2) is True  # nothing runs: nothing to do
    server = FakeServer(ours=True)
    assert desktopapp.stop_running(server.port, seconds=10) is True
    assert ("POST", "/panel/api/shutdown", "1") in server.calls
    assert desktopapp.probe(server.port) == "free"


def test_stop_leaves_other_programs_alone():
    other = FakeServer(ours=False)
    try:
        assert desktopapp.stop_running(other.port, seconds=2) is True
        assert not [call for call in other.calls if call[0] == "POST"]
    finally:
        other.close()


def test_application_files_live_in_the_users_own_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert desktopapp.home_dir() == tmp_path / "SinavIzleme"


def test_output_goes_to_a_log_file_that_does_not_grow_forever(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    log = tmp_path / "sistem.log"
    log.write_bytes(b"x" * (desktopapp.MAX_LOG_BYTES + 1))
    assert desktopapp.redirect_output(tmp_path) == log
    print("merhaba, Türkçe: ğüşıöç")
    sys.stdout.close()
    assert "merhaba, Türkçe: ğüşıöç" in log.read_text(encoding="utf-8")
    assert log.stat().st_size < 1000                         # the old log was moved aside
    assert (tmp_path / "sistem.eski.log").stat().st_size > desktopapp.MAX_LOG_BYTES


def test_the_media_server_is_restarted_when_it_dies_and_stopped_with_the_system(tmp_path, monkeypatch):
    helper = tmp_path / "helper.py"
    helper.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    monkeypatch.setattr(desktopapp.MediaServer, "RESTART_DELAY_S", 0.2)
    monkeypatch.setattr(desktopapp.MediaServer, "_kill_leftovers", lambda self: None)
    media = desktopapp.MediaServer(Path(sys.executable), helper, tmp_path)
    media.start()
    try:
        first = media._process
        assert first is not None and first.poll() is None
        first.kill()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (media._process is first or media._process.poll() is not None):
            time.sleep(0.1)
        second = media._process
        assert second is not first and second.poll() is None, "MediaMTX was not started again"
    finally:
        media.stop()
    assert media._process.poll() is not None, "MediaMTX still runs after the system was stopped"
    time.sleep(1.5)
    assert media._process.poll() is not None, "MediaMTX was started again after stop"


def test_a_missing_media_server_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(desktopapp.MediaServer, "_kill_leftovers", lambda self: None)
    media = desktopapp.MediaServer(tmp_path / "yok" / "mediamtx.exe", tmp_path / "mediamtx.yml", tmp_path)
    with pytest.raises(OSError):
        media.start()
    media.stop()
