"""Windows that the server opens on the teacher's own desktop.

The panel runs in a browser, and a browser may not tell a web page the real path of a
folder. The server runs on the same computer, so it opens the "choose a folder" window
itself. It also opens the panel window and shows folders in the file manager.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import webbrowser

TITLE = "Sınav klasörünü seçin"
TIMEOUT_S = 900

# Runs in a separate Python process so that Tk never touches the server's own threads.
_TK_SCRIPT = r"""
import sys
import tkinter
from tkinter import filedialog

root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
root.update()
path = filedialog.askdirectory(parent=root, title=sys.argv[1], initialdir=sys.argv[2] or None,
                               mustexist=False)
root.destroy()
sys.stdout.buffer.write((path or "").encode("utf-8"))
"""

# Fallback for a Python that was installed without Tk: Windows' own folder window.
_PS_SCRIPT = r"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $env:SINAV_DIALOG_TITLE
$dialog.ShowNewFolderButton = $true
if ($env:SINAV_DIALOG_DIR) { $dialog.SelectedPath = $env:SINAV_DIALOG_DIR }
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.Opacity = 0
$owner.Show()
$result = $dialog.ShowDialog($owner)
$owner.Close()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if ($result -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($dialog.SelectedPath) }
"""


class DialogUnavailable(Exception):
    """No folder window can be opened on this computer."""


def _app_window_browser() -> str | None:
    """Edge or Chrome: both can show a page in a window of its own (no tabs, no address bar)."""
    roots = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LocalAppData")]
    for relative in (os.path.join("Microsoft", "Edge", "Application", "msedge.exe"),
                     os.path.join("Google", "Chrome", "Application", "chrome.exe")):
        for root in roots:
            if root and os.path.isfile(os.path.join(root, relative)):
                return os.path.join(root, relative)
    return None


def open_panel_window(url: str, as_app: bool = True) -> str:
    """Open the teacher panel on this computer. Returns "app" or "browser".

    as_app: show it like an application, in a window of its own; falls back to an ordinary
    browser tab when neither Edge nor Chrome is found.
    """
    if as_app and os.name == "nt":
        browser = _app_window_browser()
        if browser:
            try:
                subprocess.Popen([browser, f"--app={url}", "--start-maximized", "--no-first-run",
                                  "--no-default-browser-check"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return "app"
            except OSError:
                pass
    webbrowser.open(url)
    return "browser"


def open_folder(path: str) -> None:
    """Show a folder in the file manager of the teacher's computer. Raises OSError on failure."""
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - a folder chosen by the teacher, opened in Explorer
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def open_in_editor(path: str) -> None:
    """Open a text file (the settings) in the plain editor of this computer. Raises OSError."""
    if os.name == "nt":
        # Not os.startfile: ".yaml" usually has no program of its own on Windows.
        subprocess.Popen(["notepad.exe", path], stdin=subprocess.DEVNULL,  # noqa: S603, S607
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def _run(command: list[str], env: dict[str, str] | None = None) -> str | None:
    """Run a dialog helper; return its output, or None when it could not show a window."""
    try:
        # No console window: the installed application runs without one, and a helper that
        # opened its own would flash a black window in front of the panel.
        done = subprocess.run(command, capture_output=True, timeout=TIMEOUT_S, env=env, check=False,
                              stdin=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", "replace").strip()


def pick_folder(initial: str = "") -> str:
    """Let the teacher choose a folder. Returns "" when the window was cancelled.

    Blocks until the window is closed: call it from a worker thread.
    """
    start = initial if initial and os.path.isdir(initial) else ""

    chosen = _run([sys.executable, "-c", _TK_SCRIPT, TITLE, start])
    if chosen is None and os.name == "nt":
        env = dict(os.environ, SINAV_DIALOG_TITLE=TITLE, SINAV_DIALOG_DIR=start)
        encoded = base64.b64encode(_PS_SCRIPT.encode("utf-16-le")).decode("ascii")
        chosen = _run(["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
                       "-EncodedCommand", encoded], env)
    if chosen is None:
        raise DialogUnavailable()
    return os.path.normpath(chosen) if chosen else ""
