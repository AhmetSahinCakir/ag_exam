"""End-to-end behaviour of the server through its HTTP API (no MediaMTX, no real agents)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time

import pytest
from conftest import EXAM_BYTES, PANEL, Env
from sinav.config import ConfigError, load_config
from openpyxl import Workbook

from sinav.store import CLOSED, ENDED, RUNNING, WAITING, Store


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
    _, body = env.login(numara="2021000001")
    assert body["exam_state"] == WAITING
    assert body["stream"]["url"] == "rtsp://192.168.1.10:8554/2021000001"
    assert body["stream"]["user"] == "sinavajan" and body["stream"]["pass"]
    assert any("Cisco Packet Tracer" in p for p in body["allowlist"]["patterns"])
    assert "notepad.exe" in body["allowlist"]["windows_kill"]
    assert body["allowlist"]["version"] == body["allowlist_version"]
    assert body["settings"]["foreground_tolerance_s"] == 5
    assert body["settings"]["kill_countdown_s"] == 10

    st = env.snapshot_student("2021000001")
    assert (st["ip"], st["hostname"], st["mac"]) == ("192.168.1.50", "PC-01", "AA:BB:CC:00:00:01")
    assert st["status"] == "ok"


def test_login_validation(env: Env):
    client = env.student()
    bad = [
        {"numara": "", "ad": "A", "soyad": "B"},
        {"numara": "12 34", "ad": "A", "soyad": "B"},
        {"numara": "../x", "ad": "A", "soyad": "B"},
        {"numara": "202100001", "ad": "A", "soyad": "B"},      # 9 digits
        {"numara": "20210000011", "ad": "A", "soyad": "B"},    # 11 digits
        {"numara": "20210000A1", "ad": "A", "soyad": "B"},     # a letter in it
        {"numara": "２０２１００００１１", "ad": "A", "soyad": "B"},  # digits of another script
        {"numara": "2021000001", "ad": "", "soyad": "B"},
    ]
    for body in bad:
        response = client.post("/api/login", json=body)
        assert response.status_code == 422 and response.json()["error"], body
    # The student is told what the number has to look like.
    response = client.post("/api/login", json=bad[3])
    assert response.json()["error"] == "Öğrenci numarası 10 haneli olmalı ve yalnızca rakamlardan oluşmalı."
    assert not env.store.students
    assert client.post("/api/login", content=b"not json").status_code == 400


def test_second_active_session_is_rejected_with_alert(env: Env):
    env.login(numara="2021000001", ip="192.168.1.50", mac="AA:BB:CC:00:00:01")
    _, body = env.login(numara="2021000001", ip="192.168.1.51", mac="AA:BB:CC:00:00:02", hostname="PC-02",
                        expect=409)
    assert "başka bir bilgisayarda" in body["error"]
    alert = env.alerts("duplicate_login")
    assert len(alert) == 1 and "192.168.1.51" in alert[0]["message"]


def test_relogin_from_same_machine_replaces_the_session(env: Env):
    first, _ = env.login(numara="2021000001")
    second, _ = env.login(numara="2021000001")
    assert first.post("/api/heartbeat", json={}).status_code == 401  # old session dropped
    assert second.post("/api/heartbeat", json={}).status_code == 200
    assert any(e.type == "relogin" and "Yeniden bağlandı" in e.message for e in env.store.events)
    assert not env.alerts("duplicate_login")


def test_stale_session_can_be_taken_over_from_another_machine(env: Env):
    env.login(numara="2021000001", mac="AA:BB:CC:00:00:01")
    env.store.students["2021000001"].last_hb_mono -= 60  # no heartbeat for a minute
    env.login(numara="2021000001", ip="192.168.1.77", mac="AA:BB:CC:00:00:09", hostname="PC-09")
    assert env.alerts("machine_change")


def test_same_mac_different_number_raises_red_alert(env: Env):
    env.login(numara="2021000001", mac="AA:BB:CC:00:00:01")
    env.store.students["2021000001"].last_hb_mono -= 60
    env.login(numara="2021000002", ad="Can", soyad="Er", mac="aa-bb-cc-00-00-01")
    alerts = env.alerts("mac_reuse")
    assert len(alerts) == 1
    assert alerts[0]["numara"] == "2021000002" and alerts[0]["severity"] == "critical"
    # ... with the name the earlier student typed, also in the log files.
    assert "Bu bilgisayardan daha önce 2021000001 Ali Veli giriş yapmıştı (MAC AA:BB:CC:00:00:01)" in alerts[0]["message"]
    assert alerts[0]["details"]["other_names"] == ["2021000001 Ali Veli"]
    # Logging in again with the same number does not repeat the alert.
    env.login(numara="2021000002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:01")
    assert len(env.alerts("mac_reuse")) == 1


# ------------------------------------------------------------------ roster


def test_roster_rules(env: Env):
    # No list loaded: everybody is accepted without warnings.
    env.login(numara="2021000777", ad="X", soyad="Y", mac="AA:BB:CC:00:00:01")
    assert not env.alerts()

    assert upload_roster(env, [[2021000001, "Çağrı", "Işık"], [2021000002, "Ayşe", "Yılmaz"], [2021000003, "Can", "Er"]]).json() == {"count": 3}
    # The student who was already logged in is re-checked.
    assert env.alerts("not_in_roster")[0]["numara"] == "2021000777"

    # Matching name: case and Turkish letters do not matter; the roster spelling is shown.
    env.login(numara="2021000001", ad="CAGRI", soyad="isik", mac="AA:BB:CC:00:00:02", ip="192.168.1.52")
    st = env.snapshot_student("2021000001")
    assert (st["ad"], st["soyad"], st["roster"], st["status"]) == ("Çağrı", "Işık", "ok", "ok")

    # Wrong name: accepted, yellow warning.
    env.login(numara="2021000002", ad="Fatma", soyad="Yılmaz", mac="AA:BB:CC:00:00:03", ip="192.168.1.53")
    st = env.snapshot_student("2021000002")
    assert st["roster"] == "name_mismatch" and st["status"] == "warn"
    assert "listede: Ayşe Yılmaz, girişte: Fatma Yılmaz" in env.alerts("name_mismatch")[0]["message"]

    # Unknown number: accepted with a "not in list" warning.
    env.login(numara="2021000999", ad="Yok", soyad="Kişi", mac="AA:BB:CC:00:00:04", ip="192.168.1.54")
    assert env.snapshot_student("2021000999")["roster"] == "not_in_list"

    missing = env.store.snapshot()["roster"]["missing"]
    assert [m["numara"] for m in missing] == ["2021000003"]

    bad = env.panel.post("/panel/api/roster", headers=PANEL, files={"file": ("liste.txt", b"x", "text/plain")})
    assert bad.status_code == 400 and bad.json()["error"]


# -------------------------------------------------------------- state machine


def test_exam_state_machine_and_exam_file_access(env: Env):
    client, _ = env.login()
    assert client.get("/api/exam-file").status_code == 409  # WAITING
    refused = env.panel.post("/panel/api/start", headers=PANEL, json={})
    assert refused.status_code == 409 and "klasörünü seçin" in refused.json()["error"]  # no folder yet
    assert env.choose_folder().status_code == 200
    refused = env.panel.post("/panel/api/start", headers=PANEL, json={})
    assert refused.status_code == 409 and ".pka" in refused.json()["error"]  # no file yet
    assert env.panel.post("/panel/api/end", headers=PANEL).status_code == 409

    assert env.upload_exam(b"x", "sinav.txt").status_code == 400
    assert env.upload_exam(b"", "sinav.pka").status_code == 400
    env.start()
    assert env.store.state == RUNNING

    hb = client.post("/api/heartbeat", json={"fg_process": "PacketTracer.exe", "monitors": 1,
                                             "ffmpeg_alive": True, "exam_state_seen": "WAITING"}).json()
    assert hb["exam_state"] == RUNNING and hb["exam_id"] and hb["started_at"] > 0
    # Started without a time limit: no deadline, the teacher ends the exam.
    assert hb["ends_at"] == 0 and hb["scheduled_at"] == 0
    exam = env.store.snapshot()["exam"]
    assert exam["duration_min"] == 0 and exam["ends_at"] == 0 and exam["record"] is True
    # Once shared, the file can be downloaded.
    assert client.get("/api/exam-file").content == EXAM_BYTES

    assert env.panel.post("/panel/api/start", headers=PANEL, json={}).status_code == 409
    assert env.upload_exam().status_code == 409  # not while running
    assert env.panel.post("/panel/api/reset", headers=PANEL).status_code == 409

    assert env.panel.post("/panel/api/end", headers=PANEL).status_code == 200
    assert client.post("/api/heartbeat", json={}).json()["exam_state"] == ENDED
    assert client.get("/api/exam-file").status_code == 409


# ---------------------------------------------------------------- submission


def test_submission_naming_versions_index_and_checks(env: Env):
    a, _ = env.login(numara="2021000001", ad="Ahmet Şahin", soyad="Çakır", mac="AA:BB:CC:00:00:01")
    b, _ = env.login(numara="2021000002", ad="Işıl", soyad="Öztürk", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    c, _ = env.login(numara="2021000003", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:03", ip="192.168.1.52")

    assert env.submit(a, b"work").status_code == 409  # exam not started
    env.start()

    assert env.submit(a, b"work", name="odev.zip").status_code == 400
    assert env.submit(a, b"").status_code == 400

    work_a = b"cozum A"
    first = env.submit(a, work_a).json()
    assert first == {"sha256": hashlib.sha256(work_a).hexdigest(), "filename": "2021000001_AhmetSahinCakir.pka",
                     "version": 1, "size": len(work_a), "verified": True, "late": False}
    folder = env.submissions
    assert (folder / "2021000001_AhmetSahinCakir.pka").read_bytes() == work_a
    assert env.snapshot_student("2021000001")["status"] == "done"

    # Second submission keeps the first file.
    second = env.submit(a, b"cozum A v2").json()
    assert second["filename"] == "2021000001_AhmetSahinCakir_v2.pka" and second["version"] == 2
    assert (folder / "2021000001_AhmetSahinCakir.pka").read_bytes() == work_a
    assert env.snapshot_student("2021000001")["submission"]["filename"] == "2021000001_AhmetSahinCakir_v2.pka"

    # Same bytes as another student's file: red alert on both.
    assert env.submit(b, work_a).json()["filename"] == "2021000002_IsilOzturk.pka"
    twins = env.alerts("duplicate_hash")
    assert {t["numara"] for t in twins} == {"2021000001", "2021000002"}
    assert all(t["severity"] == "critical" for t in twins)

    # Identical to the exam file: warning, but not reported as a copy.
    assert env.submit(c, EXAM_BYTES).status_code == 200
    unchanged = env.alerts("unchanged_submission")
    assert [u["numara"] for u in unchanged] == ["2021000003"]
    assert len(env.alerts("duplicate_hash")) == 2

    rows = list(csv.reader(io.StringIO((folder / "index.csv").read_text(encoding="utf-8-sig")), delimiter=";"))
    assert rows[0][:6] == ["zaman", "numara", "ad", "soyad", "dosya", "sha256"]
    assert [r[4] for r in rows[1:]] == ["2021000001_AhmetSahinCakir.pka", "2021000001_AhmetSahinCakir_v2.pka",
                                         "2021000002_IsilOzturk.pka", "2021000003_CanEr.pka"]
    assert rows[0][6:] == ["boyut", "gec_teslim", "surum", "ip", "bilgisayar", "mac"]
    assert all(r[7] == "hayır" for r in rows[1:])  # nothing was handed in late
    assert rows[1][5] == hashlib.sha256(work_a).hexdigest()


def test_upload_size_limit(env: Env, monkeypatch):
    client, _ = env.login()
    env.start()
    import sinav.store as store_module
    monkeypatch.setattr(store_module, "MAX_UPLOAD_BYTES", 1000)
    response = env.submit(client, b"x" * 1001)
    assert response.status_code == 413 and "50 MB" in response.json()["error"]
    assert not list(env.submissions.glob("*.pka"))


def test_final_status_after_the_end(env: Env):
    a, _ = env.login(numara="2021000001", mac="AA:BB:CC:00:00:01")
    env.login(numara="2021000002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    env.start()
    assert env.submit(a, b"son kayit").status_code == 200
    env.panel.post("/panel/api/end", headers=PANEL)
    # Nothing is ever handed in automatically: who did not hand in has no file.
    assert not any(e.type == "auto_submit" for e in env.store.events)
    assert [p.name for p in env.submissions.glob("*.pka")] == ["2021000001_AliVeli.pka"]
    assert env.snapshot_student("2021000001")["status"] == "done"
    assert env.snapshot_student("2021000002")["status"] == "nosubmit"
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

    st = env.snapshot_student("2021000001")
    assert st["status"] == "warn" and st["warn_count"] == 3

    history = env.panel.get("/panel/api/events", params={"numara": "2021000001"}).json()["events"]
    assert len(history) >= 6

    assert env.snapshot_student("2021000001")["ack_id"] == 0
    assert env.panel.post("/panel/api/ack", headers=PANEL, json={"numara": "2021000001"}).status_code == 200
    st = env.snapshot_student("2021000001")
    assert st["status"] == "ok" and st["ack_id"] == env.store.events[-1].id  # everything so far is seen
    assert env.store.general_ack_id == 0
    event("process_killed", name="discord.exe")
    newest = env.store.snapshot()["alerts"][0]
    assert newest["id"] > st["ack_id"] and env.snapshot_student("2021000001")["warn_count"] == 1
    assert env.panel.post("/panel/api/ack", headers=PANEL, json={}).status_code == 200  # everything
    assert env.snapshot_student("2021000001")["ack_id"] == newest["id"] == env.store.general_ack_id

    export = env.panel.get("/panel/api/export.csv")
    assert export.status_code == 200 and export.content.startswith(b"\xef\xbb\xbf")
    text = export.content.decode("utf-8-sig")
    assert "chrome.exe kapatıldı" in text and "zaman;numara;ad_soyad" in text


def test_box_turns_red_without_heartbeat_and_green_again(env: Env):
    client, _ = env.login()
    env.store.tick()
    assert env.snapshot_student("2021000001")["status"] == "ok"

    env.store.students["2021000001"].last_hb_mono -= env.cfg.disconnect_s + 0.1
    env.store.tick()
    st = env.snapshot_student("2021000001")
    assert st["status"] == "lost" and "sinyal" in st["lost_reason"]
    lost = env.alerts("disconnected")
    assert len(lost) == 1 and lost[0]["severity"] == "critical"
    env.store.tick()
    assert len(env.alerts("disconnected")) == 1  # not repeated

    assert client.post("/api/heartbeat", json={}).status_code == 200
    env.store.tick()
    st = env.snapshot_student("2021000001")
    assert st["status"] == "ok" and st["warn_count"] == 0  # back to green, no sticky warning
    assert env.alerts("connection_restored")


def test_box_turns_red_when_stream_is_missing(env: Env):
    env.login()
    store = env.store
    store.apply_streams(set(), {})  # MediaMTX reachable, but no stream for this student
    store.tick()
    assert env.snapshot_student("2021000001")["status"] == "ok"  # grace period after login
    store.students["2021000001"].stream_changed_mono -= env.cfg.disconnect_s + 0.1
    store.tick()
    st = env.snapshot_student("2021000001")
    assert st["status"] == "lost" and st["lost_reason"] == "ekran yayını yok"

    store.apply_streams({"2021000001"}, {"2021000001": "192.168.1.50"})
    store.tick()
    assert env.snapshot_student("2021000001")["status"] == "ok"

    # A stream from another address than the login is flagged once.
    store.apply_streams({"2021000001"}, {"2021000001": "192.168.1.99"})
    store.apply_streams({"2021000001"}, {"2021000001": "192.168.1.99"})
    assert len(env.alerts("stream_ip_mismatch")) == 1
    store.apply_streams({"2021000777"}, {"2021000777": "192.168.1.98"})
    assert len(env.alerts("stream_without_login")) == 1


def test_agent_exit_marks_student_red(env: Env):
    client, _ = env.login()
    env.start()
    client.post("/api/event", json={"type": "agent_exit", "details": {"phase": "Running"}})
    env.store.tick()
    st = env.snapshot_student("2021000001")
    assert st["status"] == "lost" and st["lost_reason"] == "ajan kapatıldı"
    assert env.alerts("agent_exit") and not env.alerts("disconnected")


# ------------------------------------------------------- persistence and reset


def test_state_survives_a_server_restart(env: Env):
    client, body = env.login(numara="2021000001", ad="Ahmet", soyad="Çakır")
    env.start()
    env.submit(client, b"cozum")
    env.store.save()

    restored = Store(env.cfg)
    restored.load()
    assert restored.state == RUNNING and restored.exam_id == env.store.exam_id
    assert restored.auth(body["token"]).numara == "2021000001"
    st = restored.students["2021000001"]
    assert st.submissions[0].filename == "2021000001_AhmetCakir.pka" and st.submitted
    assert restored.exam_file["sha256"] == hashlib.sha256(EXAM_BYTES).hexdigest()
    assert len(restored.events) == len(env.store.events)
    assert restored.next_event_id == env.store.next_event_id
    assert restored.exam_dir == env.exam_dir.resolve() and restored.record_path == env.store.record_path


def test_new_exam_keeps_every_file_of_the_finished_one(env: Env):
    upload_roster(env, [[2021000001, "Ali", "Veli"]])
    client, _ = env.login()
    env.start()
    env.submit(client, b"cozum")
    env.panel.post("/panel/api/end", headers=PANEL)

    response = env.panel.post("/panel/api/reset", headers=PANEL)
    assert response.status_code == 200 and response.json() == {"state": WAITING}

    # Nothing in the exam folder is moved or deleted; the event log is written next to it.
    assert (env.submissions / "2021000001_AliVeli.pka").read_bytes() == b"cozum"
    assert (env.submissions / "index.csv").exists()
    log_text = (env.exam_dir / "olay-kaydi.csv").read_text(encoding="utf-8-sig")
    assert "Teslim etti: 2021000001_AliVeli.pka" in log_text and "Sınav bitirildi" in log_text
    assert len(list((env.cfg.dir_data / "arsiv").glob("olaylar_*.jsonl"))) == 1

    snapshot = env.store.snapshot()
    assert snapshot["exam"]["state"] == WAITING and snapshot["exam"]["file"] is None
    assert snapshot["exam"]["folder"] == ""  # the next exam gets its own folder
    # The roster is kept: its student is shown again as "not logged in yet".
    assert env.store.students == {} and snapshot["roster"]["count"] == 1
    assert [(s["numara"], s["status"]) for s in snapshot["students"]] == [("2021000001", "absent")]
    assert client.post("/api/heartbeat", json={}).status_code == 401  # old sessions are gone


# ------------------------------------------------------------- exam folder


def test_exam_folder_gets_two_subfolders_and_sets_the_recording_path(env: Env):
    assert env.store.record_path == ""  # no folder yet
    assert env.choose_folder("goreli/yol").status_code == 422
    assert env.choose_folder("").status_code == 422

    body = env.choose_folder().json()
    assert body["folder"] == str(env.exam_dir.resolve())
    assert (env.exam_dir / "Kayıtlar").is_dir() and (env.exam_dir / "Teslimler").is_dir()
    snapshot = env.store.snapshot()
    assert snapshot["exam"]["folder"] == str(env.exam_dir.resolve())
    assert snapshot["paths"]["recordings"].endswith("Kayıtlar")
    assert snapshot["paths"]["submissions"].endswith("Teslimler")
    assert env.store.record_path == ""  # nothing is recorded before the exam starts

    # It can be changed before the exam, but not once the file is shared.
    other = env.tmp_path / "Başka Klasör"
    assert env.choose_folder(other).status_code == 200 and (other / "Teslimler").is_dir()
    assert env.choose_folder().status_code == 200
    env.upload_exam()
    env.panel.post("/panel/api/start", headers=PANEL)
    assert env.choose_folder(other).status_code == 409
    # Once the exam runs, MediaMTX is told to record every stream into Kayıtlar/<numara>/<time>.
    assert env.store.record_path == str(env.exam_dir.resolve() / "Kayıtlar" / "%path" / "%Y-%m-%d_%H-%M-%S_%z")


def test_folder_window_of_the_operating_system(env: Env, monkeypatch):
    import sinav.app as app_module
    from sinav.folderdialog import DialogUnavailable

    target = env.tmp_path / "Seçilen"
    monkeypatch.setattr(app_module, "pick_folder", lambda initial="": str(target))
    assert env.panel.post("/panel/api/pick-folder", headers=PANEL).json() == {"folder": str(target.resolve())}
    assert (target / "Teslimler").is_dir()

    monkeypatch.setattr(app_module, "pick_folder", lambda initial="": "")
    assert env.panel.post("/panel/api/pick-folder", headers=PANEL).json() == {"folder": "", "cancelled": True}
    assert env.store.exam_dir == target.resolve()  # cancelling keeps the previous choice

    def unavailable(initial=""):
        raise DialogUnavailable()

    monkeypatch.setattr(app_module, "pick_folder", unavailable)
    response = env.panel.post("/panel/api/pick-folder", headers=PANEL)
    assert response.status_code == 501 and "elle yazın" in response.json()["error"]
    assert env.student().post("/panel/api/pick-folder", headers=PANEL).status_code == 403


def test_student_is_done_only_while_the_file_is_in_the_folder(env: Env):
    client, _ = env.login()
    env.start()
    assert client.post("/api/heartbeat", json={}).json()["submitted"] is False
    work = EXAM_BYTES + b"-cozum"
    name = env.submit(client, work).json()["filename"]
    env.store.check_submission_folder()
    assert env.snapshot_student("2021000001")["status"] == "done"
    assert client.post("/api/heartbeat", json={}).json()["submitted"] is True
    assert not env.alerts()

    # The file disappears from the folder: the student is no longer "teslim etti".
    (env.submissions / name).rename(env.tmp_path / "kenarda.pka")
    env.store.check_submission_folder()
    env.store.check_submission_folder()
    assert env.snapshot_student("2021000001")["status"] == "nofile"
    missing = env.alerts("submission_missing")
    assert len(missing) == 1 and missing[0]["severity"] == "critical" and name in missing[0]["message"]
    assert client.post("/api/heartbeat", json={}).json()["submitted"] is False
    assert env.store.snapshot()["summary"]["submitted"] == 0

    (env.tmp_path / "kenarda.pka").rename(env.submissions / name)
    env.store.check_submission_folder()
    assert env.snapshot_student("2021000001")["status"] == "done"


def test_file_put_into_the_folder_by_hand_counts_as_submission(env: Env):
    # A file that was in the folder before the exam is never taken as a submission.
    env.choose_folder()
    (env.submissions / "2021000001_Eski.pka").write_bytes(b"gecen yilin dosyasi")
    client, _ = env.login()
    env.login(numara="2021000002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    env.start()
    env.store.check_submission_folder()
    assert env.snapshot_student("2021000001")["status"] == "ok"

    # The teacher copies a student's file from a USB stick.
    old = time.time() - 10
    by_hand = env.submissions / "2021000002_usbden.pka"
    by_hand.write_bytes(EXAM_BYTES + b"-usb")
    env.store.check_submission_folder()
    assert env.snapshot_student("2021000002")["status"] == "ok"  # just written: may still be copying
    os.utime(by_hand, (old, old))
    env.store.check_submission_folder()
    env.store.check_submission_folder()
    st = env.snapshot_student("2021000002")
    assert st["status"] == "done" and st["submission"]["filename"] == "2021000002_usbden.pka"
    assert st["submission_count"] == 1
    assert any("klasörde bulundu" in e.message for e in env.store.events)
    assert "2021000002_usbden.pka" in (env.submissions / "index.csv").read_text(encoding="utf-8-sig")

    # A file that belongs to nobody is reported once and otherwise left alone.
    stray = env.submissions / "kimin-bu.pka"
    stray.write_bytes(b"x")
    os.utime(stray, (old, old))
    env.store.check_submission_folder()
    env.store.check_submission_folder()
    assert len(env.alerts("unknown_submission_file")) == 1 and stray.exists()
    assert client.post("/api/heartbeat", json={}).json()["submitted"] is False


def test_submitted_file_is_verified(env: Env):
    a, _ = env.login(numara="2021000001", mac="AA:BB:CC:00:00:01")
    b, _ = env.login(numara="2021000002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    c, _ = env.login(numara="2021000003", ad="Ece", soyad="Su", mac="AA:BB:CC:00:00:03", ip="192.168.1.52")
    env.start()

    # The agent sends the hash of the file it read; a damaged upload is refused.
    work = EXAM_BYTES + b"-cozum"
    broken = env.submit(a, work, sha256=hashlib.sha256(b"baska").hexdigest())
    assert broken.status_code == 400 and "bozuldu" in broken.json()["error"]
    assert not list(env.submissions.glob("*.pka")) and env.snapshot_student("2021000001")["status"] == "ok"
    ok = env.submit(a, work, sha256=hashlib.sha256(work).hexdigest().upper(),
                    original_name=r"C:\Users\a\Desktop\Ağ çözümüm.pka")
    assert ok.status_code == 200 and ok.json()["verified"] is True
    assert not env.alerts()
    submitted = next(e for e in env.store.events if e.type == "submit")
    assert submitted.details["original"] == "Ağ çözümüm.pka"  # the name of the file the student picked

    # The exam file itself, exactly as it was downloaded.
    assert env.submit(b, EXAM_BYTES).status_code == 200
    unchanged = env.alerts("unchanged_submission")
    assert len(unchanged) == 1 and "sınav dosyasının kendisi" in unchanged[0]["message"]
    assert env.snapshot_student("2021000002")["warn_count"] == 1

    # A file of a very different size, saved before the exam file was downloaded.
    assert env.submit(c, b"minik", stale="true").status_code == 200
    assert "yanlış dosya olabilir" in env.alerts("suspicious_size")[0]["message"]
    assert "indirilmeden önce" in env.alerts("stale_submission")[0]["message"]

    # The streams of students whose file has arrived are stopped.
    env.store.apply_streams({"2021000001", "2021000002", "777"}, {})
    assert sorted(env.store.streams_to_stop()) == ["2021000001", "2021000002"]


def test_submission_needs_the_exam_folder(env: Env):
    client, _ = env.login()
    env.start()
    env.store.exam_dir = None  # e.g. a state file from an older version
    response = env.submit(client, b"cozum")
    assert response.status_code == 409 and "Sınav klasörü" in response.json()["error"]


def test_virtual_desktop_switch_is_an_alert(env: Env):
    client, _ = env.login()
    env.start()
    client.post("/api/event", json={"type": "desktop_switch", "details": {}})
    client.post("/api/event", json={"type": "desktop_return", "details": {"seconds": 12}})
    alerts = env.alerts("desktop_switch")
    assert len(alerts) == 1 and alerts[0]["message"] == "Başka bir masaüstüne geçti"
    assert not env.alerts("desktop_return")
    assert any(e.message == "Sınav masaüstüne geri döndü (12 sn sonra)" for e in env.store.events)
    assert env.snapshot_student("2021000001")["status"] == "warn"


# ------------------------------------------------------ class and teacher name


def test_class_and_teacher_name_are_changed_in_the_panel(env: Env):
    response = env.panel.post("/panel/api/identity", headers=PANEL,
                              json={"sinif_adi": "  Lab  3 ", "ogretmen_adi": "Dr. Işıl Öz"})
    assert response.json() == {"sinif_adi": "Lab 3", "ogretmen_adi": "Dr. Işıl Öz"}
    info = env.student().get("/api/info").json()
    assert (info["sinif_adi"], info["ogretmen_adi"]) == ("Lab 3", "Dr. Işıl Öz")
    assert env.store.snapshot()["class"] == {"sinif_adi": "Lab 3", "ogretmen_adi": "Dr. Işıl Öz", "saved": True}
    assert "Lab 3" in env.student().get("/").text

    assert env.panel.post("/panel/api/identity", headers=PANEL,
                          json={"sinif_adi": "", "ogretmen_adi": "X"}).status_code == 422
    assert env.student().post("/panel/api/identity", headers=PANEL,
                              json={"sinif_adi": "A", "ogretmen_adi": "B"}).status_code == 403

    # The panel's choice wins over config.yaml after a restart.
    from sinav.config import load_config
    cfg = load_config(env.cfg.path)
    assert cfg.sinif_adi == "B-102"
    restored = Store(cfg)
    restored.load()
    restored.load_settings()
    assert (cfg.sinif_adi, cfg.ogretmen_adi) == ("Lab 3", "Dr. Işıl Öz")

    env.start()
    assert env.panel.post("/panel/api/identity", headers=PANEL,
                          json={"sinif_adi": "A", "ogretmen_adi": "B"}).status_code == 409


# ------------------------------------------- "Sınavı başlat": time limit, recording, planned start


def prepare(env: Env):
    assert env.choose_folder().status_code == 200
    assert env.upload_exam().status_code == 200


def start_with(env: Env, **body):
    return env.panel.post("/panel/api/start", headers=PANEL, json=body)


def test_exam_cannot_start_without_the_exam_file(env: Env):
    # Starting the exam is what shares the file with the students.
    env.choose_folder()
    response = start_with(env, duration_min=30)
    assert response.status_code == 409 and ".pka" in response.json()["error"]
    assert env.store.state == WAITING


def test_time_limit_is_a_countdown_and_never_ends_the_exam(env: Env):
    client, _ = env.login()
    prepare(env)
    for bad in ("abc", 0.5, -5, 601):
        assert start_with(env, duration_min=bad).status_code == 422, bad
    assert env.store.state == WAITING

    assert start_with(env, duration_min=40).status_code == 200
    exam = env.store.snapshot()["exam"]
    assert exam["duration_min"] == 40 and round(exam["ends_at"] - exam["started_at"]) == 40 * 60
    hb = client.post("/api/heartbeat", json={}).json()
    assert hb["exam_state"] == RUNNING and hb["ends_at"] == exam["ends_at"]

    # Extra time moves the deadline.
    assert env.panel.post("/panel/api/extend", headers=PANEL, json={"minutes": 0}).status_code == 422
    extended = env.panel.post("/panel/api/extend", headers=PANEL, json={"minutes": 5}).json()
    assert round(extended["ends_at"] - exam["ends_at"]) == 300
    assert env.store.snapshot()["exam"]["duration_min"] == 45

    env.store.tick()
    assert not env.alerts("time_up")  # not yet

    # The time is up: the exam goes on. Only the teacher is told, once.
    env.store.ends_at = time.time() - 90
    env.store.tick()
    env.store.tick()
    assert env.store.state == RUNNING
    told = env.alerts("time_up")
    assert len(told) == 1 and told[0]["numara"] == "" and told[0]["message"].startswith("Sınav süresi doldu")
    hb = client.post("/api/heartbeat", json={}).json()
    assert hb["exam_state"] == RUNNING and hb["ends_at"] == env.store.ends_at
    assert client.get("/api/exam-file").status_code == 200       # nothing changes for the students ...
    assert env.submit(client, EXAM_BYTES + b"-cozum").json()["late"] is False  # ... handing in is not late

    # Extra time after the time was up counts from now, and the teacher is told again later.
    before = time.time()
    ends_at = env.panel.post("/panel/api/extend", headers=PANEL, json={"minutes": 10}).json()["ends_at"]
    assert 599 <= ends_at - before <= 602
    env.store.ends_at = time.time() - 1
    env.store.tick()
    assert len(env.alerts("time_up")) == 2 and env.store.state == RUNNING

    # Only the teacher ends the exam.
    assert env.panel.post("/panel/api/end", headers=PANEL).status_code == 200
    assert env.store.state == ENDED


def test_extra_time_for_an_exam_without_a_time_limit(env: Env):
    client, _ = env.login()
    prepare(env)
    assert env.panel.post("/panel/api/extend", headers=PANEL, json={"minutes": 5}).status_code == 409  # not running
    start_with(env)
    env.store.tick()
    assert env.store.state == RUNNING and env.store.ends_at == 0  # no time limit, no countdown

    # "Ek süre ver" in the end-of-exam window: the students now see a ten minute countdown.
    before = time.time()
    ends_at = env.panel.post("/panel/api/extend", headers=PANEL, json={"minutes": 10}).json()["ends_at"]
    assert 599 <= ends_at - before <= 602
    assert client.post("/api/heartbeat", json={}).json()["ends_at"] == ends_at
    env.store.ends_at = time.time() - 1
    env.store.tick()
    assert env.store.state == RUNNING and len(env.alerts("time_up")) == 1


def test_recording_is_a_choice_made_when_the_exam_starts(env: Env):
    prepare(env)
    assert env.store.record_path == ""
    assert start_with(env, record=False).status_code == 200
    # The screens are still streamed to the panel; they are just not kept on disk.
    assert env.store.record_path == "" and env.store.snapshot()["exam"]["record"] is False
    assert "ekranlar kaydedilmiyor" in env.store.events[-1].message

    # Agents are told nothing about it.
    client, body = env.login()
    assert "record" not in body and "record" not in client.post("/api/heartbeat", json={}).json()

    env.panel.post("/panel/api/end", headers=PANEL)
    env.panel.post("/panel/api/reset", headers=PANEL)
    prepare(env)
    assert start_with(env, record=True).status_code == 200
    assert env.store.record_path.endswith("%Y-%m-%d_%H-%M-%S_%z")
    assert "ekranlar kaydediliyor" in env.store.events[-1].message


def test_planned_start(env: Env):
    client, _ = env.login()
    prepare(env)
    assert start_with(env, start_at="yarın").status_code == 422
    assert start_with(env, start_at=time.time() + 3 * 24 * 3600).status_code == 422
    assert env.panel.post("/panel/api/cancel-start", headers=PANEL).status_code == 409

    at = time.time() + 600
    response = start_with(env, start_at=at, duration_min=30, record=False)
    assert response.status_code == 200 and response.json()["state"] == WAITING
    assert env.store.snapshot()["exam"]["scheduled"] == {"at": at, "duration_min": 30, "record": False}
    hb = client.post("/api/heartbeat", json={}).json()
    assert hb["exam_state"] == WAITING and hb["scheduled_at"] == at
    assert client.get("/api/exam-file").status_code == 409  # not shared before the start
    env.store.tick()
    assert env.store.state == WAITING

    # The plan survives a restart of the server.
    env.store.save()
    restored = Store(env.cfg)
    restored.load()
    assert restored.scheduled == {"at": at, "duration_min": 30, "record": False}

    # It can be cancelled ...
    assert env.panel.post("/panel/api/cancel-start", headers=PANEL).status_code == 200
    assert env.store.snapshot()["exam"]["scheduled"] is None
    assert client.post("/api/heartbeat", json={}).json()["scheduled_at"] == 0

    # ... and when the time comes the exam starts by itself, with the chosen options.
    start_with(env, start_at=time.time() + 600, duration_min=30, record=False)
    env.store.scheduled["at"] = time.time() - 1
    env.store.tick()
    exam = env.store.snapshot()["exam"]
    assert exam["state"] == RUNNING and exam["scheduled"] is None
    assert exam["duration_min"] == 30 and exam["record"] is False
    assert client.get("/api/exam-file").content == EXAM_BYTES

    # A time that has already passed means "now".
    env.panel.post("/panel/api/end", headers=PANEL)
    env.panel.post("/panel/api/reset", headers=PANEL)
    prepare(env)
    assert start_with(env, start_at=time.time() - 30).json()["state"] == RUNNING


# ------------------------------------------------ after the end: late submissions, closing


def test_students_can_still_hand_in_after_the_end_but_it_is_marked_late(env: Env):
    on_time, _ = env.login(numara="2021000001", mac="AA:BB:CC:00:00:01")
    late, _ = env.login(numara="2021000002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    env.start()
    assert env.submit(on_time, EXAM_BYTES + b"-1").json()["late"] is False
    env.panel.post("/panel/api/end", headers=PANEL)

    # The exam is over, but nobody is thrown out: the student is told the exam has ended ...
    hb = late.post("/api/heartbeat", json={}).json()
    assert hb["exam_state"] == ENDED and hb["submitted"] is False
    assert late.get("/api/exam-file").status_code == 409  # ... the file can no longer be downloaded ...
    assert env.snapshot_student("2021000002")["status"] == "nosubmit"

    # ... and a file handed in now is accepted and marked as late.
    env.store.ended_at -= 4 * 60
    result = env.submit(late, EXAM_BYTES + b"-2")
    assert result.status_code == 200 and result.json()["late"] is True
    st = env.snapshot_student("2021000002")
    assert st["status"] == "done" and st["submission"]["late"] is True
    alert = env.alerts("late_submission")
    assert len(alert) == 1 and alert[0]["numara"] == "2021000002" and alert[0]["severity"] == "warning"
    assert alert[0]["message"] == "Geç teslim: dosyasını sınav bittikten 4 dakika sonra teslim etti"
    assert any(e.message.startswith("Geç teslim etti: 2021000002_CanEr.pka") for e in env.store.events)
    rows = list(csv.reader(io.StringIO((env.submissions / "index.csv").read_text(encoding="utf-8-sig")),
                           delimiter=";"))
    assert rows[0][7] == "gec_teslim" and [r[7] for r in rows[1:]] == ["hayır", "evet"]


def test_a_file_that_was_already_on_its_way_is_not_late(env: Env):
    client, _ = env.login()
    env.start()
    env.panel.post("/panel/api/end", headers=PANEL)
    assert env.submit(client, EXAM_BYTES + b"-son-saniye").json()["late"] is False
    assert not env.alerts("late_submission")


def test_every_student_has_a_log_file_with_who_they_are_and_everything_recorded(env: Env):
    a, _ = env.login(numara="2021000001", ad="Ahmet Şahin", soyad="Çakır", mac="AA:BB:CC:00:00:01", hostname="PC-01")
    b, _ = env.login(numara="2021000002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    # A warning from before the exam folder was chosen ...
    a.post("/api/event", json={"type": "monitor_change", "details": {"count": 2, "previous": 1}})
    env.start()
    folder = env.exam_dir / "Uyarılar"
    assert env.store.snapshot()["paths"]["alerts"] == str(folder.resolve())
    # ... is written as soon as the folder exists.
    path = folder / "2021000001_AhmetSahinCakir.csv"
    assert "Monitör sayısı: 2 (önceki: 1)" in path.read_text(encoding="utf-8-sig")

    a.post("/api/event", json={"type": "process_killed", "details": {"name": "chrome.exe"}})
    a.post("/api/event", json={"type": "foreground_change", "details": {"name": "PacketTracer.exe"}})  # not a warning
    a.post("/api/event", json={"type": "desktop_switch", "details": {}})
    env.store.flush_student_logs()      # ordinary entries are written every few seconds
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig")), delimiter=";"))
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # opens correctly in Excel

    # First who the student is ...
    assert rows[0] == ["ÖĞRENCİ"]
    info = dict(row for row in rows[1:rows.index([])])
    assert info["Numara"] == "2021000001" and info["Ad soyad"] == "Ahmet Şahin Çakır"
    assert info["Bilgisayar adı"] == "PC-01" and info["MAC adresi"] == "AA:BB:CC:00:00:01"
    assert info["IP adresi"] == "192.168.1.50" and info["Program sürümü"] == "test"
    assert info["Öğrenci listesi"] == "Liste yüklü değil" and info["Giriş sayısı"] == "1"
    assert info["Teslim"] == "Teslim etmedi" and info["Uyarı sayısı"] == "3" and info["Sınıf"] == "B-102"
    assert info["İlk giriş"].startswith(time.strftime("%Y-"))

    # ... then everything that was recorded: warnings marked, ordinary entries too.
    table = rows[rows.index(["KAYITLAR"]) + 1:]
    assert table[0] == ["Zaman", "Tür", "Kayıt"]
    entries = [(row[1], row[2]) for row in table[1:]]
    assert entries[0][0] == "bilgi" and entries[0][1].startswith("Giriş yaptı — IP 192.168.1.50")
    assert ("UYARI", "Monitör sayısı: 2 (önceki: 1)") in entries
    assert ("UYARI", "chrome.exe kapatıldı") in entries and ("UYARI", "Başka bir masaüstüne geçti") in entries
    assert ("bilgi", "Öndeki pencere: PacketTracer.exe") in entries
    # What applied to everybody (the start of the exam) is in each file as well.
    assert any(kind == "sınav" and text.startswith("Sınav başladı") for kind, text in entries)
    assert [row[0] for row in table[1:]] == sorted(row[0] for row in table[1:])      # in order of time

    # A student without warnings has a file too; a late submission is a warning like any other.
    other = folder / "2021000002_CanEr.csv"
    env.store.flush_student_logs()
    assert "Uyarı sayısı;0" in other.read_text(encoding="utf-8-sig")
    env.panel.post("/panel/api/end", headers=PANEL)
    env.store.ended_at -= 120
    env.submit(b, EXAM_BYTES + b"-gec")
    text = other.read_text(encoding="utf-8-sig")
    assert "UYARI;Geç teslim" in text and "sınav;Sınav bitirildi" in text
    env.store.flush_student_logs()
    assert "2021000002_CanEr.pka" in other.read_text(encoding="utf-8-sig") and "(geç teslim)" in other.read_text(encoding="utf-8-sig")

    # The files stay in the exam folder when a new exam is prepared.
    env.panel.post("/panel/api/reset", headers=PANEL)
    assert path.exists() and other.exists()


def test_stream_quality_values_reach_the_student_program(env: Env):
    """What the student program is told about the picture: nothing extra by default (it uses its
    own values), the panel's quality choice, or the values written in config.yaml."""
    _, first = env.login()
    assert set(first["stream"]) == {"url", "user", "pass"}

    env.panel.post("/panel/api/settings", headers=PANEL, json={"quality": "high"})
    _, high = env.login(numara="2021000002", ip="192.168.1.51", mac="AA:BB:CC:00:00:02")
    assert {k: high["stream"][k] for k in ("fps", "width", "bitrate_kbps", "crf")} == {
        "fps": 6, "width": 1600, "bitrate_kbps": 900, "crf": 21}

    # config.yaml (yayin: kalite_crf / anahtar_kare_sn) is the base the panel's choice lies over.
    text = env.cfg.path.read_text(encoding="utf-8")
    assert "yayin:\n" in text
    env.cfg.path.write_text(text.replace("yayin:\n", "yayin:\n  kalite_crf: 30\n  anahtar_kare_sn: 4\n", 1), encoding="utf-8")
    fresh = load_config(env.cfg.path)
    assert (fresh.stream_crf, fresh.stream_keyframe_s) == (30, 4)
    env.cfg.path.write_text(text.replace("yayin:\n", "yayin:\n  kalite_crf: 99\n", 1), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(env.cfg.path)


def test_new_entries_are_added_at_the_end_of_the_student_file(env: Env, monkeypatch):
    """Ordinary entries are frequent: they are added at the end of the file. The file is written
    from the top only when something in its "ÖĞRENCİ" block changes."""
    a, _ = env.login(numara="2021000001", ad="Ali", soyad="Veli")
    b, _ = env.login(numara="2021000002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    env.start()
    store = env.store
    store.flush_student_logs()
    path = env.exam_dir / "Uyarılar" / "2021000001_AliVeli.csv"
    other = env.exam_dir / "Uyarılar" / "2021000002_CanEr.csv"

    def entries(file):
        rows = list(csv.reader(io.StringIO(file.read_text(encoding="utf-8-sig")), delimiter=";"))
        return [(row[1], row[2]) for row in rows[rows.index(["Zaman", "Tür", "Kayıt"]) + 1:]]

    full_writes = []
    original = store.write_student_log
    monkeypatch.setattr(store, "write_student_log", lambda numara: (full_writes.append(numara), original(numara))[1])

    before = path.read_bytes()
    for name in ("PacketTracer.exe", "cmd.exe", "PacketTracer.exe"):
        a.post("/api/event", json={"type": "foreground_change", "details": {"name": name}})
    env.panel.post("/panel/api/extend", headers=PANEL, json={"minutes": 5})     # for everybody
    assert path.read_bytes() == before                    # not written on every entry ...
    store.flush_student_logs()                            # ... but together, every few seconds
    assert full_writes == []                              # nothing was written from the top
    assert path.read_bytes().startswith(before) and path.read_bytes().count(b"\xef\xbb\xbf") == 1
    assert [text for _, text in entries(path)][-4:-1] == [
        "Öndeki pencere: PacketTracer.exe", "Öndeki pencere: cmd.exe", "Öndeki pencere: PacketTracer.exe"]
    extra = entries(path)[-1]
    assert extra[0] == "sınav" and extra[1].startswith("5 dakika ek süre verildi") and entries(other)[-1] == extra
    store.flush_student_logs()
    assert full_writes == [] and entries(path).count(extra) == 1    # added once, not again

    # A warning changes the count at the top: the file is written again, at once, with everything in it.
    a.post("/api/event", json={"type": "foreground_change", "details": {"name": "notepad.exe"}})
    a.post("/api/event", json={"type": "process_killed", "details": {"name": "notepad.exe"}})
    assert full_writes == ["2021000001"]
    text = path.read_text(encoding="utf-8-sig")
    assert "Uyarı sayısı;1" in text and [t for _, t in entries(path)][-2:] == ["Öndeki pencere: notepad.exe", "notepad.exe kapatıldı"]
    store.flush_student_logs()
    assert entries(path).count(("bilgi", "Öndeki pencere: notepad.exe")) == 1

    # Handing in changes the top as well ("Teslim").
    env.submit(a, EXAM_BYTES + b"-cozum")
    store.flush_student_logs()
    assert "Teslim;2021000001_AliVeli.pka" in path.read_text(encoding="utf-8-sig")
    # Whichever way it was written: the file holds every entry once, in the order it happened.
    assert [text for _, text in entries(path)] == [
        e.message for e in store.events
        if e.numara == "2021000001" or (not e.numara and e.type in {"exam_started", "exam_extended"})]

    # The file was removed by hand: it is written again in full, not continued without its top.
    other.unlink()
    b.post("/api/event", json={"type": "foreground_change", "details": {"name": "cmd.exe"}})
    store.flush_student_logs()
    assert other.read_text(encoding="utf-8-sig").startswith("ÖĞRENCİ") and entries(other)[-1][1] == "Öndeki pencere: cmd.exe"


def test_student_file_that_cannot_be_written_is_tried_again(env: Env, caplog):
    """For example the file is open in Excel: nothing is lost, it is written when that is over."""
    a, _ = env.login(numara="2021000001", ad="Ali", soyad="Veli")
    env.start()
    store = env.store
    store.flush_student_logs()
    path = env.exam_dir / "Uyarılar" / "2021000001_AliVeli.csv"
    path.unlink()
    path.mkdir()                                           # nothing can be written to this name now
    caplog.clear()
    a.post("/api/event", json={"type": "foreground_change", "details": {"name": "cmd.exe"}})
    store.flush_student_logs()
    a.post("/api/event", json={"type": "process_killed", "details": {"name": "chrome.exe"}})
    store.flush_student_logs()
    store.flush_student_logs()
    assert len([r for r in caplog.records if "kayıt dosyası yazılamadı" in r.getMessage()]) == 1   # said once

    path.rmdir()
    store.flush_student_logs()                             # no new entry is needed for the next try
    text = path.read_text(encoding="utf-8-sig")
    assert "Öndeki pencere: cmd.exe" in text and "UYARI;chrome.exe kapatıldı" in text and "Uyarı sayısı;1" in text


def test_warning_file_follows_the_name_in_the_student_list(env: Env):
    client, _ = env.login(numara="2021000001", ad="Ali", soyad="Veli")
    env.start()
    client.post("/api/event", json={"type": "process_killed", "details": {"name": "chrome.exe"}})
    folder = env.exam_dir / "Uyarılar"
    assert (folder / "2021000001_AliVeli.csv").exists()
    upload_roster(env, [[2021000001, "Ali Rıza", "Veli"]])
    assert [p.name for p in folder.iterdir()] == ["2021000001_AliRizaVeli.csv"]
    assert "Ad uyuşmuyor" in (folder / "2021000001_AliRizaVeli.csv").read_text(encoding="utf-8-sig")


def test_new_exam_closes_the_student_programs_that_are_still_open(env: Env):
    client, _ = env.login()
    env.start()
    env.panel.post("/panel/api/end", headers=PANEL)
    assert [st.numara for st in env.store.open_agents()] == ["2021000001"]

    # While the exam is being closed, agents are told so and exit. Nothing is collected
    # automatically: a student who did not hand in has no file.
    env.store.closing = True
    hb = client.post("/api/heartbeat", json={}).json()
    assert hb["exam_state"] == CLOSED and env.store.students["2021000001"].closed_seen
    env.store.closing = False

    assert env.panel.post("/panel/api/reset", headers=PANEL).json() == {"state": WAITING}
    assert env.store.closing is False and env.store.students == {}
    assert not list(env.submissions.glob("*.pka"))


def test_shutting_the_system_down_ends_the_exam_and_stops_the_server(env: Env):
    stopped = []
    env.app.state.stop_server = lambda: stopped.append(True)
    env.login()
    env.store.students["2021000001"].last_hb_mono -= 60  # that program is gone: nothing to wait for
    env.start()
    assert env.student().post("/panel/api/shutdown", headers=PANEL).status_code == 403
    assert env.panel.post("/panel/api/shutdown", headers=PANEL).json() == {"ok": True}
    deadline = time.time() + 5
    while not stopped and time.time() < deadline:
        time.sleep(0.05)
    assert stopped == [True] and env.app.state.exit_code == 10
    assert env.store.state == ENDED and env.store.closing
    assert "Sistem kapatıldı" in (env.exam_dir / "olay-kaydi.csv").read_text(encoding="utf-8-sig")


def test_panel_window_is_opened_like_an_application(env: Env, monkeypatch):
    import sinav.app as app_module
    from conftest import write_config
    from sinav.config import load_config

    opened = []
    monkeypatch.setattr(app_module, "open_panel_window",
                        lambda url, as_app=True: opened.append((url, as_app)) or "app")
    # start-teacher.bat calls this when the system is already running in the background.
    assert env.panel.post("/panel/api/open-window", headers=PANEL).json() == {"window": "app"}
    assert opened == [("http://localhost:8000/panel", True)]
    assert env.student().post("/panel/api/open-window", headers=PANEL).status_code == 403
    assert env.store.snapshot()["health"]["panel_clients"] == 0

    # An ordinary browser tab can be chosen in config.yaml.
    assert env.cfg.panel_as_app is True
    other = env.tmp_path / "tarayici"
    other.mkdir()
    cfg = load_config(write_config(other, "").parent / "config.yaml")
    assert cfg.panel_as_app is True
    text = (other / "config.yaml").read_text(encoding="utf-8").replace("  port: 8000", "  port: 8000\n  panel_penceresi: tarayici")
    (other / "config.yaml").write_text(text, encoding="utf-8")
    assert load_config(other / "config.yaml").panel_as_app is False


def test_closing_the_panel_closes_the_system_but_waits_while_students_are_connected(env: Env):
    # Nothing is asked when the panel window (or the browser tab) is closed: the system shuts
    # down by itself. How long it waits first depends on whether anybody is connected.
    assert (env.cfg.close_after_s, env.cfg.close_after_busy_s) == (5, 120)
    assert env.store.close_grace_s() == 5

    client, _ = env.login()
    assert env.store.close_grace_s() == 120  # a student program is connected: time to reopen the panel
    env.start()
    env.submit(client, EXAM_BYTES + b"-cozum")
    assert env.store.open_agents() == [] and env.store.close_grace_s() == 120  # the exam is still running
    env.panel.post("/panel/api/end", headers=PANEL)
    assert env.store.close_grace_s() == 5  # over, everybody handed in

    # A student who has not handed in yet keeps the system up for the longer time.
    env.login(numara="2021000002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    assert env.store.close_grace_s() == 120


def test_texts_for_students_do_not_mention_the_teacher(env: Env):
    page = env.student().get("/").text
    assert "ğretmen" not in page.replace("Ayşe Öğretmen", "")  # only the configured name itself
    assert "Ayşe Öğretmen" in page
    client, _ = env.login()
    _, body = env.login(ip="192.168.1.51", mac="AA:BB:CC:00:00:02", hostname="PC-02", expect=409)
    refused = env.student().post("/panel/api/end", headers=PANEL).json()["error"]
    for text in (body["error"], refused):
        assert "ğretmen" not in text, text


def test_student_program_is_one_file_that_can_be_downloaded_from_the_server(env: Env):
    student = env.student()
    page = student.get("/")
    assert page.status_code == 200
    assert "dağıtılmıyor" in page.text and "/indir/" not in page.text
    assert student.get("/indir/SinavAjan.exe").status_code == 404

    assert env.panel.get("/panel/api/state").json()["health"]["agent_download"] is False
    env.cfg.dir_dist.mkdir(parents=True, exist_ok=True)
    (env.cfg.dir_dist / "SinavAjan.exe").write_bytes(b"MZ" + b"x" * 5000)
    # The panel then shows the address a student can type into a browser.
    assert env.panel.get("/panel/api/state").json()["health"]["agent_download"] is True
    page = student.get("/")
    assert '/indir/SinavAjan.exe' in page.text
    assert "çift tıklayın" in page.text
    assert "zip" not in page.text.lower() and "ayıkla" not in page.text.lower()
    download = student.get("/indir/SinavAjan.exe")
    assert download.status_code == 200
    assert download.content == b"MZ" + b"x" * 5000
    assert 'filename="SinavAjan.exe"' in download.headers["content-disposition"]


def test_panel_asks_for_the_class_details_until_they_were_entered_once(env: Env, tmp_path):
    assert env.panel.get("/panel/api/state").json()["class"]["saved"] is False
    env.panel.post("/panel/api/identity", headers=PANEL, json={"sinif_adi": "A-1", "ogretmen_adi": "Ada Kaya"})
    assert env.panel.get("/panel/api/state").json()["class"] == {
        "sinif_adi": "A-1", "ogretmen_adi": "Ada Kaya", "saved": True}

    # The next start reads what was entered: nothing to ask.
    again = Store(env.cfg)
    again.load_settings()
    assert again.snapshot()["class"]["saved"] is True


# ------------------------------------------------------- students of the list before they log in


def test_students_of_the_list_are_shown_before_they_log_in(env: Env):
    assert env.store.snapshot()["students"] == []
    upload_roster(env, [[2021000003, "Can", "Demir"], [2021000001, "Ali", "Veli"], [2021000002, "Ayşe", "Yılmaz"]])

    snapshot = env.panel.get("/panel/api/state").json()
    assert [(s["numara"], s["ad"], s["status"]) for s in snapshot["students"]] == [
        ("2021000001", "Ali", "absent"), ("2021000002", "Ayşe", "absent"), ("2021000003", "Can", "absent")]
    assert all(s["stream_ready"] is False and s["submission"] is None for s in snapshot["students"])
    assert snapshot["summary"] == {"total": 0, "connected": 0, "warned": 0, "lost": 0, "submitted": 0, "absent": 3}

    # A student who logs in takes the place of the placeholder; a student who is not on the
    # list is shown as well.
    env.login(numara="2021000002", ad="Ayşe", soyad="Yılmaz")
    env.login(numara="2021000009", ad="Liste", soyad="Dışı", ip="192.168.1.59", mac="AA:BB:CC:00:00:09")
    snapshot = env.store.snapshot()
    assert [(s["numara"], s["status"]) for s in snapshot["students"]] == [
        ("2021000001", "absent"), ("2021000002", "ok"), ("2021000003", "absent"), ("2021000009", "warn")]
    assert snapshot["summary"]["total"] == 2 and snapshot["summary"]["absent"] == 2

    # Still listed while the exam runs and after it ended.
    env.choose_folder()
    env.upload_exam()
    env.start()
    assert env.snapshot_student("2021000001")["status"] == "absent"
    env.panel.post("/panel/api/end", headers=PANEL)
    assert env.snapshot_student("2021000001")["status"] == "absent"
    assert env.snapshot_student("2021000002")["status"] == "nosubmit"


# ---------------------------------------------------------------------- settings in the panel


def test_settings_window_shows_the_values_in_force(env: Env):
    view = env.panel.get("/panel/api/settings").json()
    assert view["values"] == view["defaults"] == {
        "programs": [], "quality": "normal", "student_label": "name", "foreground_tolerance_s": 5,
        "kill_countdown_s": 10, "disconnect_s": 10, "close_wait_min": 2, "retention_note": env.cfg.retention_note,
    }
    assert view["limits"]["foreground_tolerance_s"] == {"min": 1, "max": 120}
    assert env.student().get("/panel/api/settings").status_code == 403
    assert env.student().post("/panel/api/settings", headers=PANEL, json={}).status_code == 403


def test_settings_changed_in_the_panel_take_effect_at_once(env: Env):
    client, session = env.login()
    version = session["allowlist"]["version"]
    assert "fps" not in session["stream"]

    saved = env.panel.post("/panel/api/settings", headers=PANEL, json={
        "programs": ["putty.exe", "Wireshark", r"C:\Program Files\Tera Term\\", "PUTTY.EXE"],
        "quality": "low", "foreground_tolerance_s": 8, "kill_countdown_s": 0, "disconnect_s": 20,
        "close_wait_min": 5, "retention_note": "Kayıtlar  30 gün\nsaklanır.",
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["values"]["programs"] == ["putty.exe", "Wireshark.exe", "C:\\Program Files\\Tera Term\\"]

    # The student program that is already running is told that the rules changed ...
    beat = client.post("/api/heartbeat", json={}).json()
    assert beat["allowlist_version"] != version
    policy = env.cfg.policy
    assert policy.patterns[:2] == ["C:\\Program Files\\Cisco Packet Tracer*\\",
                                   "C:\\Program Files (x86)\\Cisco Packet Tracer*\\"]
    assert policy.patterns[2:] == ["**\\putty.exe", "**\\Wireshark.exe", "C:\\Program Files\\Tera Term\\"]
    assert (policy.foreground_tolerance_s, policy.kill_countdown_s) == (8, 0)
    assert env.store.agent_settings()["foreground_tolerance_s"] == 8
    # ... and the rest applies on the server at once.
    assert env.cfg.disconnect_s == 20 and env.cfg.close_after_busy_s == 300
    assert env.student().get("/api/info").json()["retention_note"] == "Kayıtlar 30 gün saklanır."
    # The picture quality reaches a student at the next login.
    _, again = env.login(numara="2021000002", ip="192.168.1.51", mac="AA:BB:CC:00:00:02")
    assert (again["stream"]["fps"], again["stream"]["width"], again["stream"]["bitrate_kbps"]) == (3, 960, 300)
    assert again["stream"]["crf"] == 26 and "keyframe_s" not in again["stream"]

    # Kept for the next start; class details and settings share the file without losing each other.
    env.panel.post("/panel/api/identity", headers=PANEL, json={"sinif_adi": "A-1", "ogretmen_adi": "Ada Kaya"})
    stored = json.loads(env.store.settings_path.read_text(encoding="utf-8"))
    assert stored["sinif_adi"] == "A-1" and stored["ayarlar"]["quality"] == "low"
    fresh = load_config(env.cfg.path)
    restarted = Store(fresh)
    restarted.load_settings()
    assert restarted.user_settings == env.store.user_settings
    assert fresh.policy.patterns == policy.patterns and fresh.disconnect_s == 20
    assert fresh.sinif_adi == "A-1" and restarted.identity_saved

    # Back to the defaults: nothing is stored any more.
    defaults = env.panel.get("/panel/api/settings").json()["defaults"]
    env.panel.post("/panel/api/settings", headers=PANEL, json=defaults)
    assert env.store.user_settings == {}
    assert len(env.cfg.policy.patterns) == 2 and env.cfg.disconnect_s == 10 and env.cfg.stream_fps is None
    assert "ayarlar" not in json.loads(env.store.settings_path.read_text(encoding="utf-8"))


def test_settings_that_cannot_be_used_are_refused_and_change_nothing(env: Env):
    env.panel.post("/panel/api/settings", headers=PANEL, json={"programs": ["putty.exe"]})
    for bad, text in (
        ({"programs": ["C:\\**"]}, "çok geniş"),
        ({"programs": ["*.exe"]}, "dosya adını"),
        ({"programs": ["notlar.txt"]}, "dosya adını"),
        ({"programs": ["Program Files\\x\\"]}, "C:\\"),
        ({"programs": "putty.exe"}, "liste"),
        ({"foreground_tolerance_s": 0}, "1 ile 120"),
        ({"disconnect_s": "çok"}, "sayı"),
        ({"quality": "ultra"}, "Görüntü kalitesi"),
        ({"retention_note": "x" * 401}, "400"),
    ):
        response = env.panel.post("/panel/api/settings", headers=PANEL, json=bad)
        assert response.status_code == 422 and text in response.json()["error"], (bad, response.text)
    assert env.store.user_settings == {"programs": ["putty.exe"]}
    assert env.cfg.policy.patterns[-1] == "**\\putty.exe"


def test_panel_settings_stay_in_force_when_the_settings_file_is_read_again(env: Env):
    env.panel.post("/panel/api/settings", headers=PANEL, json={"programs": ["putty.exe"], "kill_countdown_s": 3})
    text = env.cfg.path.read_text(encoding="utf-8")
    env.cfg.path.write_text(text + "\nizin_listesi:\n  - 'D:\\Araclar\\'\n", encoding="utf-8")
    os.utime(env.cfg.path, (time.time() + 5, time.time() + 5))

    from sinav.config import reload_policy
    reload_policy(env.cfg)
    env.store.policy_file_reloaded()
    assert env.cfg.policy.patterns == ["D:\\Araclar\\", "**\\putty.exe"]
    assert env.cfg.policy.kill_countdown_s == 3



def test_same_computer_warning_names_everybody_who_used_it_before(env: Env):
    upload_roster(env, [[2021000001, "Ali", "Veli"]])
    env.login(numara="2021000001", ad="Alican", soyad="Velioğlu", mac="AA:BB:CC:00:00:01")   # typed another name
    env.login(numara="2021000002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:01", ip="192.168.1.51")
    env.login(numara="2021000003", ad="Ece", soyad="Su", mac="AA:BB:CC:00:00:01", ip="192.168.1.52")
    message = next(a["message"] for a in env.alerts("mac_reuse") if a["numara"] == "2021000003")
    # What was typed at the login, not the name on the list.
    assert "daha önce 2021000001 Alican Velioğlu, 2021000002 Can Er giriş yapmıştı" in message
    env.choose_folder()
    env.store.write_all_student_logs()
    log_file = next(env.store.dir_alerts.glob("2021000003_*.csv")).read_text(encoding="utf-8-sig")
    assert "2021000001 Alican Velioğlu, 2021000002 Can Er" in log_file


# ------------------------------------------------------------- adding a student by hand


def test_a_student_can_be_added_to_the_list_by_hand_at_any_time(env: Env):
    upload_roster(env, [[2021000001, "Ali", "Veli"]])
    stranger, session = env.login(numara="2021000005", ad="Elif", soyad="Şahin", ip="192.168.1.55",
                                  mac="AA:BB:CC:00:00:05")
    assert env.snapshot_student("2021000005")["roster"] == "not_in_list"

    # Before the exam: somebody who is not here yet.
    added = env.panel.post("/panel/api/roster/add", headers=PANEL,
                           json={"numara": " 2021000009 ", "ad": "  zeynep ", "soyad": "Ak"})
    assert added.status_code == 200 and added.json() == {"numara": "2021000009", "ad": "zeynep", "soyad": "Ak"}
    waiting = env.snapshot_student("2021000009")
    assert waiting["status"] == "absent" and waiting["manual"] is True

    # During the exam: the student who was reported as "not on the list".
    env.choose_folder()
    env.upload_exam()
    env.start()
    assert env.panel.post("/panel/api/roster/add", headers=PANEL,
                          json={"numara": "2021000005", "ad": "Elif", "soyad": "Şahin"}).status_code == 200
    assert env.snapshot_student("2021000005")["roster"] == "ok"
    # After the exam as well.
    env.panel.post("/panel/api/end", headers=PANEL)
    assert env.panel.post("/panel/api/roster/add", headers=PANEL,
                          json={"numara": "2021000010", "ad": "Jale", "soyad": "Arslan"}).status_code == 200

    snapshot = env.store.snapshot()
    assert snapshot["roster"]["count"] == 4 and snapshot["roster"]["manual"] == 3
    assert [s["numara"] for s in snapshot["students"]] == ["2021000001", "2021000005", "2021000009", "2021000010"]
    messages = [e.message for e in env.store.events if e.type == "roster_added"]
    assert messages[0] == "Öğrenci listeye elle eklendi: 2021000009 zeynep Ak" and len(messages) == 3

    for bad, status, text in (
        ({"numara": "2021000009", "ad": "Zeynep", "soyad": "Ak"}, 409, "zaten var"),
        ({"numara": "20 21", "ad": "A", "soyad": "B"}, 422, "10 haneli"),
        ({"numara": "202100001", "ad": "A", "soyad": "B"}, 422, "10 haneli"),
        ({"numara": "2021000011", "ad": "", "soyad": "B"}, 422, "boş bırakılamaz"),
    ):
        response = env.panel.post("/panel/api/roster/add", headers=PANEL, json=bad)
        assert response.status_code == status and text in response.json()["error"], response.text
    assert env.student().post("/panel/api/roster/add", headers=PANEL, json={}).status_code == 403

    # A new list file replaces the list but keeps who was added by hand.
    upload_roster(env, [[2021000001, "Ali", "Veli"], [2021000002, "Ayşe", "Yılmaz"], [2021000009, "Zeynep", "Ak"]])
    assert sorted(env.store.roster) == ["2021000001", "2021000002", "2021000005", "2021000009", "2021000010"]
    assert env.store.roster["2021000009"].manual is False and env.store.roster["2021000009"].ad == "Zeynep"

    # Survives a restart.
    env.store.save()
    restored = Store(env.cfg)
    restored.load()
    assert restored.roster["2021000010"].manual is True and restored.roster["2021000001"].manual is False


def test_students_added_by_hand_alone_do_not_flag_everybody_else(env: Env):
    env.login(numara="2021000001")
    env.panel.post("/panel/api/roster/add", headers=PANEL, json={"numara": "2021000002", "ad": "Ayşe", "soyad": "Yılmaz"})
    env.login(numara="2021000003", ad="Can", soyad="Demir", ip="192.168.1.53", mac="AA:BB:CC:00:00:03")
    assert env.snapshot_student("2021000001")["roster"] == "no_roster"
    assert env.snapshot_student("2021000003")["roster"] == "no_roster"
    assert not env.alerts("not_in_roster")
    # The name typed at the login is checked against the hand-made entry.
    env.login(numara="2021000002", ad="Başka", soyad="Biri", ip="192.168.1.52", mac="AA:BB:CC:00:00:02")
    assert env.snapshot_student("2021000002")["roster"] == "name_mismatch"
    assert env.snapshot_student("2021000002")["ad"] == "Ayşe"


def test_a_student_who_has_not_logged_in_can_be_taken_off_the_list(env: Env):
    upload_roster(env, [[2021000001, "Ali", "Veli"], [2021000002, "Ayşe", "Yılmaz"]])
    env.panel.post("/panel/api/roster/add", headers=PANEL, json={"numara": "2021000099", "ad": "Yanlış", "soyad": "Numara"})
    env.login(numara="2021000001")

    assert env.panel.post("/panel/api/roster/remove", headers=PANEL, json={"numara": "2021000099"}).status_code == 200
    assert env.panel.post("/panel/api/roster/remove", headers=PANEL, json={"numara": "2021000002"}).status_code == 200
    assert [s["numara"] for s in env.store.snapshot()["students"]] == ["2021000001"]
    assert [e.message for e in env.store.events if e.type == "roster_removed"][0] == \
        "Öğrenci listeden çıkarıldı: 2021000099 Yanlış Numara"

    logged_in = env.panel.post("/panel/api/roster/remove", headers=PANEL, json={"numara": "2021000001"})
    assert logged_in.status_code == 409 and "Giriş yapmış" in logged_in.json()["error"]
    assert env.panel.post("/panel/api/roster/remove", headers=PANEL, json={"numara": "2021000500"}).status_code == 404


# ------------------------------------------------------------ Alt+Tab and the desktop


def test_switching_windows_and_the_desktop_are_logged_but_never_a_warning(env: Env):
    client, _ = env.login()
    env.choose_folder()
    env.upload_exam()
    env.start()

    def report(**details):
        return client.post("/api/event", json={"type": "foreign_foreground", "details": details, "ts": time.time()})

    # Marked by the student program itself ...
    report(name="explorer.exe", title="Görev Geçişi", seconds=7, shell=True)
    report(name="explorer.exe", title="", seconds=9, shell=True)
    # ... or recognised by its title (student programs installed before this change).
    report(name="explorer.exe", title="Program Manager", seconds=12)
    report(name="Explorer.EXE", title="Task Switching", seconds=6)
    student = env.snapshot_student("2021000001")
    assert student["status"] == "ok" and student["warn_count"] == 0
    assert not env.alerts("foreign_foreground")
    logged = [e for e in env.store.events if e.type == "foreign_foreground"]
    assert len(logged) == 4 and all(e.severity == "info" and not e.alert for e in logged)
    assert logged[0].message == "Masaüstü ya da pencere geçişi önde: explorer.exe (7 sn) — pencere: “Görev Geçişi”"

    # A real window in front is still a warning: a folder window, another program.
    report(name="explorer.exe", title="Belgeler", seconds=6)
    report(name="winver.exe", title="Windows Hakkında", seconds=6)
    assert len(env.alerts("foreign_foreground")) == 2
    assert env.snapshot_student("2021000001")["status"] == "warn"
    assert "Packet Tracer dışında bir pencere önde: explorer.exe (6 sn) — pencere: “Belgeler”" in \
        [a["message"] for a in env.alerts("foreign_foreground")]


# --------------------------------------------------------------------- "Görüldü"


def test_marking_as_seen_tells_how_many_warnings_there_were(env: Env):
    client, _ = env.login()
    env.login(numara="2021000002", ip="192.168.1.51", mac="AA:BB:CC:00:00:02")
    for _ in range(3):
        client.post("/api/event", json={"type": "process_killed", "details": {"name": "chrome.exe"}, "ts": time.time()})
    assert env.panel.post("/panel/api/ack", headers=PANEL, json={"numara": "2021000002"}).json() == {"ok": True, "count": 0}
    assert env.panel.post("/panel/api/ack", headers=PANEL, json={"numara": "2021000001"}).json() == {"ok": True, "count": 3}
    assert env.panel.post("/panel/api/ack", headers=PANEL, json={}).json()["count"] == 0
    assert env.snapshot_student("2021000001")["status"] == "ok"


# ------------------------------------------------------------- recording folders


def test_recordings_go_into_a_folder_with_the_students_name(env: Env, monkeypatch):
    import sinav.app as app_module

    calls = []
    monkeypatch.setattr(app_module, "set_path_record_path", lambda api, name, path: calls.append((name, path)))

    env.login(numara="2021000001", ad="Şükrü Çağrı", soyad="Işık")
    assert env.store.record_paths() == {} and calls == []          # no exam folder yet: nothing to record into
    env.choose_folder()
    recordings = env.exam_dir.resolve() / "Kayıtlar"
    expected = str(recordings / "%path_SukruCagriIsik" / "%Y-%m-%d_%H-%M-%S_%z")
    assert env.store.record_paths() == {"2021000001": expected}
    assert env.snapshot_student("2021000001")["record_folder"] == "2021000001_SukruCagriIsik"

    # A student who logs in gets the folder at once (before the screen stream starts).
    env.login(numara="2021000002", ad="Ayşe", soyad="Yılmaz", ip="192.168.1.51", mac="AA:BB:CC:00:00:02")
    assert ("2021000002", str(recordings / "%path_AyseYilmaz" / "%Y-%m-%d_%H-%M-%S_%z")) in calls
    assert ("2021000001", expected) in calls
    # The name on the list is the one that is used.
    env.panel.post("/panel/api/roster/add", headers=PANEL, json={"numara": "2021000002", "ad": "Ayşe Nur", "soyad": "Yılmaz"})
    assert env.snapshot_student("2021000002")["record_folder"] == "2021000002_AyseNurYilmaz"


def test_new_exam_keeps_what_was_entered_in_the_panel(env: Env):
    env.panel.post("/panel/api/identity", headers=PANEL, json={"sinif_adi": "A-1", "ogretmen_adi": "Ada Kaya"})
    env.panel.post("/panel/api/settings", headers=PANEL, json={"programs": ["putty.exe"], "kill_countdown_s": 3})
    env.panel.post("/panel/api/roster/add", headers=PANEL, json={"numara": "2021000002", "ad": "Ayşe", "soyad": "Yılmaz"})
    env.panel.post("/panel/api/reset", headers=PANEL)

    assert env.panel.get("/panel/api/state").json()["class"]["saved"] is True   # not asked again
    view = env.panel.get("/panel/api/settings").json()
    assert view["values"]["programs"] == ["putty.exe"] and view["defaults"]["programs"] == []
    assert view["defaults"]["kill_countdown_s"] == 10 and view["values"]["kill_countdown_s"] == 3
    assert env.cfg.policy.patterns[-1] == "**\\putty.exe"
    assert env.store.roster["2021000002"].manual is True
    # Saving something else afterwards does not lose the settings.
    env.panel.post("/panel/api/identity", headers=PANEL, json={"sinif_adi": "A-2", "ogretmen_adi": "Ada Kaya"})
    assert json.loads(env.store.settings_path.read_text(encoding="utf-8"))["ayarlar"]["programs"] == ["putty.exe"]


# ------------------------------------------------------- starting the recording later


def test_recording_can_be_stopped_and_started_again(env: Env):
    client, _ = env.login()
    env.choose_folder()
    env.upload_exam()
    assert env.panel.post("/panel/api/record/stop", headers=PANEL).status_code == 409      # nothing to stop yet
    env.panel.post("/panel/api/start", headers=PANEL, json={"record": True})
    assert env.store.record_path != ""

    stopped = env.panel.post("/panel/api/record/stop", headers=PANEL)
    assert stopped.status_code == 200 and stopped.json() == {"record": False}
    assert env.store.record_path == "" and env.panel.get("/panel/api/state").json()["exam"]["record"] is False
    again = env.panel.post("/panel/api/record/stop", headers=PANEL)
    assert again.status_code == 409 and "açık değil" in again.json()["error"]
    assert env.student().post("/panel/api/record/stop", headers=PANEL).status_code == 403

    # ... and on again, as often as wanted while the exam runs.
    assert env.panel.post("/panel/api/record/start", headers=PANEL).status_code == 200
    assert env.store.record_path != ""
    assert [e.type for e in env.store.events if e.type.startswith("recording_")] == [
        "recording_stopped", "recording_started"]
    env.store.flush_student_logs()
    text = next(env.store.dir_alerts.glob("2021000001_*.csv")).read_text(encoding="utf-8-sig")
    assert text.count("sınav;Ekran kaydı durduruldu") == 1 and "sınav;Ekran kaydı sınav sürerken başlatıldı" in text


def test_ending_the_exam_ends_the_recording(env: Env):
    """Students who have not handed in stay connected and are still shown in the panel after the
    end; their screens are no longer recorded."""
    client, _ = env.login()
    env.choose_folder()
    env.upload_exam()
    env.panel.post("/panel/api/start", headers=PANEL, json={"record": True})
    assert env.store.record_path != ""

    env.panel.post("/panel/api/end", headers=PANEL)
    state = env.panel.get("/panel/api/state").json()
    assert env.store.record_path == "" and state["exam"]["record"] is False
    assert env.snapshot_student("2021000001")["status"] == "nosubmit"       # still in the panel, not recorded
    assert env.store.events[-1].message == "Sınav bitirildi — ekran kaydı durduruldu"
    # Recording belongs to the running exam: it cannot be switched on (or off) afterwards.
    after = env.panel.post("/panel/api/record/start", headers=PANEL)
    assert after.status_code == 409 and "Sınav bitti" in after.json()["error"]
    assert env.panel.post("/panel/api/record/stop", headers=PANEL).status_code == 409
    assert env.store.record_path == ""
    text = next(env.store.dir_alerts.glob("2021000001_*.csv")).read_text(encoding="utf-8-sig")
    assert "sınav;Sınav bitirildi — ekran kaydı durduruldu" in text

    # An exam that ran without recording ends without a word about it; a state saved by an
    # older version (ended, recording still marked as on) records nothing either.
    env.panel.post("/panel/api/reset", headers=PANEL)
    env.choose_folder()
    env.upload_exam()
    env.panel.post("/panel/api/start", headers=PANEL, json={"record": False})
    env.panel.post("/panel/api/end", headers=PANEL)
    assert [e.message for e in env.store.events if e.type == "exam_ended"][-1] == "Sınav bitirildi"
    env.store.record_enabled = True
    assert env.store.record_path == "" and env.store.snapshot()["exam"]["record"] is False


# ------------------------------------------------------- what is a warning and what is not


def test_programs_that_were_open_before_the_exam_are_closed_without_a_warning(env: Env):
    """At the start of an exam nearly every student has a browser open. Closing those is what
    is expected; a warning for each would bury the ones that matter."""
    client, _ = env.login()
    env.start()
    client.post("/api/event", json={"type": "enforcement_started", "details": {}, "ts": 1000.0})
    # Started before the exam began for this student (by the student computer's own clock).
    client.post("/api/event", json={"type": "process_killed", "ts": 1001.0,
                                    "details": {"name": "chrome.exe", "title": "Yeni Sekme", "started": 400.0}})
    st = env.snapshot_student("2021000001")
    assert (st["status"], st["warn_count"]) == ("ok", 0) and not env.alerts("process_killed")
    event = [e for e in env.store.events if e.type == "process_killed"][-1]
    assert event.severity == "info" and event.details["before_exam"] is True
    assert event.message == "Sınav başlarken açık olan program kapatıldı: chrome.exe — pencere: “Yeni Sekme”"

    # Opened during the exam: that is a warning.
    client.post("/api/event", json={"type": "process_killed", "ts": 1300.0,
                                    "details": {"name": "chrome.exe", "started": 1290.0}})
    st = env.snapshot_student("2021000001")
    assert (st["status"], st["warn_count"]) == ("warn", 1)
    assert env.alerts("process_killed")[0]["message"] == "chrome.exe kapatıldı"

    # The student program was restarted in the middle of the exam: the exam still began at 1000.
    client.post("/api/event", json={"type": "enforcement_started", "details": {}, "ts": 2000.0})
    client.post("/api/event", json={"type": "process_killed", "ts": 2001.0,
                                    "details": {"name": "firefox.exe", "started": 1500.0}})
    assert env.snapshot_student("2021000001")["warn_count"] == 2
    # Nothing the student program says can switch the warning off; a program whose start is not
    # known counts as opened during the exam.
    client.post("/api/event", json={"type": "process_killed", "ts": 2002.0,
                                    "details": {"name": "opera.exe", "before_exam": True}})
    client.post("/api/event", json={"type": "process_killed", "ts": 2003.0, "details": {"name": "brave.exe"}})
    assert env.snapshot_student("2021000001")["warn_count"] == 4
    # Both kinds are in the student's own file.
    env.store.flush_student_logs()
    text = next(env.store.dir_alerts.glob("2021000001_*.csv")).read_text(encoding="utf-8-sig")
    assert "bilgi;Sınav başlarken açık olan program kapatıldı: chrome.exe" in text and "UYARI;chrome.exe kapatıldı" in text


def test_a_window_that_stays_in_front_is_one_warning_until_it_was_seen(env: Env):
    client, _ = env.login()
    env.start()
    foreign = {"type": "foreign_foreground", "details": {"name": "explorer.exe", "title": "Belgeler", "seconds": 6}}
    client.post("/api/event", json=foreign)
    assert env.snapshot_student("2021000001")["warn_count"] == 1
    # The student program repeats it every 30 seconds while the window stays in front.
    for seconds in (36, 66):
        client.post("/api/event", json={"type": "foreign_foreground",
                                        "details": {"name": "explorer.exe", "title": "Belgeler", "seconds": seconds}})
    assert env.snapshot_student("2021000001")["warn_count"] == 1 and len(env.alerts("foreign_foreground")) == 1
    assert [e.message for e in env.store.events if e.type == "foreign_foreground"][-1] == \
        "Packet Tracer dışındaki pencere hâlâ önde: explorer.exe (66 sn) — pencere: “Belgeler”"

    # Marked as seen, and the window is still in front: that is worth a new warning.
    env.panel.post("/panel/api/ack", headers=PANEL, json={"numara": "2021000001"})
    client.post("/api/event", json={"type": "foreign_foreground",
                                    "details": {"name": "explorer.exe", "title": "Belgeler", "seconds": 96}})
    assert env.snapshot_student("2021000001")["warn_count"] == 1 and len(env.alerts("foreign_foreground")) == 2

    # Another program in front, or the same one again after Packet Tracer was back: new warnings.
    client.post("/api/event", json={"type": "foreign_foreground", "details": {"name": "winver.exe", "seconds": 6}})
    assert env.snapshot_student("2021000001")["warn_count"] == 2
    client.post("/api/event", json={"type": "foreground_restored", "details": {"seconds": 20}})
    client.post("/api/event", json={"type": "foreign_foreground", "details": {"name": "winver.exe", "seconds": 6}})
    assert env.snapshot_student("2021000001")["warn_count"] == 3


def test_a_short_break_in_the_connection_is_not_a_warning_a_long_one_is(env: Env):
    client, _ = env.login()
    env.start()
    store = env.store
    st = store.students["2021000001"]

    def lose_and_return(seconds: float):
        st.last_hb_mono -= env.cfg.disconnect_s + 1
        store.tick()
        assert env.snapshot_student("2021000001")["status"] == "lost"
        st.lost_since_ts -= seconds
        client.post("/api/heartbeat", json={})
        store.tick()

    lose_and_return(20)
    snapshot = env.snapshot_student("2021000001")
    assert (snapshot["status"], snapshot["warn_count"]) == ("ok", 0)
    assert [e.type for e in store.events if e.numara and e.type in ("disconnected", "connection_restored", "long_outage")] == \
        ["disconnected", "connection_restored"]

    lose_and_return(200)
    snapshot = env.snapshot_student("2021000001")
    assert (snapshot["status"], snapshot["warn_count"]) == ("warn", 1)
    assert env.alerts("long_outage")[0]["message"] == "Bağlantı 3 dk 20 sn kesik kaldı; yeniden kuruldu"


def test_warnings_without_a_student_are_marked_as_seen_on_their_own(env: Env):
    client, _ = env.login()
    env.start()
    client.post("/api/event", json={"type": "process_killed", "details": {"name": "chrome.exe"}})
    env.store.add_event("", "unknown_submission_file", "warning", "Teslimler klasöründe tanınmayan dosya: x.pka")
    state = env.panel.get("/panel/api/state").json()
    general = [a for a in state["alerts"] if not a["numara"] and a["severity"] != "info"]
    assert general and general[0]["id"] > state["general_ack_id"]

    assert env.panel.post("/panel/api/ack", headers=PANEL, json={"general": True}).json() == {"ok": True, "count": 0}
    state = env.panel.get("/panel/api/state").json()
    assert general[0]["id"] <= state["general_ack_id"]
    assert env.snapshot_student("2021000001")["warn_count"] == 1      # the student's own warning is untouched


def test_how_students_are_named_in_the_panel_is_a_setting(env: Env):
    assert env.panel.get("/panel/api/state").json()["student_label"] == "name"
    for mode in ("number", "both", "name"):
        saved = env.panel.post("/panel/api/settings", headers=PANEL, json={"student_label": mode})
        assert saved.status_code == 200 and saved.json()["values"]["student_label"] == mode
        assert env.panel.get("/panel/api/state").json()["student_label"] == mode
    bad = env.panel.post("/panel/api/settings", headers=PANEL, json={"student_label": "initials"})
    assert bad.status_code == 422 and "Öğrenci gösterimi" in bad.json()["error"]
    # Kept for the next start, like the other settings.
    env.panel.post("/panel/api/settings", headers=PANEL, json={"student_label": "both"})
    restored = Store(load_config(env.cfg.path))
    restored.load_settings()
    assert restored.snapshot()["student_label"] == "both"


def test_recording_can_be_started_while_the_exam_runs(env: Env):
    client, _ = env.login()
    env.choose_folder()
    env.upload_exam()
    # Not before the exam: that is what "Ekranları kaydet" in the start window is for.
    early = env.panel.post("/panel/api/record/start", headers=PANEL)
    assert early.status_code == 409 and "Sınav başlamadı" in early.json()["error"]

    env.panel.post("/panel/api/start", headers=PANEL, json={"record": False})
    assert env.store.record_path == "" and env.panel.get("/panel/api/state").json()["exam"]["record"] is False

    started = env.panel.post("/panel/api/record/start", headers=PANEL)
    assert started.status_code == 200 and started.json() == {"record": True}
    assert env.store.record_path == str(env.exam_dir.resolve() / "Kayıtlar" / "%path" / "%Y-%m-%d_%H-%M-%S_%z")
    assert env.panel.get("/panel/api/state").json()["exam"]["record"] is True
    assert [e.message for e in env.store.events if e.type == "recording_started"] == \
        ["Ekran kaydı sınav sürerken başlatıldı"]
    # Written into every student's own log, too.
    env.store.flush_student_logs()
    assert "sınav;Ekran kaydı sınav sürerken başlatıldı" in \
        next(env.store.dir_alerts.glob("2021000001_*.csv")).read_text(encoding="utf-8-sig")

    again = env.panel.post("/panel/api/record/start", headers=PANEL)
    assert again.status_code == 409 and "zaten açık" in again.json()["error"]
    assert env.student().post("/panel/api/record/start", headers=PANEL).status_code == 403
    # The choice survives a restart of the system.
    env.store.save()
    restored = Store(env.cfg)
    restored.load()
    assert restored.record_enabled is True


def test_example_list_file_can_be_downloaded_and_uploaded_as_it_is(env: Env):
    response = env.panel.get("/panel/api/roster/template.xlsx")
    assert response.status_code == 200
    assert 'filename="ogrenci-listesi-ornek.xlsx"' in response.headers["content-disposition"]
    assert env.student().get("/panel/api/roster/template.xlsx").status_code == 403
    uploaded = env.panel.post("/panel/api/roster", headers=PANEL,
                              files={"file": ("ogrenci-listesi-ornek.xlsx", response.content, "application/octet-stream")})
    assert uploaded.status_code == 200 and uploaded.json() == {"count": 2}
    assert [(e.numara, e.ad, e.soyad) for e in env.store.roster.values()] == \
        [("2021000001", "Ali", "Veli"), ("2021000002", "Ayşe", "Yılmaz")]
