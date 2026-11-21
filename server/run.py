"""Starts the exam server.

    python server/run.py [--config server/config.yaml]     (from a console; see start-teacher.bat)
    pythonw server/run.py --app                            (the installed application's shortcut)
    pythonw server/run.py --stop                           (setup: close the running copy first)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

MIN_PYTHON = (3, 11)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sınav İzleme Sistemi — sunucu")
    parser.add_argument("--config", default=None, help="config.yaml yolu")
    parser.add_argument("--host", default="0.0.0.0",
                        help="dinlenecek adres (varsayılan: tüm ağ arayüzleri)")
    parser.add_argument("--open-panel", action="store_true",
                        help="sunucu başlayınca paneli aç")
    parser.add_argument("--app", action="store_true",
                        help="kurulu uygulama kipi: tek kopya çalışır, MediaMTX'i kendisi başlatır, "
                             "veriler %%LOCALAPPDATA%%\\SinavIzleme altında durur, panel açılır")
    parser.add_argument("--stop", action="store_true",
                        help="bu bilgisayarda çalışan kopyayı kapat ve çık (kurulum/kaldırma için)")
    args = parser.parse_args()

    from sinav import desktopapp

    home = None
    if args.app:
        home = desktopapp.home_dir()
        (home / "data").mkdir(parents=True, exist_ok=True)
        desktopapp.redirect_output(home)

    def fail(text: str, code: int) -> int:
        if args.app:
            desktopapp.show_error(text)
        else:
            print(text)
        return code

    if sys.version_info < MIN_PYTHON:
        return fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} veya daha yenisi gerekli "
                    f"(bulunan: {sys.version.split()[0]}).", 2)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # never crash on console encoding
        except (AttributeError, ValueError):
            pass

    try:
        import uvicorn

        from sinav.app import create_app
        from sinav.config import ConfigError, load_config
        from sinav.discovery import lan_ips
    except ImportError as exc:
        return fail(f"Gerekli Python paketleri kurulu değil: {exc}\n"
                    "Kurulum (internet varken):  pip install -r server/requirements.txt", 2)

    config_path = args.config or str(HERE / "config.yaml")
    if home is not None and not args.config and (home / "config.yaml").is_file():
        config_path = str(home / "config.yaml")  # the user's own copy of the settings
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        return fail(f"AYAR HATASI: {exc}", 2)

    if args.stop:
        return 0 if desktopapp.stop_running(cfg.port) else 1

    media = None
    if home is not None:
        cfg.dir_data = home / "data"
        if not desktopapp.claim_single_instance():
            # The icon was clicked again. If the system is running, show its panel again; if
            # the first copy is still starting, it will open the panel itself in a moment.
            if desktopapp.probe(cfg.port) == "ours":
                print("Sistem zaten çalışıyor; panel penceresi yeniden açılıyor.")
                desktopapp.show_running_panel(cfg.port)
            else:
                print("Sistem zaten açılıyor; ikinci kopya başlatılmadı.")
            return 0
        owner = desktopapp.probe(cfg.port)
        if owner == "ours":
            print("Sistem zaten çalışıyor; panel penceresi yeniden açılıyor.")
            desktopapp.show_running_panel(cfg.port)
            return 0
        if owner == "other":
            return fail(f"{cfg.port} numaralı bağlantı noktasını başka bir program kullanıyor. "
                        "O programı kapatıp yeniden deneyin.", 1)
        name = "mediamtx.exe" if sys.platform == "win32" else "mediamtx"
        media = desktopapp.MediaServer(HERE.parent / "mediamtx" / name,
                                       HERE.parent / "mediamtx" / "mediamtx.yml", home)
        try:
            media.start()
        except OSError as exc:
            return fail(f"Ekran aktarımı bileşeni (MediaMTX) başlatılamadı: {exc}\n"
                        "Programı yeniden kurmayı deneyin.", 1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    app = create_app(cfg)
    app.state.open_panel = args.open_panel or args.app

    ips = lan_ips()
    print("=" * 66)
    print(f"  Sınıf: {cfg.sinif_adi}   {cfg.ogretmen_adi}")
    print(f"  Panel           : http://localhost:{cfg.port}/panel  (yalnızca bu bilgisayar)")
    if ips:
        for ip in ips:
            print(f"  Öğrenci adresi  : http://{ip}:{cfg.port}/   (elle IP girişi için: {ip})")
    else:
        print("  UYARI: Ağ bağlantısı bulunamadı. Sınıf modemine bağlı mısınız?")
    print(f"  Keşif           : UDP {cfg.discovery_port}    Ekran yayını: RTSP TCP {cfg.rtsp_port}")
    print("  Kapatmak için panel penceresini kapatın (ya da bu pencerede Ctrl+C)")
    print("=" * 66)

    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=cfg.port, access_log=False,
                                           log_level="warning", timeout_graceful_shutdown=2))
    # "Sistemi kapat" in the panel (or in the question shown after the panel window was
    # closed) stops the web server through this.
    app.state.stop_server = lambda: setattr(server, "should_exit", True)
    try:
        server.run()
    except (OSError, SystemExit) as exc:
        # uvicorn leaves through SystemExit when it cannot listen on the port.
        if media is not None and desktopapp.probe(cfg.port) == "ours":
            # Started twice at the same moment: the other copy won; show its panel.
            desktopapp.show_running_panel(cfg.port)
            return 0
        return fail(f"Sunucu başlatılamadı ({cfg.port} numaralı bağlantı noktası kullanımda "
                    f"olabilir): {exc}", 1)
    except Exception as exc:  # noqa: BLE001 - last resort: tell the user instead of vanishing
        logging.exception("Sunucu beklenmedik biçimde durdu")
        return fail(f"Sistem beklenmedik bir hatayla kapandı: {exc}", 1)
    finally:
        if media is not None:
            media.stop()
    if app.state.exit_code:
        print("Sistem kapatıldı.")
    return int(app.state.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
