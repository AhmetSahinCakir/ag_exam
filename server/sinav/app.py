"""FastAPI application: student (agent) API on the LAN, teacher panel on localhost."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse

from . import __version__
from .config import Config, ConfigError, reload_policy
from .discovery import DiscoveryResponder, lan_ips
from .folderdialog import DialogUnavailable, open_folder, open_in_editor, open_panel_window, pick_folder
from .mediamtx import fetch_streams, kick_publishers, set_recording
from .roster import RosterError, parse_roster
from .store import MAX_UPLOAD_BYTES, RUNNING, WAITING, ApiError, Store, Student

log = logging.getLogger("sinav")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
STATIC_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".ico": "image/x-icon"}
LOCAL_HOSTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
# The student program is one file; put it into the "dagitim" folder to hand it out over the
# classroom network.
AGENT_FILE = "SinavAjan.exe"
MAX_JSON_BYTES = 64 * 1024
SSE_MIN_INTERVAL_S = 0.4
# Closing the exam for everybody: how long to wait until every open student program has
# been told (they ask every 2 s).
CLOSE_NOTICE_S = 7.0
# Exit code of run.py after "Sistemi kapat": the start script then closes its window.
EXIT_CLOSED_BY_TEACHER = 10
NO_STORE = {"Cache-Control": "no-store"}


def is_local(request: Request) -> bool:
    return request.client is not None and request.client.host in LOCAL_HOSTS


def create_app(cfg: Config) -> FastAPI:
    store = Store(cfg)
    store.load()
    store.load_settings()
    # Lets an agent recognise the same server when it answers on several network adapters.
    instance_id = secrets.token_hex(8)
    cached_ips: list[str] = lan_ips()
    dialog_open = False
    panel_clients = 0          # panel pages connected to the live stream
    panel_gone_since = 0.0     # monotonic time the last one disconnected; 0 = never seen / connected
    panel_gone_logged = False
    shutting_down = False
    panel_url = f"http://localhost:{cfg.port}/panel"

    def count_panel(delta: int) -> None:
        nonlocal panel_clients, panel_gone_since, panel_gone_logged
        panel_clients += delta
        store.panel_clients = panel_clients
        if delta > 0:
            if panel_gone_logged and not shutting_down:
                log.info("Panel yeniden açıldı; sistem çalışmaya devam ediyor.")
            panel_gone_since = 0.0
            panel_gone_logged = False
        elif panel_clients == 0:
            panel_gone_since = time.monotonic()

    async def open_panel_soon() -> None:
        await asyncio.sleep(1.0)
        await asyncio.to_thread(open_panel_window, panel_url, cfg.panel_as_app)

    # ------------------------------------------------------------ background

    async def ticker() -> None:
        nonlocal cached_ips
        count = 0
        while True:
            await asyncio.sleep(1)
            count += 1
            try:
                store.tick()
                if count % 2 == 0:
                    # A student counts as "teslim etti" only while the file is really in the folder.
                    store.check_submission_folder()
                    store.save_if_dirty()
                if count % 3 == 0:
                    try:
                        if reload_policy(cfg):
                            log.info("İzin listesi yeniden yüklendi (sürüm %s)", cfg.policy.version)
                            store.changed(persist=False)
                        if store.config_error:
                            store.config_error = ""
                            store.changed(persist=False)
                    except (ConfigError, OSError, ValueError) as exc:
                        message = f"config.yaml okunamadı, önceki izin listesi geçerli: {exc}"
                        if message != store.config_error:
                            store.config_error = message
                            store.changed(persist=False)
                if count % 10 == 0:
                    cached_ips = await asyncio.to_thread(lan_ips)
            except Exception:  # noqa: BLE001 - the monitor loop must never die
                log.exception("Arka plan denetiminde hata")

    async def poller() -> None:
        while True:
            try:
                ready, publishers = await asyncio.to_thread(fetch_streams, cfg.mediamtx_api)
                store.apply_streams(ready, publishers)
                # Recordings go into the exam folder the teacher chose (off until one is chosen).
                wanted = store.record_path
                if wanted != store.recording_applied:
                    await asyncio.to_thread(set_recording, cfg.mediamtx_api, wanted)
                    store.recording_applied = wanted
                    log.info("Ekran kaydı: %s", wanted or "kapalı")
            except Exception:  # noqa: BLE001 - MediaMTX not running / restarting
                store.mediamtx_down()
                store.recording_applied = None  # a restarted MediaMTX has forgotten the folder
            else:
                done = store.streams_to_stop()
                if done:
                    try:
                        await asyncio.to_thread(kick_publishers, cfg.mediamtx_api, done)
                    except Exception:  # noqa: BLE001 - tried again on the next pass
                        log.warning("Teslim eden öğrencinin yayını durdurulamadı: %s", ", ".join(done))
            await asyncio.sleep(2)

    async def close_agents() -> None:
        """Tell every student program that is still open that the exam is closed.

        The programs exit; nothing is handed in automatically. Waits until each of them has
        been told (they ask every 2 s).
        """
        waiting = store.open_agents()
        store.closing = True
        store.changed(persist=False)
        if not waiting:
            return
        log.info("Öğrenci programları kapatılıyor (%d açık)…", len(waiting))
        deadline = time.monotonic() + CLOSE_NOTICE_S
        while time.monotonic() < deadline and any(not st.closed_seen for st in store.open_agents()):
            await asyncio.sleep(0.25)

    async def shutdown_system(reason: str) -> None:
        """“Sistemi kapat”: close the exam for everybody, then stop this server."""
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        log.info("Sistem kapatılıyor (%s)…", reason)
        await close_agents()
        if store.state == RUNNING:
            store.end_exam()
        store.add_event("", "system_shutdown", "info", "Sistem kapatıldı")
        store.write_events_csv()
        store.write_all_student_alerts()
        app.state.exit_code = EXIT_CLOSED_BY_TEACHER
        stop = getattr(app.state, "stop_server", None)
        if stop is not None:
            stop()

    async def panel_watch() -> None:
        """Closing the panel window (the browser, or its tab) closes the system.

        Nothing is asked. A reload reconnects within a second and does not count. While student
        programs are connected the wait is longer (see Store.close_grace_s), so that an
        accidental close or a browser crash can be undone by opening the panel again.
        """
        nonlocal panel_gone_logged
        while True:
            await asyncio.sleep(0.25)
            if shutting_down or panel_clients > 0 or not panel_gone_since:
                continue
            gone = time.monotonic() - panel_gone_since
            grace = store.close_grace_s()
            if gone >= 1.5 and not panel_gone_logged:
                panel_gone_logged = True
                log.info("Panel penceresi kapandı. Sistem %d sn sonra kapanacak; vazgeçmek için paneli "
                         "yeniden açın.", max(0, round(grace - gone)))
            if gone >= grace:
                await shutdown_system("panel penceresi kapatıldı")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        responder = None
        try:
            responder = DiscoveryResponder(
                cfg.discovery_port,
                lambda: {"port": cfg.port, "sinif_adi": cfg.sinif_adi, "ogretmen_adi": cfg.ogretmen_adi,
                         "id": instance_id},
            )
            responder.start()
        except OSError as exc:
            store.discovery_error = (
                f"UDP {cfg.discovery_port} portu dinlenemiyor ({exc}). Ajanlar sunucuyu otomatik "
                "bulamaz; öğrenciler IP adresini elle girmelidir."
            )
            log.error(store.discovery_error)
        tasks = [asyncio.create_task(ticker()), asyncio.create_task(poller()),
                 asyncio.create_task(panel_watch())]
        if app.state.open_panel:
            tasks.append(asyncio.create_task(open_panel_soon()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            if responder is not None:
                responder.stop()
            try:
                store.save()
            except OSError as exc:
                log.error("Durum dosyası yazılamadı: %s", exc)

    app = FastAPI(title="Sınav İzleme Sistemi", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.store = store
    app.state.exit_code = 0
    app.state.stop_server = None  # set by run.py: stops the web server
    app.state.open_panel = False  # set by run.py --open-panel: show the panel window at start
    app.state.user_config = None  # set by run.py --app: where the user's own settings file goes

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"error": exc.message}, status_code=exc.status)

    # --------------------------------------------------------------- helpers

    async def json_body(request: Request) -> dict[str, Any]:
        length = request.headers.get("content-length", "0")
        if length.isdigit() and int(length) > MAX_JSON_BYTES:
            raise ApiError(413, "İstek çok büyük.")
        try:
            body = json.loads(await request.body() or b"{}")
        except ValueError as exc:
            raise ApiError(400, "Geçersiz istek gövdesi (JSON bekleniyor).") from exc
        if not isinstance(body, dict):
            raise ApiError(400, "Geçersiz istek gövdesi (JSON nesnesi bekleniyor).")
        return body

    async def read_upload(request: Request) -> tuple[str, bytes, Any]:
        """Read the multipart field "file"; enforces the 50 MB limit before parsing."""
        length = request.headers.get("content-length", "")
        if not length.isdigit():
            raise ApiError(411, "İstek boyutu (Content-Length) belirtilmemiş.")
        if int(length) > MAX_UPLOAD_BYTES + 1024 * 1024:
            raise ApiError(413, "Dosya çok büyük (en fazla 50 MB).")
        try:
            form = await request.form()
        except Exception as exc:  # noqa: BLE001 - malformed multipart
            raise ApiError(400, "Dosya yüklemesi okunamadı.") from exc
        upload = form.get("file")
        if upload is None or isinstance(upload, str):
            raise ApiError(400, "Dosya gönderilmedi.")
        data = await upload.read()
        return upload.filename or "", data, form

    def current_student(request: Request) -> Student:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise ApiError(401, "Oturum bilgisi eksik. Yeniden giriş yapın.")
        return store.auth(token.strip())

    def local_only(request: Request) -> None:
        if not is_local(request):
            raise ApiError(403, "Panel yalnızca sistemin çalıştığı bilgisayardan (localhost) açılabilir.")
        if request.method not in ("GET", "HEAD") and request.headers.get("x-panel") != "1":
            # Blocks cross-site form posts from other pages open in the teacher's browser.
            raise ApiError(403, "Geçersiz panel isteği.")

    # ============================================================ agent API

    @app.get("/api/info")
    async def api_info() -> dict[str, Any]:
        return {
            "sinif_adi": cfg.sinif_adi,
            "ogretmen_adi": cfg.ogretmen_adi,
            "exam_state": store.state,
            "server_version": __version__,
            "instance_id": instance_id,
            "retention_note": cfg.retention_note,
        }

    @app.post("/api/login")
    async def api_login(request: Request) -> dict[str, Any]:
        body = await json_body(request)
        ip = request.client.host if request.client else ""
        server_host = request.url.hostname or ""
        return store.login(body, ip, server_host)

    @app.post("/api/heartbeat")
    async def api_heartbeat(request: Request, st: Student = Depends(current_student)) -> dict[str, Any]:
        return store.heartbeat(st, await json_body(request))

    @app.post("/api/event")
    async def api_event(request: Request, st: Student = Depends(current_student)) -> dict[str, Any]:
        body = await json_body(request)
        store.agent_event(st, str(body.get("type") or ""), body.get("details"), body.get("ts"))
        return {"ok": True}

    @app.get("/api/config")
    async def api_config(_: Student = Depends(current_student)) -> dict[str, Any]:
        return {"allowlist": cfg.policy.to_agent(), "settings": store.agent_settings()}

    @app.get("/api/exam-file")
    async def api_exam_file(_: Student = Depends(current_student)) -> Response:
        if store.state == WAITING:
            raise ApiError(409, "Sınav henüz başlamadı.")
        if store.state != RUNNING:
            raise ApiError(409, "Sınav sona erdi.")
        if not store.exam_file or not store.exam_file_path.exists():
            raise ApiError(404, "Sınav dosyası sunucuda bulunamadı.")
        return FileResponse(store.exam_file_path, filename="sinav.pka",
                            media_type="application/octet-stream", headers=NO_STORE)

    @app.post("/api/submit")
    async def api_submit(request: Request, st: Student = Depends(current_student)) -> dict[str, Any]:
        filename, data, form = await read_upload(request)
        stale = str(form.get("stale") or "").strip().lower() in ("1", "true")
        return store.submit(st, filename, data, str(form.get("sha256") or ""), stale,
                            str(form.get("original_name") or ""))

    # ============================================================ panel pages

    @app.get("/")
    async def root(request: Request) -> Response:
        if is_local(request):
            return RedirectResponse("/panel")
        return HTMLResponse(student_page(cfg), headers=NO_STORE)

    @app.get(f"/indir/{AGENT_FILE}")
    async def download_agent() -> Response:
        path = cfg.dir_dist / AGENT_FILE
        if not path.is_file():
            raise ApiError(404, "Sınav programı bu adresten dağıtılmıyor.")
        return FileResponse(path, filename=AGENT_FILE, media_type="application/octet-stream")

    @app.get("/favicon.ico")
    async def favicon() -> Response:
        # The panel opens in a window of its own; this is its icon on the taskbar.
        return FileResponse(STATIC_DIR / "favicon.ico", media_type="image/x-icon")

    @app.get("/panel", dependencies=[Depends(local_only)])
    async def panel() -> Response:
        return FileResponse(STATIC_DIR / "panel.html", media_type="text/html; charset=utf-8", headers=NO_STORE)

    @app.get("/panel/static/{name}", dependencies=[Depends(local_only)])
    async def panel_static(name: str) -> Response:
        path = STATIC_DIR / name
        media_type = STATIC_TYPES.get(path.suffix)
        if "/" in name or "\\" in name or media_type is None or not path.is_file():
            raise ApiError(404, "Dosya bulunamadı.")
        return FileResponse(path, media_type=media_type, headers=NO_STORE)

    # ============================================================== panel API

    @app.get("/panel/api/stream", dependencies=[Depends(local_only)])
    async def panel_stream(request: Request) -> StreamingResponse:
        async def generate():
            waiter = store.subscribe()
            count_panel(+1)
            try:
                while True:
                    if shutting_down:
                        # Tell the page, and end the stream so that the server can stop at once.
                        yield "event: closed\ndata: {}\n\n"
                        break
                    payload = json.dumps(store.snapshot(cached_ips), ensure_ascii=False)
                    yield f"data: {payload}\n\n"
                    sent = time.monotonic()
                    try:
                        await asyncio.wait_for(waiter.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        pass
                    waiter.clear()
                    pause = SSE_MIN_INTERVAL_S - (time.monotonic() - sent)
                    if pause > 0:
                        await asyncio.sleep(pause)
                    if await request.is_disconnected():
                        break
            finally:
                store.unsubscribe(waiter)
                count_panel(-1)

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/panel/api/state", dependencies=[Depends(local_only)])
    async def panel_state() -> dict[str, Any]:
        """The same snapshot the live stream sends, as a single JSON document (for tools and tests)."""
        return store.snapshot(cached_ips)

    @app.get("/panel/api/events", dependencies=[Depends(local_only)])
    async def panel_events(numara: str = "") -> dict[str, Any]:
        return {"events": store.events_for(numara)}

    @app.get("/panel/api/export.csv", dependencies=[Depends(local_only)])
    async def panel_export() -> Response:
        name = time.strftime("olaylar_%Y-%m-%d_%H-%M.csv")
        return Response(store.export_csv(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"', **NO_STORE})

    @app.post("/panel/api/identity", dependencies=[Depends(local_only)])
    async def panel_identity(request: Request) -> dict[str, Any]:
        """Class (exam room) and teacher name, as shown to the students."""
        body = await json_body(request)
        store.set_identity(body.get("sinif_adi"), body.get("ogretmen_adi"))
        return {"sinif_adi": cfg.sinif_adi, "ogretmen_adi": cfg.ogretmen_adi}

    @app.post("/panel/api/pick-folder", dependencies=[Depends(local_only)])
    async def panel_pick_folder() -> dict[str, Any]:
        """Open the folder window of the operating system on this (the teacher's) computer."""
        nonlocal dialog_open
        if store.state != WAITING:
            raise ApiError(409, "Sınav klasörü yalnızca sınav başlamadan önce seçilebilir.")
        if dialog_open:
            raise ApiError(409, "Klasör seçme penceresi zaten açık (görev çubuğuna bakın).")
        dialog_open = True
        try:
            chosen = await asyncio.to_thread(pick_folder, str(store.exam_dir or ""))
        except DialogUnavailable as exc:
            raise ApiError(501, "Klasör seçme penceresi açılamadı. Klasörün yolunu elle yazın.") from exc
        finally:
            dialog_open = False
        if not chosen:
            return {"folder": "", "cancelled": True}
        return {"folder": str(store.set_exam_dir(chosen))}

    @app.post("/panel/api/exam-folder", dependencies=[Depends(local_only)])
    async def panel_exam_folder(request: Request) -> dict[str, Any]:
        body = await json_body(request)
        return {"folder": str(store.set_exam_dir(body.get("path")))}

    @app.post("/panel/api/open-folder", dependencies=[Depends(local_only)])
    async def panel_open_folder() -> dict[str, Any]:
        """Show the exam folder in the file manager of this (the teacher's) computer."""
        if store.exam_dir is None:
            raise ApiError(409, "Sınav klasörü seçilmedi.")
        try:
            open_folder(str(store.exam_dir))
        except OSError as exc:
            raise ApiError(501, f"Klasör açılamadı. Elle açın: {store.exam_dir}") from exc
        return {"folder": str(store.exam_dir)}

    @app.post("/panel/api/open-settings", dependencies=[Depends(local_only)])
    async def panel_open_settings() -> dict[str, Any]:
        """Open the settings file (allowed programs and so on) in the editor of this computer.

        The installed application keeps its own settings read-only under "Program Files"; the
        first time, a copy is made in the user's folder and that copy is used from then on.
        """
        own = getattr(app.state, "user_config", None)
        try:
            if own is not None and Path(own) != cfg.path:
                own = Path(own)
                if not own.is_file():
                    own.parent.mkdir(parents=True, exist_ok=True)
                    own.write_bytes(cfg.path.read_bytes())
                cfg.path = own
                cfg.mtime = own.stat().st_mtime
            open_in_editor(str(cfg.path))
        except OSError as exc:
            raise ApiError(501, f"Ayar dosyası açılamadı. Elle açın: {cfg.path}") from exc
        return {"file": str(cfg.path)}

    @app.post("/panel/api/exam-file", dependencies=[Depends(local_only)])
    async def panel_exam_file(request: Request) -> dict[str, Any]:
        filename, data, _ = await read_upload(request)
        return {"file": store.set_exam_file(filename, data)}

    @app.post("/panel/api/roster", dependencies=[Depends(local_only)])
    async def panel_roster(request: Request) -> dict[str, Any]:
        filename, data, _ = await read_upload(request)
        try:
            entries = parse_roster(data, filename)
        except RosterError as exc:
            raise ApiError(400, str(exc)) from exc
        return {"count": store.set_roster(entries, filename)}

    @app.post("/panel/api/start", dependencies=[Depends(local_only)])
    async def panel_start(request: Request) -> dict[str, Any]:
        """“Sınavı başlat”: now or at a planned time, with an optional time limit and recording choice.

        Starting the exam is what shares the exam file with the students.
        """
        body = await json_body(request)
        store.start_exam(body.get("duration_min"), body.get("record", True), body.get("start_at"))
        return {"state": store.state, "scheduled": store.scheduled}

    @app.post("/panel/api/cancel-start", dependencies=[Depends(local_only)])
    async def panel_cancel_start() -> dict[str, Any]:
        store.cancel_schedule()
        return {"state": store.state}

    @app.post("/panel/api/extend", dependencies=[Depends(local_only)])
    async def panel_extend(request: Request) -> dict[str, Any]:
        body = await json_body(request)
        return {"ends_at": store.extend_exam(body.get("minutes"))}

    @app.post("/panel/api/end", dependencies=[Depends(local_only)])
    async def panel_end() -> dict[str, Any]:
        store.end_exam()
        return {"state": store.state}

    @app.post("/panel/api/reset", dependencies=[Depends(local_only)])
    async def panel_reset() -> dict[str, Any]:
        """“Yeni sınav”: student programs that are still open hand in and close first."""
        if store.state == RUNNING:
            raise ApiError(409, "Sınav sürerken sıfırlanamaz. Önce sınavı bitirin.")
        await close_agents()
        store.reset()
        return {"state": store.state}

    @app.post("/panel/api/open-window", dependencies=[Depends(local_only)])
    async def panel_open_window() -> dict[str, Any]:
        """Show the panel window again (start-teacher.bat calls this when the system already runs)."""
        return {"window": await asyncio.to_thread(open_panel_window, panel_url, cfg.panel_as_app)}

    @app.post("/panel/api/shutdown", dependencies=[Depends(local_only)])
    async def panel_shutdown() -> dict[str, Any]:
        """“Sistemi kapat”: ends the exam, closes the student programs and stops the server."""
        asyncio.get_running_loop().create_task(shutdown_system("panelden"))
        return {"ok": True}

    @app.post("/panel/api/ack", dependencies=[Depends(local_only)])
    async def panel_ack(request: Request) -> dict[str, Any]:
        body = await json_body(request)
        numara = body.get("numara")
        store.ack(str(numara) if numara else None)
        return {"ok": True}

    return app


def student_page(cfg: Config) -> str:
    """Small landing page for students who open the server address in a browser."""
    has_file = (cfg.dir_dist / AGENT_FILE).is_file()
    download = (
        f'<p><a class="btn" href="/indir/{AGENT_FILE}">Sınav programını indir ({AGENT_FILE})</a></p>'
        "<ol><li>İndirdiğiniz <b>SinavAjan.exe</b> dosyasına çift tıklayın ve izin sorusuna "
        "<b>Evet</b> deyin.</li>"
        "<li>Ekranda bu sınıfın adını görünce <b>Doğru</b> deyip giriş yapın.</li></ol>"
        if has_file
        else "<p>Sınav programı bu adresten dağıtılmıyor.</p>"
    )
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sınav — {html.escape(cfg.sinif_adi)}</title>
<style>
 body{{font-family:Segoe UI,system-ui,sans-serif;max-width:640px;margin:48px auto;padding:0 16px;
      color:#1b1f24;line-height:1.5}}
 h1{{font-size:28px;margin-bottom:4px}} .sub{{color:#57606a;margin-top:0}}
 .btn{{display:inline-block;background:#1f6feb;color:#fff;padding:12px 18px;border-radius:8px;
      text-decoration:none;font-weight:600}}
 li{{margin:6px 0}}
</style></head><body>
<h1>Sınıf: {html.escape(cfg.sinif_adi)}</h1>
<p class="sub">{html.escape(cfg.ogretmen_adi)}</p>
{download}
</body></html>"""
