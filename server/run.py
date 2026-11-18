"""Starts the teacher server:  python server/run.py  [--config server/config.yaml]"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

MIN_PYTHON = (3, 11)


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        print(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} veya daha yenisi gerekli "
              f"(bulunan: {sys.version.split()[0]}).")
        return 2

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # never crash on console encoding
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Sınav İzleme Sistemi — öğretmen sunucusu")
    parser.add_argument("--config", default=str(HERE / "config.yaml"), help="config.yaml yolu")
    parser.add_argument("--host", default="0.0.0.0",
                        help="dinlenecek adres (varsayılan: tüm ağ arayüzleri)")
    args = parser.parse_args()

    try:
        import uvicorn

        from sinav.app import create_app
        from sinav.config import ConfigError, load_config
        from sinav.discovery import lan_ips
    except ImportError as exc:
        print(f"Gerekli Python paketleri kurulu değil: {exc}\n"
              "Kurulum (internet varken):  pip install -r server/requirements.txt")
        return 2

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"AYAR HATASI: {exc}")
        return 2

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    app = create_app(cfg)

    ips = lan_ips()
    print("=" * 66)
    print(f"  Sınıf: {cfg.sinif_adi}   Öğretmen: {cfg.ogretmen_adi}")
    print(f"  Öğretmen paneli : http://localhost:{cfg.port}/panel  (yalnızca bu bilgisayar)")
    if ips:
        for ip in ips:
            print(f"  Öğrenci adresi  : http://{ip}:{cfg.port}/   (elle IP girişi için: {ip})")
    else:
        print("  UYARI: Ağ bağlantısı bulunamadı. Sınıf modemine bağlı mısınız?")
    print(f"  Keşif           : UDP {cfg.discovery_port}    Ekran yayını: RTSP TCP {cfg.rtsp_port}")
    print("  Durdurmak için bu pencerede Ctrl+C")
    print("=" * 66)

    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=cfg.port, access_log=False,
                                           log_level="warning", timeout_graceful_shutdown=2))
    # "Sistemi kapat" in the panel (or in the question shown after the panel window was
    # closed) stops the web server through this.
    app.state.stop_server = lambda: setattr(server, "should_exit", True)
    try:
        server.run()
    except OSError as exc:
        print(f"Sunucu başlatılamadı (port {cfg.port} kullanımda olabilir): {exc}")
        return 1
    if app.state.exit_code:
        print("Sistem kapatıldı.")
    return int(app.state.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
