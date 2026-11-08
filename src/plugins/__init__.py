"""Schaltplan-Live-Ansicht -- KiCad Action Plugin.

Beim Laden durch KiCad wird im Hintergrund ein kleiner Webserver gestartet
(http://localhost:8765), der den Schaltplan des gerade geoeffneten Projekts
anzeigt und bei jedem Speichern aktualisiert. Der Server beendet sich, wenn
KiCad geschlossen wird. Der Toolbar-Knopf im PCB-Editor oeffnet die Ansicht.
Linux, Windows und macOS.
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import webbrowser

import pcbnew

PORT = 8765
URL = "http://localhost:%d" % PORT
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(PLUGIN_DIR, "liveview_server.py")
IS_WIN = sys.platform == "win32"


def _server_running():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _python():
    """Python-Interpreter fuer den Server.

    sys.executable ist innerhalb von KiCad je nach Plattform das KiCad-Binary
    selbst. Bevorzugt wird das mit KiCad gelieferte Python, dann das System.
    """
    exe = sys.executable or ""
    base = os.path.basename(exe).lower()
    if base.startswith("python"):
        if IS_WIN and base == "python.exe":
            w = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.isfile(w):
                return w
        return exe
    names = ["pythonw.exe", "python.exe"] if IS_WIN else ["python3", "python"]
    dirs = [os.path.dirname(exe), sys.prefix, os.path.join(sys.prefix, "bin"),
            sys.exec_prefix, os.path.join(sys.exec_prefix, "bin")]
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    for n in (["pythonw", "python", "py"] if IS_WIN else ["python3", "python"]):
        p = shutil.which(n)
        if p:
            return p
    return None


def _kicad_cli_hint():
    """kicad-cli neben dem laufenden KiCad suchen (Windows/macOS-Bundles)."""
    exe = sys.executable or ""
    cands = [os.path.join(os.path.dirname(exe), "kicad-cli.exe" if IS_WIN else "kicad-cli")]
    if ".app/Contents" in exe:  # macOS: .../KiCad.app/Contents/...
        app = exe.split(".app/Contents")[0] + ".app/Contents"
        cands.append(os.path.join(app, "MacOS", "kicad-cli"))
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def ensure_server():
    if _server_running():
        return
    py = _python()
    if not py:
        raise RuntimeError("kein Python-Interpreter gefunden")
    cmd = [py, "-I", SERVER, "--port", str(PORT)]
    cli = _kicad_cli_hint()
    if cli:
        cmd += ["--kicad-cli", cli]
    log_dir = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    log = open(os.path.join(log_dir, "kicad-liveview.log"), "ab")
    kw = dict(stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True)
    if IS_WIN:
        kw["creationflags"] = (subprocess.DETACHED_PROCESS
                               | subprocess.CREATE_NEW_PROCESS_GROUP
                               | subprocess.CREATE_NO_WINDOW)
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)
    log.close()


class SchematicLiveView(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "Schaltplan Live-Ansicht"
        self.category = "Ansicht"
        self.description = "Zeigt den Schaltplan des offenen Projekts live im Browser"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(PLUGIN_DIR, "icon.png")

    def Run(self):
        ensure_server()
        webbrowser.open(URL)


try:
    ensure_server()
except Exception as error:  # Plugin trotzdem registrieren
    print("[Schaltplan Live-Ansicht] Serverstart fehlgeschlagen: %s" % error, file=sys.stderr)

SchematicLiveView().register()
