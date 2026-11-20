"""The programs offered in "Ayarlar → Program ekle"."""

from __future__ import annotations

import base64
import json
import os
import threading
import time

from conftest import PANEL, Env
from sinav import apps

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 40).decode()


def test_catalogue_has_what_is_commonly_allowed_next_to_packet_tracer():
    names = {entry["name"] for entry in apps.CATALOG}
    assert {"Google Chrome", "Microsoft Edge", "Visual Studio Code", "PuTTY", "Wireshark"} <= names
    exes = [exe.lower() for entry in apps.CATALOG for exe in entry["exe"]]
    assert len(exes) == len(set(exes)) and all(exe.endswith(".exe") for exe in exes)
    assert {entry["kind"] for entry in apps.CATALOG} <= {"browser", "code", "terminal", "office", "network", "text", "tool"}


def test_what_the_scan_printed_is_checked_before_it_is_used():
    printed = json.dumps([
        {"name": "Zoom  Workplace", "exe": "Zoom.exe", "icon": PNG},
        {"name": "Ağ Aracı", "exe": "ag.exe", "icon": "not-base64!"},        # icon dropped, entry kept
        {"name": "Tekrar", "exe": "ZOOM.EXE", "icon": ""},                    # same program again
        {"name": "Kötü", "exe": "..\\..\\evil.exe", "icon": ""},              # not a plain file name
        {"name": "", "exe": "adsiz.exe"}, {"name": "Belge", "exe": "belge.pdf"}, "çöp", None,
    ])
    found = apps.parse_scan(printed)
    assert [(entry["name"], entry["exe"]) for entry in found] == [("Ağ Aracı", "ag.exe"), ("Zoom Workplace", "Zoom.exe")]
    assert found[0]["icon"] == "" and found[1]["icon"] == "data:image/png;base64," + PNG
    # One program alone is printed as an object by PowerShell 5; nothing usable gives an empty list.
    assert apps.parse_scan(json.dumps({"name": "Tek", "exe": "tek.exe", "icon": ""}))[0]["exe"] == "tek.exe"
    assert apps.parse_scan("") == [] and apps.parse_scan("HATA") == [] and apps.parse_scan("42") == []


def test_list_is_there_at_once_and_this_computers_programs_follow():
    release = threading.Event()
    calls = []

    def scan():
        calls.append(1)
        release.wait(5)
        return [{"name": "Chrome", "exe": "CHROME.EXE", "icon": "data:image/png;base64," + PNG},
                {"name": "Zoom", "exe": "Zoom.exe", "icon": ""}]

    listing = apps.AppList(scan)
    first = listing.view()
    assert first["scanning"] is True and first["installed"] == [] and len(first["catalog"]) == len(apps.CATALOG)
    assert all(entry["icon"] == "" for entry in first["catalog"])
    listing.view()                                   # asked again while the scan runs: still one scan
    release.set()
    deadline = time.monotonic() + 5
    while listing.view()["scanning"] and time.monotonic() < deadline:
        time.sleep(0.02)
    done = listing.view()
    assert done["scanning"] is False and calls == [1]
    # A program of the catalogue that is installed here shows its own icon, and is listed once.
    chrome = next(entry for entry in done["catalog"] if entry["name"] == "Google Chrome")
    assert chrome["icon"].startswith("data:image/png;base64,")
    assert [entry["exe"] for entry in done["installed"]] == ["Zoom.exe"]

    def broken():
        raise OSError("powershell yok")

    failed = apps.AppList(broken)
    failed.view()
    deadline = time.monotonic() + 5
    while failed.view()["scanning"] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert failed.view()["installed"] == [] and len(failed.view()["catalog"]) == len(apps.CATALOG)


def test_panel_gets_the_list_and_students_do_not(env: Env):
    data = env.panel.get("/panel/api/apps").json()
    assert {"catalog", "installed", "scanning"} <= set(data) and data["catalog"][0]["name"] == "Google Chrome"
    assert env.student().get("/panel/api/apps").status_code == 403
    # What is picked there is stored by file name and allowed wherever it is installed.
    saved = env.panel.post("/panel/api/settings", headers=PANEL, json={"programs": data["catalog"][0]["exe"]})
    assert saved.status_code == 200 and "**\\chrome.exe" in env.cfg.policy.patterns


def test_real_scan_of_this_computer():
    """On Windows: the Start menu is really read (the test machine has programs installed)."""
    found = apps.scan_installed()
    if os.name != "nt":
        assert found == []
        return
    print(f"kurulu program: {len(found)}; simgesi olan: {sum(1 for entry in found if entry['icon'])}")
    for entry in found[:8]:
        print(f"  {entry['name']}  [{entry['exe']}]  simge {len(entry['icon'])} bayt")
    assert len(found) >= 3 and sum(1 for entry in found if entry["icon"]) >= 3
