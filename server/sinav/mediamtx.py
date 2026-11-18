"""Reads stream status from the local MediaMTX control API. No video is handled here."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

TIMEOUT_S = 1.5


def _get(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    # The API is on 127.0.0.1; never route it through a system proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def _host_of(remote_addr: str) -> str:
    """'192.168.1.5:50000' -> '192.168.1.5', '[::1]:50000' -> '::1'."""
    host = remote_addr.rsplit(":", 1)[0] if ":" in remote_addr else remote_addr
    return host.strip("[]")


def fetch_streams(api_base: str) -> tuple[set[str], dict[str, str]]:
    """Return (paths with a live stream, {path: publisher IP}).

    Raises OSError/ValueError when MediaMTX cannot be reached.
    """
    paths = _get(f"{api_base}/v3/paths/list?itemsPerPage=1000")
    ready: set[str] = set()
    for item in paths.get("items", []):
        # "online" is the current field; "ready" is its deprecated predecessor.
        live = item.get("online") if "online" in item else item.get("ready")
        if live and item.get("name"):
            ready.add(item["name"])

    publishers: dict[str, str] = {}
    sessions: dict = {}
    for endpoint in ("/v3/rtsp/sessions/list", "/v3/rtspsessions/list"):
        try:
            sessions = _get(f"{api_base}{endpoint}?itemsPerPage=1000")
            break
        except urllib.error.HTTPError:
            continue  # older/newer MediaMTX uses the other spelling
    for item in sessions.get("items", []):
        if item.get("state") == "publish" and item.get("path"):
            publishers[item["path"]] = _host_of(str(item.get("remoteAddr") or ""))
    return ready, publishers
