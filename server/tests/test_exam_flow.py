"""End-to-end behaviour of the server through its HTTP API (no MediaMTX, no real agents)."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import time

from conftest import EXAM_BYTES, PANEL, Env
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
    _, body = env.login(numara="2021001")
    assert body["exam_state"] == WAITING
    assert body["stream"]["url"] == "rtsp://192.168.1.10:8554/2021001"
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
                     "version": 1, "size": len(work_a), "verified": True, "late": False}
    folder = env.submissions
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
    assert env.submit(c, EXAM_BYTES).status_code == 200
    unchanged = env.alerts("unchanged_submission")
    assert [u["numara"] for u in unchanged] == ["2021003"]
    assert len(env.alerts("duplicate_hash")) == 2

    rows = list(csv.reader(io.StringIO((folder / "index.csv").read_text(encoding="utf-8-sig")), delimiter=";"))
    assert rows[0][:6] == ["zaman", "numara", "ad", "soyad", "dosya", "sha256"]
    assert [r[4] for r in rows[1:]] == ["2021001_AhmetSahinCakir.pka", "2021001_AhmetSahinCakir_v2.pka",
                                         "2021002_IsilOzturk.pka", "2021003_CanEr.pka"]
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
    a, _ = env.login(numara="2021001", mac="AA:BB:CC:00:00:01")
    env.login(numara="2021002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    env.start()
    assert env.submit(a, b"son kayit").status_code == 200
    env.panel.post("/panel/api/end", headers=PANEL)
    # Nothing is ever handed in automatically: who did not hand in has no file.
    assert not any(e.type == "auto_submit" for e in env.store.events)
    assert [p.name for p in env.submissions.glob("*.pka")] == ["2021001_AliVeli.pka"]
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

    assert env.snapshot_student("2021001")["ack_id"] == 0
    assert env.panel.post("/panel/api/ack", headers=PANEL, json={"numara": "2021001"}).status_code == 200
    st = env.snapshot_student("2021001")
    assert st["status"] == "ok" and st["ack_id"] == env.store.events[-1].id  # everything so far is seen
    assert env.store.general_ack_id == 0
    event("process_killed", name="discord.exe")
    newest = env.store.snapshot()["alerts"][0]
    assert newest["id"] > st["ack_id"] and env.snapshot_student("2021001")["warn_count"] == 1
    assert env.panel.post("/panel/api/ack", headers=PANEL, json={}).status_code == 200  # everything
    assert env.snapshot_student("2021001")["ack_id"] == newest["id"] == env.store.general_ack_id

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

    store.apply_streams({"2021001"}, {"2021001": "192.168.1.50"})
    store.tick()
    assert env.snapshot_student("2021001")["status"] == "ok"

    # A stream from another address than the login is flagged once.
    store.apply_streams({"2021001"}, {"2021001": "192.168.1.99"})
    store.apply_streams({"2021001"}, {"2021001": "192.168.1.99"})
    assert len(env.alerts("stream_ip_mismatch")) == 1
    store.apply_streams({"777"}, {"777": "192.168.1.98"})
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
    env.start()
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
    assert restored.exam_dir == env.exam_dir.resolve() and restored.record_path == env.store.record_path


def test_new_exam_keeps_every_file_of_the_finished_one(env: Env):
    upload_roster(env, [[2021001, "Ali", "Veli"]])
    client, _ = env.login()
    env.start()
    env.submit(client, b"cozum")
    env.panel.post("/panel/api/end", headers=PANEL)

    response = env.panel.post("/panel/api/reset", headers=PANEL)
    assert response.status_code == 200 and response.json() == {"state": WAITING}

    # Nothing in the exam folder is moved or deleted; the event log is written next to it.
    assert (env.submissions / "2021001_AliVeli.pka").read_bytes() == b"cozum"
    assert (env.submissions / "index.csv").exists()
    log_text = (env.exam_dir / "olay-kaydi.csv").read_text(encoding="utf-8-sig")
    assert "Teslim etti: 2021001_AliVeli.pka" in log_text and "Sınav bitirildi" in log_text
    assert len(list((env.cfg.dir_data / "arsiv").glob("olaylar_*.jsonl"))) == 1

    snapshot = env.store.snapshot()
    assert snapshot["exam"]["state"] == WAITING and snapshot["exam"]["file"] is None
    assert snapshot["exam"]["folder"] == ""  # the next exam gets its own folder
    assert snapshot["students"] == [] and snapshot["roster"]["count"] == 1  # roster is kept
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
    assert env.snapshot_student("2021001")["status"] == "done"
    assert client.post("/api/heartbeat", json={}).json()["submitted"] is True
    assert not env.alerts()

    # The file disappears from the folder: the student is no longer "teslim etti".
    (env.submissions / name).rename(env.tmp_path / "kenarda.pka")
    env.store.check_submission_folder()
    env.store.check_submission_folder()
    assert env.snapshot_student("2021001")["status"] == "nofile"
    missing = env.alerts("submission_missing")
    assert len(missing) == 1 and missing[0]["severity"] == "critical" and name in missing[0]["message"]
    assert client.post("/api/heartbeat", json={}).json()["submitted"] is False
    assert env.store.snapshot()["summary"]["submitted"] == 0

    (env.tmp_path / "kenarda.pka").rename(env.submissions / name)
    env.store.check_submission_folder()
    assert env.snapshot_student("2021001")["status"] == "done"


def test_file_put_into_the_folder_by_hand_counts_as_submission(env: Env):
    # A file that was in the folder before the exam is never taken as a submission.
    env.choose_folder()
    (env.submissions / "2021001_Eski.pka").write_bytes(b"gecen yilin dosyasi")
    client, _ = env.login()
    env.login(numara="2021002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    env.start()
    env.store.check_submission_folder()
    assert env.snapshot_student("2021001")["status"] == "ok"

    # The teacher copies a student's file from a USB stick.
    old = time.time() - 10
    by_hand = env.submissions / "2021002_usbden.pka"
    by_hand.write_bytes(EXAM_BYTES + b"-usb")
    env.store.check_submission_folder()
    assert env.snapshot_student("2021002")["status"] == "ok"  # just written: may still be copying
    os.utime(by_hand, (old, old))
    env.store.check_submission_folder()
    env.store.check_submission_folder()
    st = env.snapshot_student("2021002")
    assert st["status"] == "done" and st["submission"]["filename"] == "2021002_usbden.pka"
    assert st["submission_count"] == 1
    assert any("klasörde bulundu" in e.message for e in env.store.events)
    assert "2021002_usbden.pka" in (env.submissions / "index.csv").read_text(encoding="utf-8-sig")

    # A file that belongs to nobody is reported once and otherwise left alone.
    stray = env.submissions / "kimin-bu.pka"
    stray.write_bytes(b"x")
    os.utime(stray, (old, old))
    env.store.check_submission_folder()
    env.store.check_submission_folder()
    assert len(env.alerts("unknown_submission_file")) == 1 and stray.exists()
    assert client.post("/api/heartbeat", json={}).json()["submitted"] is False


def test_submitted_file_is_verified(env: Env):
    a, _ = env.login(numara="2021001", mac="AA:BB:CC:00:00:01")
    b, _ = env.login(numara="2021002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    c, _ = env.login(numara="2021003", ad="Ece", soyad="Su", mac="AA:BB:CC:00:00:03", ip="192.168.1.52")
    env.start()

    # The agent sends the hash of the file it read; a damaged upload is refused.
    work = EXAM_BYTES + b"-cozum"
    broken = env.submit(a, work, sha256=hashlib.sha256(b"baska").hexdigest())
    assert broken.status_code == 400 and "bozuldu" in broken.json()["error"]
    assert not list(env.submissions.glob("*.pka")) and env.snapshot_student("2021001")["status"] == "ok"
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
    assert env.snapshot_student("2021002")["warn_count"] == 1

    # A file of a very different size, saved before the exam file was downloaded.
    assert env.submit(c, b"minik", stale="true").status_code == 200
    assert "yanlış dosya olabilir" in env.alerts("suspicious_size")[0]["message"]
    assert "indirilmeden önce" in env.alerts("stale_submission")[0]["message"]

    # The streams of students whose file has arrived are stopped.
    env.store.apply_streams({"2021001", "2021002", "777"}, {})
    assert sorted(env.store.streams_to_stop()) == ["2021001", "2021002"]


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
    assert env.snapshot_student("2021001")["status"] == "warn"


# ------------------------------------------------------ class and teacher name


def test_class_and_teacher_name_are_changed_in_the_panel(env: Env):
    response = env.panel.post("/panel/api/identity", headers=PANEL,
                              json={"sinif_adi": "  Lab  3 ", "ogretmen_adi": "Dr. Işıl Öz"})
    assert response.json() == {"sinif_adi": "Lab 3", "ogretmen_adi": "Dr. Işıl Öz"}
    info = env.student().get("/api/info").json()
    assert (info["sinif_adi"], info["ogretmen_adi"]) == ("Lab 3", "Dr. Işıl Öz")
    assert env.store.snapshot()["class"] == {"sinif_adi": "Lab 3", "ogretmen_adi": "Dr. Işıl Öz"}
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
    on_time, _ = env.login(numara="2021001", mac="AA:BB:CC:00:00:01")
    late, _ = env.login(numara="2021002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    env.start()
    assert env.submit(on_time, EXAM_BYTES + b"-1").json()["late"] is False
    env.panel.post("/panel/api/end", headers=PANEL)

    # The exam is over, but nobody is thrown out: the student is told the exam has ended ...
    hb = late.post("/api/heartbeat", json={}).json()
    assert hb["exam_state"] == ENDED and hb["submitted"] is False
    assert late.get("/api/exam-file").status_code == 409  # ... the file can no longer be downloaded ...
    assert env.snapshot_student("2021002")["status"] == "nosubmit"

    # ... and a file handed in now is accepted and marked as late.
    env.store.ended_at -= 4 * 60
    result = env.submit(late, EXAM_BYTES + b"-2")
    assert result.status_code == 200 and result.json()["late"] is True
    st = env.snapshot_student("2021002")
    assert st["status"] == "done" and st["submission"]["late"] is True
    alert = env.alerts("late_submission")
    assert len(alert) == 1 and alert[0]["numara"] == "2021002" and alert[0]["severity"] == "warning"
    assert alert[0]["message"] == "Geç teslim: dosyasını sınav bittikten 4 dakika sonra teslim etti"
    assert any(e.message.startswith("Geç teslim etti: 2021002_CanEr.pka") for e in env.store.events)
    rows = list(csv.reader(io.StringIO((env.submissions / "index.csv").read_text(encoding="utf-8-sig")),
                           delimiter=";"))
    assert rows[0][7] == "gec_teslim" and [r[7] for r in rows[1:]] == ["hayır", "evet"]


def test_a_file_that_was_already_on_its_way_is_not_late(env: Env):
    client, _ = env.login()
    env.start()
    env.panel.post("/panel/api/end", headers=PANEL)
    assert env.submit(client, EXAM_BYTES + b"-son-saniye").json()["late"] is False
    assert not env.alerts("late_submission")


def test_warnings_are_kept_in_one_file_per_student(env: Env):
    a, _ = env.login(numara="2021001", ad="Ahmet Şahin", soyad="Çakır", mac="AA:BB:CC:00:00:01")
    b, _ = env.login(numara="2021002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
    # A warning from before the exam folder was chosen ...
    a.post("/api/event", json={"type": "monitor_change", "details": {"count": 2, "previous": 1}})
    env.start()
    folder = env.exam_dir / "Uyarılar"
    assert env.store.snapshot()["paths"]["alerts"] == str(folder.resolve())
    # ... is written as soon as the folder exists.
    path = folder / "2021001_AhmetSahinCakir.csv"
    assert "Monitör sayısı: 2 (önceki: 1)" in path.read_text(encoding="utf-8-sig")

    a.post("/api/event", json={"type": "process_killed", "details": {"name": "chrome.exe"}})
    a.post("/api/event", json={"type": "foreground_change", "details": {"name": "PacketTracer.exe"}})  # not a warning
    a.post("/api/event", json={"type": "desktop_switch", "details": {}})
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig")), delimiter=";"))
    assert rows[0] == ["zaman", "numara", "ad_soyad", "onem", "uyari"]
    assert [r[4] for r in rows[1:]] == ["Monitör sayısı: 2 (önceki: 1)", "chrome.exe kapatıldı",
                                        "Başka bir masaüstüne geçti"]
    assert all(r[1] == "2021001" and r[2] == "Ahmet Şahin Çakır" and r[3] == "uyarı" for r in rows[1:])
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # opens correctly in Excel

    # A student without warnings has no file; a late submission is a warning like any other.
    assert not list(folder.glob("2021002_*"))
    env.panel.post("/panel/api/end", headers=PANEL)
    env.store.ended_at -= 120
    env.submit(b, EXAM_BYTES + b"-gec")
    assert "Geç teslim" in (folder / "2021002_CanEr.csv").read_text(encoding="utf-8-sig")

    # The files stay in the exam folder when a new exam is prepared.
    env.panel.post("/panel/api/reset", headers=PANEL)
    assert path.exists() and (folder / "2021002_CanEr.csv").exists()


def test_warning_file_follows_the_name_in_the_student_list(env: Env):
    client, _ = env.login(numara="2021001", ad="Ali", soyad="Veli")
    env.start()
    client.post("/api/event", json={"type": "process_killed", "details": {"name": "chrome.exe"}})
    folder = env.exam_dir / "Uyarılar"
    assert (folder / "2021001_AliVeli.csv").exists()
    upload_roster(env, [[2021001, "Ali Rıza", "Veli"]])
    assert [p.name for p in folder.iterdir()] == ["2021001_AliRizaVeli.csv"]
    assert "Ad uyuşmuyor" in (folder / "2021001_AliRizaVeli.csv").read_text(encoding="utf-8-sig")


def test_new_exam_closes_the_student_programs_that_are_still_open(env: Env):
    client, _ = env.login()
    env.start()
    env.panel.post("/panel/api/end", headers=PANEL)
    assert [st.numara for st in env.store.open_agents()] == ["2021001"]

    # While the exam is being closed, agents are told so and exit. Nothing is collected
    # automatically: a student who did not hand in has no file.
    env.store.closing = True
    hb = client.post("/api/heartbeat", json={}).json()
    assert hb["exam_state"] == CLOSED and env.store.students["2021001"].closed_seen
    env.store.closing = False

    assert env.panel.post("/panel/api/reset", headers=PANEL).json() == {"state": WAITING}
    assert env.store.closing is False and env.store.students == {}
    assert not list(env.submissions.glob("*.pka"))


def test_shutting_the_system_down_ends_the_exam_and_stops_the_server(env: Env):
    stopped = []
    env.app.state.stop_server = lambda: stopped.append(True)
    env.login()
    env.store.students["2021001"].last_hb_mono -= 60  # that program is gone: nothing to wait for
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
    env.login(numara="2021002", ad="Can", soyad="Er", mac="AA:BB:CC:00:00:02", ip="192.168.1.51")
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
