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
from .folderdialog import DialogUnavailable, open_folder, pick_folder
from .mediamtx import fetch_streams, kick_publishers, set_recording
from .roster import RosterError, parse_roster
from .store import MAX_UPLOAD_BYTES, RUNNING, WAITING, ApiError, Store, Student

log = logging.getLogger("sinav")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
STATIC_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
LOCAL_HOSTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
AGENT_ZIP = "SinavAjan.zip"
MAX_JSON_BYTES = 64 * 1024
SSE_MIN_INTERVAL_S = 0.4
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
                    log.info("Ekran kaydı: %s", wanted or "kapalı (sınav klasörü seçilmedi)")
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
        tasks = [asyncio.create_task(ticker()), asyncio.create_task(poller())]
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
            raise ApiError(403, "Öğretmen paneli yalnızca öğretmen bilgisayarından (localhost) açılabilir.")
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
        auto = str(form.get("auto") or "").strip().lower() in ("1", "true", "evet", "yes")
        stale = str(form.get("stale") or "").strip().lower() in ("1", "true")
        return store.submit(st, filename, data, auto, str(form.get("sha256") or ""), stale,
                            str(form.get("original_name") or ""))

    # ============================================================ panel pages

    @app.get("/")
    async def root(request: Request) -> Response:
        if is_local(request):
            return RedirectResponse("/panel")
        return HTMLResponse(student_page(cfg), headers=NO_STORE)

    @app.get(f"/indir/{AGENT_ZIP}")
    async def download_agent() -> Response:
        path = cfg.dir_dist / AGENT_ZIP
        if not path.is_file():
            raise ApiError(404, "Ajan paketi bu sunucuya konmamış. Öğretmeninizden isteyin.")
        return FileResponse(path, filename=AGENT_ZIP, media_type="application/zip")

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
            try:
                while True:
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
        store.reset()
        return {"state": store.state}

    @app.post("/panel/api/ack", dependencies=[Depends(local_only)])
    async def panel_ack(request: Request) -> dict[str, Any]:
        body = await json_body(request)
        numara = body.get("numara")
        store.ack(str(numara) if numara else None)
        return {"ok": True}

    return app


def student_page(cfg: Config) -> str:
    """Small landing page for students who open the server address in a browser."""
    has_zip = (cfg.dir_dist / AGENT_ZIP).is_file()
    download = (
        f'<p><a class="btn" href="/indir/{AGENT_ZIP}">Sınav ajanını indir ({AGENT_ZIP})</a></p>'
        "<ol><li>İndirdiğiniz zip dosyasına sağ tıklayıp <b>Tümünü ayıkla</b> deyin.</li>"
        "<li>Açılan klasörde <b>SinavAjan.exe</b> dosyasına sağ tıklayın → "
        "<b>Yönetici olarak çalıştır</b>.</li>"
        "<li>Ekranda bu sınıfın ve öğretmenin adını görünce <b>Doğru</b> deyip giriş yapın.</li></ol>"
        if has_zip
        else "<p>Sınav ajanı bu adresten dağıtılmıyor. Ajanı öğretmeninizden alın.</p>"
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
<p class="sub">Öğretmen: {html.escape(cfg.ogretmen_adi)}</p>
{download}
</body></html>"""
