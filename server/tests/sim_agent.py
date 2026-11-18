"""Öğrenci ajanı simülatörü (yalnızca test içindir; gerçek ajan /agent altındadır).

Windows öğrenci bilgisayarı olmadan sunucuyu, paneli ve MediaMTX'i denemek için
gerçek ajanın ağ davranışını taklit eder: UDP keşif -> giriş -> heartbeat ->
(isteğe bağlı) ffmpeg test yayını -> sınav dosyasını indirme -> teslim. Sınav bitince
gerçek ajan gibi açık kalır; öğretmen sınavı kapatınca çıkar (otomatik teslim yoktur).

Örnek (öğretmen bilgisayarında, sunucu çalışırken):
    python server/tests/sim_agent.py --count 5 --stream
    python server/tests/sim_agent.py --numara 2021001 --ad Ayşe --soyad Yılmaz --stream --submit
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

DISCOVER = b"SINAV_DISCOVER v1"


def discover(port: int, timeout: float = 5.0) -> list[dict]:
    """Broadcast a discovery request and collect the answers."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.5)
    found: dict[tuple[str, int], dict] = {}
    deadline = time.monotonic() + timeout
    next_send = 0.0
    try:
        while time.monotonic() < deadline and not found:
            if time.monotonic() >= next_send:
                for target in ("255.255.255.255", "127.0.0.1"):
                    try:
                        sock.sendto(DISCOVER, (target, port))
                    except OSError:
                        pass
                next_send = time.monotonic() + 1.0
            try:
                data, _ = sock.recvfrom(4096)
                reply = json.loads(data.decode("utf-8"))
                found[(reply["ip"], reply["port"])] = reply
            except (socket.timeout, ValueError, KeyError):
                continue
    finally:
        sock.close()
    return list(found.values())


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.token = ""
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method: str, path: str, body: dict | None = None, raw: bool = False,
             data: bytes | None = None, content_type: str = "application/json"):
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        if data is not None:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self._opener.open(request, timeout=10) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except ValueError:
                pass
            raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from None
        return payload if raw else json.loads(payload.decode("utf-8"))

    def submit(self, filename: str, content: bytes) -> dict:
        boundary = uuid.uuid4().hex
        parts = [
            # The real agent sends the hash of the file it read, so that the server can tell
            # whether the upload arrived intact.
            f'--{boundary}\r\nContent-Disposition: form-data; name="sha256"\r\n\r\n'
            f'{hashlib.sha256(content).hexdigest()}\r\n'.encode(),
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode(),
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        return self.call("POST", "/api/submit", data=b"".join(parts),
                         content_type=f"multipart/form-data; boundary={boundary}")


class SimAgent(threading.Thread):
    def __init__(self, base: str, numara: str, ad: str, soyad: str, args, index: int = 0):
        super().__init__(daemon=True, name=f"sim-{numara}")
        self.api = Api(base)
        self.numara, self.ad, self.soyad = numara, ad, soyad
        self.args = args
        self.index = index
        self.ffmpeg: subprocess.Popen | None = None
        self.exam_bytes: bytes | None = None
        self.done = threading.Event()

    def log(self, text: str) -> None:
        print(f"[{self.numara}] {text}", flush=True)

    def start_stream(self, stream: dict) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.log("ffmpeg bulunamadı; yayın yapılmayacak (PATH'e ekleyin)")
            return
        url = stream["url"].replace("rtsp://", f"rtsp://{stream['user']}:{stream['pass']}@", 1)
        fps = int(stream.get("fps") or 5)
        width = int(stream.get("width") or 1280)
        kbps = int(stream.get("bitrate_kbps") or 500)
        label = f"{self.numara} {self.ad}".replace(":", " ").replace("'", " ")
        source = (f"testsrc2=size=1920x1080:rate={fps},"
                  f"drawbox=x=0:y=0:w=iw:h=120:color=black@0.6:t=fill")
        vf = f"scale={width}:-2"
        if self.args.label:
            vf = f"drawtext=text='{label}':x=40:y=30:fontsize=64:fontcolor=white,{vf}"
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi", "-i", source,
            "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k",
            "-g", str(fps * 2), "-pix_fmt", "yuv420p",
            "-f", "rtsp", "-rtsp_transport", "tcp", url,
        ]
        self.ffmpeg = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)

    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001
            self.log(f"HATA: {exc}")
        finally:
            if self.ffmpeg and self.ffmpeg.poll() is None:
                self.ffmpeg.terminate()
            self.done.set()

    def _run(self) -> None:
        login = self.api.call("POST", "/api/login", {
            "numara": self.numara, "ad": self.ad, "soyad": self.soyad,
            "hostname": self.args.hostname or f"SIM-PC-{self.index % 1000:02d}",
            "mac": self.args.mac or "02:00:00:%02X:%02X:%02X" % (
                (self.index >> 16) & 255, (self.index >> 8) & 255, self.index & 255),
            "agent_version": "sim-1.0",
        })
        self.api.token = login["token"]
        self.log(f"giriş yapıldı; durum {login['exam_state']}, yayın {login['stream']['url']}")
        if self.args.stream:
            self.start_stream(login["stream"])

        seen = ""
        started = time.monotonic()
        submitted = False
        ended = None
        while True:
            alive = self.ffmpeg is not None and self.ffmpeg.poll() is None
            hb = self.api.call("POST", "/api/heartbeat", {
                "fg_process": "PacketTracer.exe",
                "fg_path": r"C:\Program Files\Cisco Packet Tracer 8.2.2\bin\PacketTracer.exe",
                "fg_title": "Cisco Packet Tracer - sinav.pka",
                "monitors": 1, "ffmpeg_alive": alive, "exam_state_seen": seen,
            })
            state = hb["exam_state"]
            if state != seen:
                self.log(f"sınav durumu: {state}")
                if state == "RUNNING" and self.exam_bytes is None:
                    self.exam_bytes = self.api.call("GET", "/api/exam-file", raw=True)
                    self.log(f"sınav dosyası indirildi ({len(self.exam_bytes)} bayt)")
                    self.api.call("POST", "/api/event",
                                  {"type": "exam_file_ready", "details": {}, "ts": time.time()})
                    started = time.monotonic()
                seen = state

            if state == "RUNNING" and self.args.kill_event and time.monotonic() - started > 3:
                self.args.kill_event = False
                self.api.call("POST", "/api/event", {
                    "type": "process_killed", "ts": time.time(),
                    "details": {"name": "chrome.exe",
                                "path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                                "title": "Yeni Sekme - Google Chrome"},
                })
                self.log("örnek 'process_killed' olayı gönderildi")

            if state == "RUNNING" and self.args.desktop_event and time.monotonic() - started > 5:
                self.args.desktop_event = False
                self.api.call("POST", "/api/event", {"type": "desktop_switch", "ts": time.time(), "details": {}})
                self.log("örnek 'desktop_switch' olayı gönderildi")

            if (state == "RUNNING" and self.args.submit and not submitted
                    and time.monotonic() - started > self.args.submit_after):
                content = self.exam_bytes or b""
                if not self.args.submit_unchanged:
                    content += f"\ncozum-{self.numara}".encode()
                result = self.api.submit("sinav.pka", content)
                self.log(f"teslim edildi: {result['filename']} sha256={result['sha256'][:16]}…")
                submitted = True
                return

            if hb.get("submitted") and not submitted:
                # The server found this student's file in the submissions folder (e.g. the teacher
                # copied it there by hand): the real agent finishes with "Teslim alındı".
                self.log("teslim dosyası sunucuda görüldü, çıkılıyor")
                return

            if state == "CLOSED":
                # The teacher closed the exam for everybody: the program exits. Nothing is
                # handed in automatically.
                self.log("sınav kapatıldı, çıkılıyor")
                return

            if state == "ENDED":
                # Like the real agent: stay open after the end; the file can still be handed in (late).
                if ended is None:
                    ended = time.monotonic()
                    self.log("sınav bitti; program açık kalıyor")
                if (self.args.late_submit is not None and not submitted and self.exam_bytes is not None
                        and time.monotonic() - ended > self.args.late_submit):
                    content = self.exam_bytes + f"\ngec-{self.numara}".encode()
                    result = self.api.submit("sinav.pka", content)
                    self.log(f"geç teslim: {result['filename']} (geç: {result.get('late')})")
                    return
            time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Öğrenci ajanı simülatörü (test)")
    parser.add_argument("--server", help="http://IP:8000 (verilmezse UDP keşif kullanılır)")
    parser.add_argument("--discovery-port", type=int, default=47000)
    parser.add_argument("--numara", default="")
    parser.add_argument("--ad", default="Deneme")
    parser.add_argument("--soyad", default="Öğrenci")
    parser.add_argument("--hostname", default="")
    parser.add_argument("--mac", default="")
    parser.add_argument("--count", type=int, default=1, help="sahte öğrenci sayısı")
    parser.add_argument("--first", type=int, default=20210001, help="ilk öğrenci numarası")
    parser.add_argument("--stream", action="store_true", help="ffmpeg ile test görüntüsü yayınla")
    parser.add_argument("--label", action="store_true",
                        help="görüntüye numarayı yaz (ffmpeg'de drawtext/font desteği gerekir)")
    parser.add_argument("--submit", action="store_true", help="sınav başlayınca dosya teslim et")
    parser.add_argument("--submit-after", type=float, default=8.0, help="teslimden önce bekleme (sn)")
    parser.add_argument("--submit-unchanged", action="store_true",
                        help="--submit ile: sınav dosyasını hiç değiştirmeden teslim et")
    parser.add_argument("--late-submit", type=float, default=None, metavar="SN",
                        help="sınav bittikten SN saniye sonra teslim et (geç teslim)")
    parser.add_argument("--kill-event", action="store_true", help="örnek 'process_killed' olayı gönder")
    parser.add_argument("--desktop-event", action="store_true",
                        help="örnek 'desktop_switch' (başka masaüstüne geçti) olayı gönder")
    args = parser.parse_args()

    base = args.server
    if not base:
        print("Sunucu aranıyor (UDP keşif)…", flush=True)
        servers = discover(args.discovery_port)
        if not servers:
            print("Sınav sunucusu bulunamadı. --server http://IP:8000 ile deneyin.")
            return 1
        server = servers[0]
        print(f"Bulundu — Sınıf: {server['sinif_adi']} — Öğretmen: {server['ogretmen_adi']} "
              f"({server['ip']}:{server['port']})", flush=True)
        base = f"http://{server['ip']}:{server['port']}"

    agents = []
    for i in range(args.count):
        numara = args.numara if (args.numara and args.count == 1) else str(args.first + i)
        ad = args.ad if args.count == 1 else f"{args.ad}{i + 1}"
        # Unique fake computer name / MAC per number, also across several simulator processes.
        index = int(numara) % 1_000_000 if numara.isdigit() else i + 1
        agent = SimAgent(base, numara, ad, args.soyad, argparse.Namespace(**vars(args)), index=index)
        agent.start()
        agents.append(agent)
        time.sleep(0.15)
    try:
        while any(not a.done.is_set() for a in agents):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Durduruldu.")
    for agent in agents:
        if agent.ffmpeg and agent.ffmpeg.poll() is None:
            agent.ffmpeg.terminate()
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.exit(main())
