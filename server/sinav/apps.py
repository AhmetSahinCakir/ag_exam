"""The programs offered in "Ayarlar → İzin verilen programlar → Program ekle".

Two sources:

* a short list of programs that are commonly allowed next to Packet Tracer (a browser, an
  editor, a terminal ...), known by their file names;
* the programs installed on this computer (the Start menu shortcuts), with their own icons, so
  that a program can be found by typing a part of its name.

A program is allowed by its file name (chrome.exe), wherever it is installed: the name is the
same on the students' computers, the folder often is not.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
from typing import Any

# kind: which drawing the panel shows when the program's own icon is not known.
CATALOG: list[dict[str, Any]] = [
    {"name": "Google Chrome", "exe": ["chrome.exe"], "kind": "browser"},
    {"name": "Microsoft Edge", "exe": ["msedge.exe"], "kind": "browser"},
    {"name": "Mozilla Firefox", "exe": ["firefox.exe"], "kind": "browser"},
    {"name": "Opera", "exe": ["opera.exe"], "kind": "browser"},
    {"name": "Visual Studio Code", "exe": ["Code.exe"], "kind": "code"},
    {"name": "Visual Studio", "exe": ["devenv.exe"], "kind": "code"},
    {"name": "Notepad++", "exe": ["notepad++.exe"], "kind": "code"},
    {"name": "PyCharm", "exe": ["pycharm64.exe"], "kind": "code"},
    {"name": "Not Defteri", "exe": ["notepad.exe"], "kind": "text"},
    {"name": "Hesap Makinesi", "exe": ["CalculatorApp.exe", "calc.exe"], "kind": "tool"},
    {"name": "Komut İstemi", "exe": ["cmd.exe"], "kind": "terminal"},
    {"name": "Windows PowerShell", "exe": ["powershell.exe"], "kind": "terminal"},
    {"name": "Windows Terminal", "exe": ["WindowsTerminal.exe"], "kind": "terminal"},
    {"name": "PuTTY", "exe": ["putty.exe"], "kind": "terminal"},
    {"name": "Tera Term", "exe": ["ttermpro.exe"], "kind": "terminal"},
    {"name": "Wireshark", "exe": ["Wireshark.exe"], "kind": "network"},
    {"name": "GNS3", "exe": ["gns3.exe"], "kind": "network"},
    {"name": "Microsoft Word", "exe": ["WINWORD.EXE"], "kind": "office"},
    {"name": "Microsoft Excel", "exe": ["EXCEL.EXE"], "kind": "office"},
    {"name": "Microsoft PowerPoint", "exe": ["POWERPNT.EXE"], "kind": "office"},
    {"name": "Adobe Acrobat Reader", "exe": ["Acrobat.exe", "AcroRd32.exe"], "kind": "office"},
    {"name": "Paint", "exe": ["mspaint.exe"], "kind": "tool"},
    {"name": "Ekran Alıntısı Aracı", "exe": ["SnippingTool.exe"], "kind": "tool"},
]

MAX_INSTALLED = 400
SCAN_TIMEOUT_S = 60

# Reads the Start menu of this computer: one line of JSON, [{name, exe, icon}], the icon a
# 32x32 PNG in base64. Shortcuts to uninstallers, manuals and web pages are left out.
_SCAN_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Drawing
$shell = New-Object -ComObject Shell.Application
$skip = '(?i)uninstall|kaldır|remove|readme|beni oku|help|yardım|manual|kılavuz|license|lisans|website|web site|documentation|release notes|setup|repair|onar'
$seen = @{}
$items = New-Object System.Collections.ArrayList
$folders = @([Environment]::GetFolderPath('CommonPrograms'), [Environment]::GetFolderPath('Programs'))
foreach ($folder in $folders) {
    if (-not $folder -or -not (Test-Path -LiteralPath $folder)) { continue }
    foreach ($link in @(Get-ChildItem -LiteralPath $folder -Recurse -Filter *.lnk -File)) {
        if ($items.Count -ge __MAX__) { break }
        try {
            $name = [IO.Path]::GetFileNameWithoutExtension($link.Name)
            if ($name -match $skip) { continue }
            $target = $shell.Namespace($link.DirectoryName).ParseName($link.Name).GetLink.Path
            if (-not $target -or $target -notmatch '(?i)\.exe$') { continue }
            if ($target -match '(?i)\\Windows\\Installer\\') { continue }
            if (-not (Test-Path -LiteralPath $target)) { continue }
            $exe = [IO.Path]::GetFileName($target)
            $key = $exe.ToLowerInvariant()
            if ($seen.ContainsKey($key)) { continue }
            $seen[$key] = $true
            $png = ''
            try {
                $icon = [System.Drawing.Icon]::ExtractAssociatedIcon($target)
                if ($icon) {
                    $bitmap = New-Object System.Drawing.Bitmap 32, 32
                    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
                    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                    $source = $icon.ToBitmap()
                    $graphics.DrawImage($source, 0, 0, 32, 32)
                    $stream = New-Object IO.MemoryStream
                    $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
                    $png = [Convert]::ToBase64String($stream.ToArray())
                    $stream.Dispose(); $graphics.Dispose(); $source.Dispose(); $bitmap.Dispose(); $icon.Dispose()
                }
            } catch { }
            [void]$items.Add(@{ name = $name; exe = $exe; icon = $png })
        } catch { }
    }
}
$json = ConvertTo-Json -InputObject @($items) -Compress -Depth 3
if (-not $json) { $json = '[]' }
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::Out.Write($json)
""".replace("__MAX__", str(MAX_INSTALLED))


def parse_scan(output: str) -> list[dict[str, str]]:
    """Turn what the scan printed into [{name, exe, icon}] (icon: a data URL or "")."""
    try:
        data = json.loads(output)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())[:80]
        exe = str(item.get("exe") or "").strip()
        if not name or not exe.lower().endswith(".exe") or any(ch in exe for ch in '\\/:*?"<>|%') or len(exe) > 120:
            continue
        if exe.lower() in seen:
            continue
        seen.add(exe.lower())
        icon = str(item.get("icon") or "")
        try:
            valid = bool(icon) and len(icon) < 40000 and base64.b64decode(icon, validate=True).startswith(b"\x89PNG")
        except ValueError:
            valid = False
        found.append({"name": name, "exe": exe, "icon": f"data:image/png;base64,{icon}" if valid else ""})
    found.sort(key=lambda entry: entry["name"].casefold())
    return found[:MAX_INSTALLED]


def scan_installed() -> list[dict[str, str]]:
    """The programs in this computer's Start menu. Empty on anything but Windows, and when the
    scan cannot run. Takes a few seconds: call it from a worker thread."""
    if os.name != "nt":
        return []
    encoded = base64.b64encode(_SCAN_SCRIPT.encode("utf-16-le")).decode("ascii")
    try:
        done = subprocess.run(  # noqa: S603, S607 - Windows' own PowerShell, fixed script
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", encoded],
            capture_output=True, timeout=SCAN_TIMEOUT_S, check=False, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_scan(done.stdout.decode("utf-8", "replace").strip())


class AppList:
    """The list behind "Program ekle": the fixed catalogue at once, this computer's programs as
    soon as they have been read (once, in the background)."""

    def __init__(self, scan=scan_installed):
        self._scan = scan
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._installed: list[dict[str, str]] | None = None

    def _run(self) -> None:
        try:
            found = self._scan()
        except Exception:  # noqa: BLE001 - the catalogue is still there
            found = []
        with self._lock:
            self._installed = found

    def view(self) -> dict[str, Any]:
        with self._lock:
            if self._installed is None and self._thread is None:
                self._thread = threading.Thread(target=self._run, name="program-listesi", daemon=True)
                self._thread.start()
            installed = self._installed
        icons = {entry["exe"].lower(): entry["icon"] for entry in installed or []}
        catalog = []
        for entry in CATALOG:
            icon = next((icons[exe.lower()] for exe in entry["exe"] if icons.get(exe.lower())), "")
            catalog.append({"name": entry["name"], "exe": list(entry["exe"]), "kind": entry["kind"], "icon": icon})
        known = {exe.lower() for entry in CATALOG for exe in entry["exe"]}
        return {
            "catalog": catalog,
            # What is in the catalogue already is not listed a second time.
            "installed": [entry for entry in installed or [] if entry["exe"].lower() not in known],
            "scanning": installed is None,
        }
