"""Windows that the server opens on the teacher's own desktop.

The panel runs in a browser. A browser may not tell a web page the real path of a folder,
and a page cannot ask a question while its own window is being closed. The server runs on
the same computer, so it opens these windows itself: the "choose a folder" window and the
question shown after the panel window was closed.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import time

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


def open_folder(path: str) -> None:
    """Show a folder in the file manager of the teacher's computer. Raises OSError on failure."""
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - a folder chosen by the teacher, opened in Explorer
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def _run(command: list[str], env: dict[str, str] | None = None) -> str | None:
    """Run a dialog helper; return its output, or None when it could not show a window."""
    try:
        done = subprocess.run(command, capture_output=True, timeout=TIMEOUT_S, env=env, check=False,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", "replace").strip()


# Shown on the teacher's desktop after the panel window (browser) was closed. A web page
# cannot ask anything while its own window closes, so the server asks right afterwards.
_CLOSED_SCRIPT = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ink = [System.Drawing.Color]::FromArgb(29, 37, 48)
$line = [System.Drawing.Color]::FromArgb(201, 206, 214)

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Sınav İzleme'
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$form.ShowInTaskbar = $true
$form.BackColor = [System.Drawing.Color]::White
$form.ForeColor = $ink
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$form.ClientSize = New-Object System.Drawing.Size(580, 236)
$form.Tag = 'background'

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Panel penceresi kapatıldı'
$title.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 14)
$title.SetBounds(28, 22, 524, 34)
$form.Controls.Add($title)

$body = New-Object System.Windows.Forms.Label
$body.Text = $env:SINAV_DIALOG_TEXT
$body.SetBounds(28, 64, 524, 96)
$form.Controls.Add($body)

function Add-Choice([string]$text, [int]$left, [int]$width, [string]$answer, [bool]$primary) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $text
    $button.SetBounds($left, 172, $width, 40)
    $button.FlatStyle = 'Flat'
    $button.UseMnemonic = $false
    if ($primary) {
        $button.BackColor = [System.Drawing.Color]::FromArgb(43, 98, 217)
        $button.ForeColor = [System.Drawing.Color]::White
        $button.FlatAppearance.BorderSize = 0
        $button.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 10)
    } else {
        $button.BackColor = [System.Drawing.Color]::White
        $button.FlatAppearance.BorderColor = $line
    }
    $button.Tag = $answer
    $button.Add_Click({
        param($sender, $e)
        if ($sender.Tag -eq 'shutdown' -and $env:SINAV_DIALOG_CONFIRM) {
            $sure = [System.Windows.Forms.MessageBox]::Show($form, $env:SINAV_DIALOG_CONFIRM, 'Sınav İzleme',
                'YesNo', 'Warning', 'Button2')
            if ($sure -ne [System.Windows.Forms.DialogResult]::Yes) { return }
        }
        $form.Tag = $sender.Tag
        $form.Close()
    })
    $form.Controls.Add($button)
    return $button
}

$keep = Add-Choice 'Arka planda çalışsın' 28 196 'background' $true
[void](Add-Choice 'Paneli yeniden aç' 236 160 'reopen' $false)
[void](Add-Choice 'Sistemi kapat' 408 144 'shutdown' $false)
$form.AcceptButton = $keep
[void]$form.ShowDialog()
[Console]::Out.Write($form.Tag)
"""


def ask_panel_closed(text: str, confirm: str = "", cancelled=None) -> str:
    """Ask the teacher what to do after the panel window was closed.

    Returns "background" (keep the system running), "reopen" or "shutdown".
    cancelled: optional callable; when it returns True the question is withdrawn (the panel
    was opened again in the meantime) and "background" is returned.
    Blocks until answered: call it from a worker thread. Raises DialogUnavailable when no
    window can be shown (not Windows).
    """
    if os.name != "nt":
        raise DialogUnavailable()
    env = dict(os.environ, SINAV_DIALOG_TEXT=text, SINAV_DIALOG_CONFIRM=confirm)
    encoded = base64.b64encode(_CLOSED_SCRIPT.encode("utf-16-le")).decode("ascii")
    try:
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        raise DialogUnavailable() from exc
    deadline = time.monotonic() + TIMEOUT_S
    while process.poll() is None:
        if time.monotonic() > deadline or (cancelled is not None and cancelled()):
            process.kill()
            process.wait()
            return "background"
        time.sleep(0.3)
    if process.returncode != 0:
        raise DialogUnavailable()
    answer = (process.stdout.read() if process.stdout else b"").decode("utf-8", "replace").strip()
    return answer if answer in ("reopen", "shutdown") else "background"


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
