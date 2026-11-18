"""End-to-end behaviour of the server through its HTTP API (no MediaMTX, no real agents)."""

from __future__ import annotations

import csv
import hashlib
import io
import time

from conftest import EXAM_BYTES, PANEL, Env
from openpyxl import Workbook

from sinav.store import ENDED, RUNNING, WAITING, Store


def roster_xlsx(rows):
    book = Workbook()
    book.active.append(["numara", "ad", "soyad"])
    for row in rows:
        book.active.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def upload_roster(env: Env, rows):
    return env.panel.post("/panel/api/roster", headers=PANEL,
                          files={"file": ("liste.xlsx", roster_xlsx(rows), "application/octet-stream")})


# ------------------------------------------------------------------ access


def test_info_is_public_and_panel_is_local_only(env: Env):
    student = env.student()
    info = student.get("/api/info").json()
    assert info["sinif_adi"] == "B-102" and info["ogretmen_adi"] == "Ayşe Öğretmen"

    for path in ("/panel", "/panel/static/panel.js", "/panel/api/stream", "/panel/api/export.csv",
                 "/panel/api/events", "/panel/api/state"):
        assert student.get(path).status_code == 403, path
    assert student.post("/panel/api/end", headers=PANEL).status_code == 403
    assert env.panel.get("/panel").status_code == 200
    assert env.panel.get("/panel/api/state").json()["class"]["sinif_adi"] == "B-102"
    assert "text/javascript" in env.panel.get("/panel/static/panel.js").headers["content-type"]
    # Cross-site form posts (no custom header) are refused even from localhost.
    assert env.panel.post("/panel/api/end").status_code == 403
    # No path tricks through the static route.
    assert env.panel.get("/panel/static/..%2Fconfig.yaml").status_code == 404


def test_root_page_for_students_and_redirect_for_teacher(env: Env):
    page = env.student().get("/")
    assert page.status_code == 200 and "B-102" in page.text
    assert env.panel.get("/", follow_redirects=False).status_code in (302, 307)


def test_api_requires_token(env: Env):
    student = env.student()
    assert student.post("/api/heartbeat", json={}).status_code == 401
    assert student.post("/api/heartbeat", json={}, headers={"Authorization": "Bearer x"}).status_code == 401
    assert student.get("/api/exam-file").status_code == 401


# ------------------------------------------------------------------- login


def test_login_returns_everything_the_agent_needs(env: Env):
    _, body = env.login(numara="2021001")
    assert body["exam_state"] == WAITING
    assert body["stream"]["url"] == "rtsp://192.168.1.10:8554/s/2021001"
    assert body["stream"]["user"] == "sinavajan" and body["stream"]["pass"]
    assert any("Cisco Packet Tracer" in p for p in body["allowlist"]["patterns"])
    assert "notepad.exe" in body["allowlist"]["windows_kill"]
    assert body["allowlist"]["version"] == body["allowlist_version"]
    assert body["settings"]["foreground_tolerance_s"] == 5
    assert body["settings"]["kill_countdown_s"] == 10

    st = env.snapshot_student("2021001")
    assert (st["ip"], st["hostname"], st["mac"]) == ("192.168.1.50", "PC-01", "AA:BB:CC:00:00:01")
    assert st["status"] == "ok"


def test_login_validation(env: Env):
    client = env.student()
    bad = [
        {"numara": "", "ad": "A", "soyad": "B"},
        {"numara": "12 34", "ad": "A", "soyad": "B"},
        {"numara": "../x", "ad": "A", "soyad": "B"},
        {"numara": "1", "ad": "", "soyad": "B"},
    ]
    for body in bad:
        response = client.post("/api/login", json=body)
        assert response.status_code == 422 and response.json()["error"], body
    assert client.post("/api/login", content=b"not json").status_code == 400


def test_second_active_session_is_rejected_with_alert(env: Env):
    env.login(numara="2021001", ip="192.168.1.50", mac="AA:BB:CC:00:00:01")
    _, body = env.login(numara="2021001", ip="192.168.1.51", mac="AA:BB:CC:00:00:02", hostname="PC-02",
                        expect=409)
    assert "başka bir bilgisayarda" in body["error"]
    alert = env.alerts("duplicate_login")
    assert len(alert) == 1 and "192.168.1.51" in alert[0]["message"]


def test_relogin_from_same_machine_replaces_the_session(env: Env):
    first, _ = env.login(numara="2021001")
    second, _ = env.login(numara="2021001")
    assert first.post("/api/heartbeat", json={}).status_code == 401  # old session dropped
    assert second.post("/api/heartbeat", json={}).status_code == 200
    assert any(e.type == "relogin" and "Yeniden bağlandı" in e.message for e in env.store.events)
    assert not env.alerts("duplicate_login")


def test_stale_session_can_be_taken_over_from_another_machine(env: Env):
    env.login(numara="2021001", mac="AA:BB:CC:00:00:01")
    env.store.students["2021001"].last_hb_mono -= 60  # no heartbeat for a minute
    env.login(numara="2021001", ip="192.168.1.77", mac="AA:BB:CC:00:00:09", hostname="PC-09")
    assert env.alerts("machine_change")


def test_same_mac_different_number_raises_red_alert(env: Env):
    env.login(numara="2021001", mac="AA:BB:CC:00:00:01")
    env.store.students["2021001"].last_hb_mono -= 60
    env.login(numara="2021002", ad="Can", soyad="Er", mac="aa-bb-cc-00-00-01")
    alerts = env.alerts("mac_reuse")
    assert len(alerts) == 1
    assert alerts[0]["numara"] == "2021002" and alerts[0]["severity"] == "critical"
    assert "Bu bilgisayardan daha önce 2021001 giriş yapmıştı" in alerts[0]["message"]
    # Logging in again with the same number does not repeat the alert.
    env.login(numara="2021002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:01")
    assert len(env.alerts("mac_reuse")) == 1


# ------------------------------------------------------------------ roster


def test_roster_rules(env: Env):
    # No list loaded: everybody is accepted without warnings.
    env.login(numara="1", ad="X", soyad="Y", mac="AA:BB:CC:00:00:01")
    assert not env.alerts()

    assert upload_roster(env, [[2021001, "Çağrı", "Işık"], [2021002, "Ayşe", "Yılmaz"], [2021003, "Can", "Er"]]).json() == {"count": 3}
    # The already logged-in "1" is re-checked.
    assert env.alerts("not_in_roster")[0]["numara"] == "1"

    # Matching name: case and Turkish letters do not matter; the roster spelling is shown.
    env.login(numara="2021001", ad="CAGRI", soyad="isik", mac="AA:BB:CC:00:00:02", ip="192.168.1.52")
    st = env.snapshot_student("2021001")
    assert (st["ad"], st["soyad"], st["roster"], st["status"]) == ("Çağrı", "Işık", "ok", "ok")

    # Wrong name: accepted, yellow warning.
    env.login(numara="2021002", ad="Fatma", soyad="Yılmaz", mac="AA:BB:CC:00:00:03", ip="192.168.1.53")
    st = env.snapshot_student("2021002")
    assert st["roster"] == "name_mismatch" and st["status"] == "warn"
    assert "listede: Ayşe Yılmaz, girişte: Fatma Yılmaz" in env.alerts("name_mismatch")[0]["message"]

    # Unknown number: accepted with a "not in list" warning.
    env.login(numara="999", ad="Yok", soyad="Kişi", mac="AA:BB:CC:00:00:04", ip="192.168.1.54")
    assert env.snapshot_student("999")["roster"] == "not_in_list"

    missing = env.store.snapshot()["roster"]["missing"]
    assert [m["numara"] for m in missing] == ["2021003"]

    bad = env.panel.post("/panel/api/roster", headers=PANEL, files={"file": ("liste.txt", b"x", "text/plain")})
    assert bad.status_code == 400 and bad.json()["error"]


# -------------------------------------------------------------- state machine


def test_exam_state_machine_and_exam_file_access(env: Env):
    client, _ = env.login()
    assert client.get("/api/exam-file").status_code == 409  # WAITING
    assert env.panel.post("/panel/api/start", headers=PANEL, json={}).status_code == 409  # no file yet
    assert env.panel.post("/panel/api/end", headers=PANEL).status_code == 409

    assert env.upload_exam(b"x", "sinav.txt").status_code == 400
    assert env.upload_exam(b"", "sinav.pka").status_code == 400
    env.start(duration=40)
    assert env.store.state == RUNNING

    hb = client.post("/api/heartbeat", json={"fg_process": "PacketTracer.exe", "monitors": 1,
                                             "ffmpeg_alive": True, "exam_state_seen": "WAITING"}).json()
    assert hb["exam_state"] == RUNNING and hb["exam_id"]
    assert abs(hb["ends_at"] - hb["started_at"] - 40 * 60) < 1
    assert client.get("/api/exam-file").content == EXAM_BYTES

    assert env.panel.post("/panel/api/start", headers=PANEL, json={}).status_code == 409
    assert env.upload_exam().status_code == 409  # not while running
    assert env.panel.post("/panel/api/reset", headers=PANEL).status_code == 409

    assert env.panel.post("/panel/api/end", headers=PANEL).status_code == 200
    assert client.post("/api/heartbeat", json={}).json()["exam_state"] == ENDED
    assert client.get("/api/exam-file").status_code == 409


# ---------------------------------------------------------------- submission


def test_submission_naming_versions_index_and_checks(env: Env):
    a, _ = env.login(numara="2021001", ad="Ahmet Şahin", soyad="Çakır", mac="AA:BB:CC:00:00:01")
    b, _ = env.login(numara="2021002", ad="Işıl", soyad="Öztürk", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    c, _ = env.login(numara="2021003", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:03", ip="192.168.1.52")

    assert env.submit(a, b"work").status_code == 409  # exam not started
    env.start()

    assert env.submit(a, b"work", name="odev.zip").status_code == 400
    assert env.submit(a, b"").status_code == 400

    work_a = b"cozum A"
    first = env.submit(a, work_a).json()
    assert first == {"sha256": hashlib.sha256(work_a).hexdigest(), "filename": "2021001_AhmetSahinCakir.pka",
                     "version": 1, "size": len(work_a)}
    folder = env.cfg.dir_submissions
    assert (folder / "2021001_AhmetSahinCakir.pka").read_bytes() == work_a
    assert env.snapshot_student("2021001")["status"] == "done"

    # Second submission keeps the first file.
    second = env.submit(a, b"cozum A v2").json()
    assert second["filename"] == "2021001_AhmetSahinCakir_v2.pka" and second["version"] == 2
    assert (folder / "2021001_AhmetSahinCakir.pka").read_bytes() == work_a
    assert env.snapshot_student("2021001")["submission"]["filename"] == "2021001_AhmetSahinCakir_v2.pka"

    # Same bytes as another student's file: red alert on both.
    assert env.submit(b, work_a).json()["filename"] == "2021002_IsilOzturk.pka"
    twins = env.alerts("duplicate_hash")
    assert {t["numara"] for t in twins} == {"2021001", "2021002"}
    assert all(t["severity"] == "critical" for t in twins)

    # Identical to the exam file: warning, but not reported as a copy.
    assert env.submit(c, EXAM_BYTES, auto=True).status_code == 200
    unchanged = env.alerts("unchanged_submission")
    assert [u["numara"] for u in unchanged] == ["2021003"]
    assert len(env.alerts("duplicate_hash")) == 2

    rows = list(csv.reader(io.StringIO((folder / "index.csv").read_text(encoding="utf-8-sig")), delimiter=";"))
    assert rows[0][:6] == ["zaman", "numara", "ad", "soyad", "dosya", "sha256"]
    assert [r[4] for r in rows[1:]] == ["2021001_AhmetSahinCakir.pka", "2021001_AhmetSahinCakir_v2.pka",
                                         "2021002_IsilOzturk.pka", "2021003_CanEr.pka"]
    assert rows[4][7] == "evet" and rows[1][7] == "hayır"  # otomatik
    assert rows[1][5] == hashlib.sha256(work_a).hexdigest()


def test_upload_size_limit(env: Env, monkeypatch):
    client, _ = env.login()
    env.start()
    import sinav.store as store_module
    monkeypatch.setattr(store_module, "MAX_UPLOAD_BYTES", 1000)
    response = env.submit(client, b"x" * 1001)
    assert response.status_code == 413 and "50 MB" in response.json()["error"]
    assert not list(env.cfg.dir_submissions.glob("*.pka"))


def test_auto_submit_after_end_and_final_status(env: Env):
    a, _ = env.login(numara="2021001", mac="AA:BB:CC:00:00:01")
    env.login(numara="2021002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    env.start()
    env.panel.post("/panel/api/end", headers=PANEL)
    result = env.submit(a, b"son kayit", auto=True)
    assert result.status_code == 200
    assert any(e.type == "auto_submit" for e in env.store.events)
    assert env.snapshot_student("2021001")["status"] == "done"
    assert env.snapshot_student("2021002")["status"] == "nosubmit"
    summary = env.store.snapshot()["summary"]
    assert (summary["submitted"], summary["lost"]) == (1, 1)


# ------------------------------------------------------ events and connectivity


def test_agent_events_alerts_and_ack(env: Env):
    client, _ = env.login()
    env.start()

    def event(kind, **details):
        return client.post("/api/event", json={"type": kind, "details": details, "ts": time.time()})

    assert event("process_killed", name="chrome.exe", path=r"C:\x\chrome.exe", title="<b>Sekme</b>").status_code == 200
    assert event("foreign_foreground", name="explorer.exe", seconds=6).status_code == 200
    assert event("foreground_change", name="PacketTracer.exe", title="Router0").status_code == 200
    assert event("monitor_change", count=2, previous=1).status_code == 200
    assert event("ffmpeg_restart", reason="ffmpeg kapandı").status_code == 200
    assert client.post("/api/event", json={"details": {}}).status_code == 422

    messages = {e["type"]: e["message"] for e in env.alerts()}
    assert messages["process_killed"].startswith("chrome.exe kapatıldı")
    assert messages["foreign_foreground"].startswith("Packet Tracer dışında bir pencere önde: explorer.exe")
    assert messages["monitor_change"] == "Monitör sayısı: 2 (önceki: 1)"
    # Foreground switches and ffmpeg restarts go to the log only, not to the alert feed.
    assert "foreground_change" not in messages and "ffmpeg_restart" not in messages
    assert any(e.type == "foreground_change" for e in env.store.events)

    st = env.snapshot_student("2021001")
    assert st["status"] == "warn" and st["warn_count"] == 3

    history = env.panel.get("/panel/api/events", params={"numara": "2021001"}).json()["events"]
    assert len(history) >= 6

    assert env.panel.post("/panel/api/ack", headers=PANEL, json={"numara": "2021001"}).status_code == 200
    assert env.snapshot_student("2021001")["status"] == "ok"

    export = env.panel.get("/panel/api/export.csv")
    assert export.status_code == 200 and export.content.startswith(b"\xef\xbb\xbf")
    text = export.content.decode("utf-8-sig")
    assert "chrome.exe kapatıldı" in text and "zaman;numara;ad_soyad" in text


def test_box_turns_red_without_heartbeat_and_green_again(env: Env):
    client, _ = env.login()
    env.store.tick()
    assert env.snapshot_student("2021001")["status"] == "ok"

    env.store.students["2021001"].last_hb_mono -= env.cfg.disconnect_s + 0.1
    env.store.tick()
    st = env.snapshot_student("2021001")
    assert st["status"] == "lost" and "sinyal" in st["lost_reason"]
    lost = env.alerts("disconnected")
    assert len(lost) == 1 and lost[0]["severity"] == "critical"
    env.store.tick()
    assert len(env.alerts("disconnected")) == 1  # not repeated

    assert client.post("/api/heartbeat", json={}).status_code == 200
    env.store.tick()
    st = env.snapshot_student("2021001")
    assert st["status"] == "ok" and st["warn_count"] == 0  # back to green, no sticky warning
    assert env.alerts("connection_restored")


def test_box_turns_red_when_stream_is_missing(env: Env):
    env.login()
    store = env.store
    store.apply_streams(set(), {})  # MediaMTX reachable, but no stream for this student
    store.tick()
    assert env.snapshot_student("2021001")["status"] == "ok"  # grace period after login
    store.students["2021001"].stream_changed_mono -= env.cfg.disconnect_s + 0.1
    store.tick()
    st = env.snapshot_student("2021001")
    assert st["status"] == "lost" and st["lost_reason"] == "ekran yayını yok"

    store.apply_streams({"s/2021001"}, {"s/2021001": "192.168.1.50"})
    store.tick()
    assert env.snapshot_student("2021001")["status"] == "ok"

    # A stream from another address than the login is flagged once.
    store.apply_streams({"s/2021001"}, {"s/2021001": "192.168.1.99"})
    store.apply_streams({"s/2021001"}, {"s/2021001": "192.168.1.99"})
    assert len(env.alerts("stream_ip_mismatch")) == 1
    store.apply_streams({"s/777"}, {"s/777": "192.168.1.98"})
    assert len(env.alerts("stream_without_login")) == 1


def test_agent_exit_marks_student_red(env: Env):
    client, _ = env.login()
    env.start()
    client.post("/api/event", json={"type": "agent_exit", "details": {"phase": "Running"}})
    env.store.tick()
    st = env.snapshot_student("2021001")
    assert st["status"] == "lost" and st["lost_reason"] == "ajan kapatıldı"
    assert env.alerts("agent_exit") and not env.alerts("disconnected")


# ------------------------------------------------------- persistence and reset


def test_state_survives_a_server_restart(env: Env):
    client, body = env.login(numara="2021001", ad="Ahmet", soyad="Çakır")
    env.start(duration=30)
    env.submit(client, b"cozum")
    env.store.save()

    restored = Store(env.cfg)
    restored.load()
    assert restored.state == RUNNING and restored.exam_id == env.store.exam_id
    assert restored.auth(body["token"]).numara == "2021001"
    st = restored.students["2021001"]
    assert st.submissions[0].filename == "2021001_AhmetCakir.pka" and st.submitted
    assert restored.exam_file["sha256"] == hashlib.sha256(EXAM_BYTES).hexdigest()
    assert len(restored.events) == len(env.store.events)
    assert restored.next_event_id == env.store.next_event_id


def test_reset_archives_instead_of_deleting(env: Env):
    upload_roster(env, [[2021001, "Ali", "Veli"]])
    client, _ = env.login()
    env.start()
    env.submit(client, b"cozum")
    env.panel.post("/panel/api/end", headers=PANEL)

    response = env.panel.post("/panel/api/reset", headers=PANEL)
    assert response.status_code == 200
    archive = response.json()["archive"]
    assert archive

    from pathlib import Path
    archived = Path(archive)
    assert (archived / "submissions" / "2021001_AliVeli.pka").read_bytes() == b"cozum"
    assert (archived / "submissions" / "index.csv").exists()
    assert (archived / "events.jsonl").exists() and (archived / "sinav.pka").exists()
    assert not list(env.cfg.dir_submissions.iterdir())

    snapshot = env.store.snapshot()
    assert snapshot["exam"]["state"] == WAITING and snapshot["exam"]["file"] is None
    assert snapshot["students"] == [] and snapshot["roster"]["count"] == 1  # roster is kept
    assert client.post("/api/heartbeat", json={}).status_code == 401  # old sessions are gone
