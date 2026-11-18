"""Shared fixtures: a server instance that writes only into a temporary folder."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from sinav.app import create_app  # noqa: E402
from sinav.config import load_config  # noqa: E402

PANEL = {"X-Panel": "1"}
EXAM_BYTES = b"PKA-SINAV-DOSYASI" * 50


def write_config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
sinif_adi: "B-102"
ogretmen_adi: "Ayşe Öğretmen"
sunucu:
  port: 8000
  kesif_portu: {40000 + os.getpid() % 20000}
yayin:
  kullanici: "sinavajan"
  sifre: "test-sifre"
mediamtx:
  api: "http://127.0.0.1:9"      # nothing listens here: MediaMTX counts as "down"
klasorler:
  teslimler: teslim
  kayitlar: kayit
  veri: veri
  dagitim: dagitim
{extra}
""",
        encoding="utf-8",
    )
    return path


class Env:
    """A running app with one panel client (localhost) and a factory for student clients."""

    def __init__(self, tmp_path: Path, extra: str = ""):
        self.tmp_path = tmp_path
        self.cfg = load_config(write_config(tmp_path, extra))
        self.app = create_app(self.cfg)
        self.store = self.app.state.store
        # Only the panel client runs the app lifespan (discovery thread, background tasks).
        self.panel = self._client("127.0.0.1")
        self.panel.__enter__()

    def _client(self, ip: str) -> TestClient:
        return TestClient(self.app, client=(ip, 50000), base_url="http://192.168.1.10:8000")

    def student(self, ip: str = "192.168.1.50") -> TestClient:
        return self._client(ip)

    def close(self) -> None:
        self.panel.__exit__(None, None, None)

    # ---- helpers -------------------------------------------------------

    def login(self, numara="2021001", ad="Ali", soyad="Veli", ip="192.168.1.50",
              mac="AA:BB:CC:00:00:01", hostname="PC-01", expect=200):
        client = self.student(ip)
        response = client.post("/api/login", json={
            "numara": numara, "ad": ad, "soyad": soyad, "hostname": hostname, "mac": mac,
            "agent_version": "test",
        })
        assert response.status_code == expect, response.text
        if expect == 200:
            client.headers["Authorization"] = f"Bearer {response.json()['token']}"
        return client, response.json()

    def upload_exam(self, data: bytes = EXAM_BYTES, name: str = "sinav1.pka"):
        return self.panel.post("/panel/api/exam-file", headers=PANEL,
                               files={"file": (name, data, "application/octet-stream")})

    def start(self):
        """Upload the exam file and share it (sharing the file starts the exam)."""
        assert self.upload_exam().status_code == 200
        response = self.panel.post("/panel/api/start", headers=PANEL)
        assert response.status_code == 200, response.text

    def submit(self, client: TestClient, data: bytes, auto: bool = False, name: str = "sinav.pka"):
        return client.post("/api/submit", data={"auto": "true" if auto else "false"},
                           files={"file": (name, data, "application/octet-stream")})

    def alerts(self, kind: str | None = None) -> list[dict]:
        events = [e.to_json() for e in self.store.events if e.alert]
        return [e for e in events if kind is None or e["type"] == kind]

    def snapshot_student(self, numara: str) -> dict:
        return next(s for s in self.store.snapshot()["students"] if s["numara"] == numara)


@pytest.fixture
def env(tmp_path: Path):
    environment = Env(tmp_path)
    try:
        yield environment
    finally:
        environment.close()
