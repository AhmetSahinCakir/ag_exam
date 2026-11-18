"""UDP discovery responder.

Agents broadcast "SINAV_DISCOVER v1" on the LAN; we answer with a small JSON
document so that the agent can find this classroom's server without a
configured IP address.

A plain blocking socket in a daemon thread is used on purpose: on Windows,
asyncio's datagram transport can stop receiving after an ICMP "port
unreachable" (WSAECONNRESET) caused by an agent that already closed its socket.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from typing import Callable

log = logging.getLogger("sinav.discovery")

DISCOVER_PREFIX = b"SINAV_DISCOVER"
PROTOCOL_VERSION = 1


def local_ip_for(peer_ip: str) -> str:
    """The local address the OS would use to reach peer_ip (no packet is sent)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((peer_ip, 9))
        return probe.getsockname()[0]
    except OSError:
        return ""
    finally:
        probe.close()


def lan_ips() -> list[str]:
    """Best-effort list of this machine's non-loopback IPv4 addresses."""
    found: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    default = local_ip_for("192.0.2.1")
    if default and not default.startswith("127.") and default not in found:
        found.insert(0, default)
    return found


class DiscoveryResponder(threading.Thread):
    def __init__(self, port: int, info: Callable[[], dict]):
        super().__init__(name="discovery", daemon=True)
        self.port = port
        self._info = info
        self._stop_event = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.settimeout(1.0)
        # Raises OSError when the port is taken; the caller reports it on the panel.
        self._sock.bind(("0.0.0.0", port))

    def run(self) -> None:
        log.info("Keşif dinleniyor: UDP %d", self.port)
        while not self._stop_event.is_set():
            try:
                data, addr = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except ConnectionResetError:
                continue  # Windows: previous reply hit a closed port; keep listening
            except OSError:
                if self._stop_event.is_set():
                    break
                self._stop_event.wait(0.2)
                continue
            if not data.strip().startswith(DISCOVER_PREFIX):
                continue
            try:
                reply = dict(self._info())
                reply["ip"] = local_ip_for(addr[0])
                reply["v"] = PROTOCOL_VERSION
                if not reply["ip"]:
                    continue
                self._sock.sendto(json.dumps(reply, ensure_ascii=False).encode("utf-8"), addr)
            except OSError as exc:
                log.warning("Keşif yanıtı gönderilemedi (%s): %s", addr[0], exc)

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._sock.close()
        except OSError:
            pass
