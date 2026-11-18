"""Talks to the local MediaMTX control API: stream status, recording folder, stopping a stream.

No video is handled here.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

TIMEOUT_S = 1.5


def _call(url: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    # The API is on 127.0.0.1; never route it through a system proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=TIMEOUT_S) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw.strip() else {}


def _get(url: str) -> dict:
    return _call(url)


def _rtsp_sessions(api_base: str) -> tuple[str, list[dict]]:
    """Return (endpoint prefix, RTSP sessions)."""
    for prefix in ("/v3/rtsp/sessions", "/v3/rtspsessions"):
        try:
            return prefix, _get(f"{api_base}{prefix}/list?itemsPerPage=1000").get("items", [])
        except urllib.error.HTTPError:
            continue  # older/newer MediaMTX uses the other spelling
    return "", []


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
    _, sessions = _rtsp_sessions(api_base)
    for item in sessions:
        if item.get("state") == "publish" and item.get("path"):
            publishers[item["path"]] = _host_of(str(item.get("remoteAddr") or ""))
    return ready, publishers


def set_recording(api_base: str, record_path: str) -> None:
    """Record every stream to record_path (a MediaMTX path pattern); "" turns recording off.

    Takes effect immediately, also for streams that are already running.
    """
    body: dict = {"record": bool(record_path)}
    if record_path:
        body["recordPath"] = record_path
    _call(f"{api_base}/v3/config/pathdefaults/patch", "PATCH", body)


def kick_publishers(api_base: str, paths: list[str]) -> int:
    """Stop the publishers of the given paths. Returns how many were stopped."""
    wanted = set(paths)
    prefix, sessions = _rtsp_sessions(api_base)
    stopped = 0
    for item in sessions:
        if item.get("state") == "publish" and item.get("path") in wanted and item.get("id"):
            try:
                _call(f"{api_base}{prefix}/kick/{item['id']}", "POST")
                stopped += 1
            except urllib.error.HTTPError:
                pass  # already gone
    return stopped
