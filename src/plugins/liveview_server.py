#!/usr/bin/env python3
"""KiCad Schaltplan-Live-Ansicht.

Kleiner HTTP-Server, der den Schaltplan des aktuell in KiCad geoeffneten
Projekts per kicad-cli als SVG exportiert und im Browser anzeigt. Die Seite
aktualisiert sich selbst, sobald eine .kicad_sch-Datei gespeichert wird.

- Aktives Projekt: erster Eintrag der KiCad-Dateihistorie (kicad.json), fuer
  den eine Projekt-Lockdatei (~<name>.kicad_pro.lck) existiert.
- Beendet sich selbst, wenn kein KiCad-Prozess mehr laeuft.
- Startet nur einmal: ist der Port belegt, endet der zweite Start sofort.
- Linux, Windows und macOS.
"""
import argparse
import glob
import html
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

KICAD_PROCS = {"kicad", "eeschema", "pcbnew"}
IDLE_EXIT_S = 20
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
# Unter Windows kein Konsolenfenster fuer Hilfsprozesse aufblitzen lassen.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0

state = {
    "project": None,      # Pfad zur .kicad_pro
    "sch": None,          # Pfad zur Root-.kicad_sch
    "sig": None,          # Signatur der mtimes aller .kicad_sch
    "ver": 0,
    "sheets": [],         # [(name, svg-bytes)]
    "error": "",
}
lock = threading.Lock()


# --------------------------------------------------------------------------
# Plattformabhaengige Pfade
# --------------------------------------------------------------------------
def kicad_config_base():
    """Ordner, in dem KiCad seine versionierten Einstellungen ablegt."""
    if os.environ.get("KICAD_CONFIG_HOME"):
        return os.environ["KICAD_CONFIG_HOME"]
    if IS_WIN:
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "kicad")
    if IS_MAC:
        return os.path.expanduser("~/Library/Preferences/kicad")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "kicad")


def kicad_config_dirs():
    base = kicad_config_base()
    if os.path.isfile(os.path.join(base, "kicad.json")):
        return [base]  # KICAD_CONFIG_HOME zeigt direkt auf einen Versionsordner

    def ver(d):
        try:
            return [int(x) for x in os.path.basename(d).split(".")]
        except ValueError:
            return [-1]
    dirs = [d for d in glob.glob(os.path.join(base, "*")) if os.path.isdir(d)]
    return sorted(dirs, key=ver, reverse=True)


def _newest(paths):
    """Pfad mit der hoechsten Versionsnummer (10.0 vor 9.0, nicht alphabetisch)."""
    paths = [p for p in paths if os.path.isfile(p)]

    def ver(p):
        return [int(n) for n in re.findall(r"\d+", p)]
    return max(paths, key=ver) if paths else None


def find_kicad_cli(hint=None):
    """kicad-cli: Hinweis vom Plugin, PATH, dann uebliche Installationsorte."""
    for c in (hint, os.environ.get("KICAD_LIVEVIEW_CLI")):
        if c and os.path.isfile(c):
            return c
    found = shutil.which("kicad-cli")
    if found:
        return found
    if IS_WIN:
        roots = {os.environ.get(v) for v in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA")}
        cands = []
        for r in filter(None, roots):
            cands += glob.glob(os.path.join(r, "KiCad", "*", "bin", "kicad-cli.exe"))
            cands += glob.glob(os.path.join(r, "Programs", "KiCad", "*", "bin", "kicad-cli.exe"))
        return _newest(cands)
    if IS_MAC:
        cands = []
        for apps in ("/Applications", os.path.expanduser("~/Applications")):
            cands += glob.glob(os.path.join(apps, "KiCad*", "KiCad.app", "Contents", "MacOS", "kicad-cli"))
            cands += glob.glob(os.path.join(apps, "KiCad.app", "Contents", "MacOS", "kicad-cli"))
        return _newest(cands)
    return _newest(["/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli"])


def output_dir():
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return os.path.join(base, "kicad-liveview")


# --------------------------------------------------------------------------
# KiCad-Zustand
# --------------------------------------------------------------------------
def active_project():
    for d in kicad_config_dirs():
        try:
            with open(os.path.join(d, "kicad.json"), encoding="utf-8") as f:
                hist = json.load(f).get("system", {}).get("file_history", [])
        except (OSError, ValueError):
            continue
        for pro in hist:
            pdir, name = os.path.split(pro)
            lck = os.path.join(pdir, "~" + name + ".lck")
            if pro.endswith(".kicad_pro") and os.path.exists(pro) and os.path.exists(lck):
                return pro
    return None


def _process_names():
    """Kleingeschriebene Prozessnamen ohne .exe-Endung."""
    if os.path.isdir("/proc/self"):
        names = set()
        for comm in glob.glob("/proc/[0-9]*/comm"):
            try:
                with open(comm) as f:
                    names.add(f.read().strip().lower())
            except OSError:
                pass
        return names
    if IS_WIN:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, creationflags=NO_WINDOW).stdout
        return {line.split('","')[0].strip('"').lower().removesuffix(".exe")
                for line in out.splitlines() if line.strip()}
    out = subprocess.run(["ps", "-axco", "comm"], capture_output=True, text=True).stdout
    return {os.path.basename(line.strip()).lower() for line in out.splitlines()[1:]}


def kicad_running():
    try:
        return bool(KICAD_PROCS & _process_names())
    except Exception:
        # Prozessliste nicht lesbar: offenes Projekt gilt als Lebenszeichen.
        return active_project() is not None


def sch_signature(sch):
    pdir = os.path.dirname(sch)
    sig = []
    for f in sorted(glob.glob(os.path.join(pdir, "*.kicad_sch"))):
        try:
            sig.append((f, os.path.getmtime(f)))
        except OSError:
            pass
    return tuple(sig)


def export(cli, sch, out):
    for f in glob.glob(os.path.join(out, "*.svg")):
        os.remove(f)
    if not cli:
        return [], "kicad-cli nicht gefunden"
    p = subprocess.run([cli, "sch", "export", "svg", "--exclude-drawing-sheet",
                        "-o", out, sch], capture_output=True, text=True,
                       creationflags=NO_WINDOW)
    root = os.path.splitext(os.path.basename(sch))[0]
    sheets = []
    for f in sorted(glob.glob(os.path.join(out, "*.svg")),
                    key=lambda p: (os.path.basename(p) != root + ".svg", p)):
        name = os.path.splitext(os.path.basename(f))[0]
        name = "Root" if name == root else re.sub("^" + re.escape(root) + "-", "", name)
        with open(f, "rb") as fh:
            sheets.append((name, fh.read()))
    return sheets, (p.stderr.strip() if p.returncode else "")


def worker(fixed_sch, cli, out):
    last_seen = time.time()
    while True:
        try:
            if kicad_running():
                last_seen = time.time()
            elif time.time() - last_seen > IDLE_EXIT_S and not fixed_sch:
                os._exit(0)

            if fixed_sch:
                pro, sch = None, fixed_sch
            else:
                pro = active_project()
                sch = os.path.splitext(pro)[0] + ".kicad_sch" if pro else None

            if sch and os.path.exists(sch):
                sig = sch_signature(sch)
                if sch != state["sch"] or sig != state["sig"]:
                    time.sleep(0.3)  # Speichervorgang abwarten
                    sheets, err = export(cli, sch, out)
                    with lock:
                        state.update(project=pro, sch=sch, sig=sig, sheets=sheets,
                                     error=err, ver=state["ver"] + 1)
            elif state["sch"] is not None:
                with lock:
                    state.update(project=None, sch=None, sig=None, sheets=[],
                                 error="", ver=state["ver"] + 1)
        except Exception as e:  # weiter beobachten
            state["error"] = str(e)
        time.sleep(1)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Schaltplan Live</title>
<style>
html,body{margin:0;height:100%;background:#f5f4ee;font:13px system-ui,sans-serif}
#bar{position:fixed;top:0;left:0;right:0;display:flex;flex-wrap:wrap;gap:6px;align-items:center;
 padding:6px 10px;background:#222;color:#ddd;z-index:2}
#bar b{color:#fff}#st{margin-left:auto;opacity:.7}
#tabs button{background:#3a3a3a;color:#ddd;border:0;border-radius:3px;padding:3px 8px;cursor:pointer}
#tabs button.on{background:#c8a24a;color:#111}
#wrap{position:absolute;top:34px;bottom:0;left:0;right:0;overflow:auto}
#wrap svg{width:100%;height:auto;background:#fff}
#msg{padding:40px;color:#555}
</style></head><body>
<div id="bar"><b id="proj">&hellip;</b><span id="tabs"></span><span id="st"></span></div>
<div id="wrap"><div id="msg">Warte auf KiCad-Projekt &hellip;</div></div>
<script>
let ver=-1, sel=0, names=[];
function tabs(){const t=document.getElementById('tabs');t.innerHTML='';
 if(names.length<2)return;names.forEach((n,i)=>{const b=document.createElement('button');
 b.textContent=n;if(i===sel)b.className='on';b.onclick=()=>{sel=i;tabs();load();};t.appendChild(b);});}
async function load(){if(!names.length){document.getElementById('wrap').innerHTML=
 '<div id="msg">Kein offenes KiCad-Projekt gefunden.</div>';return;}
 const r=await fetch('/svg/'+sel+'?v='+ver);document.getElementById('wrap').innerHTML=await r.text();}
async function tick(){try{const s=await (await fetch('/state')).json();
 document.getElementById('proj').textContent=s.project||'kein Projekt';
 document.title=(s.project||'Schaltplan')+' \\u00b7 Live';
 if(s.ver!==ver){ver=s.ver;names=s.sheets;if(sel>=names.length)sel=0;tabs();await load();}
 document.getElementById('st').textContent=(s.error?'Fehler: '+s.error+' \\u00b7 ':'')+
  'Stand '+new Date().toLocaleTimeString();
}catch(e){document.getElementById('st').textContent='Server beendet (KiCad geschlossen?)';}}
setInterval(tick,1500);tick();
</script></body></html>""".encode()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # Browser hat die Anfrage abgebrochen

    def do_GET(self):
        path = self.path.split("?")[0]
        with lock:
            if path == "/state":
                name = None
                if state["sch"]:
                    name = os.path.splitext(os.path.basename(state["sch"]))[0]
                body = json.dumps({"ver": state["ver"], "project": name,
                                   "sheets": [n for n, _ in state["sheets"]],
                                   "error": html.escape(state["error"][:200])})
                return self.send(body.encode(), "application/json")
            m = re.fullmatch(r"/svg/(\d+)", path)
            if m:
                i = int(m.group(1))
                if i < len(state["sheets"]):
                    return self.send(state["sheets"][i][1], "image/svg+xml")
                return self.send(b"", "text/plain", 404)
        self.send(PAGE, "text/html; charset=utf-8")


class Server(http.server.ThreadingHTTPServer):
    # Windows erlaubt sonst mehreren Prozessen denselben Port (SO_REUSEADDR).
    allow_reuse_address = not IS_WIN
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--sch", help="festen Schaltplan anzeigen statt aktives Projekt")
    ap.add_argument("--kicad-cli", help="Pfad zu kicad-cli")
    a = ap.parse_args()
    out = output_dir()
    os.makedirs(out, exist_ok=True)
    try:
        srv = Server(("127.0.0.1", a.port), Handler)
    except OSError:
        print("Port %d belegt - Server laeuft bereits." % a.port, file=sys.stderr)
        return
    cli = find_kicad_cli(a.kicad_cli)
    threading.Thread(target=worker, args=(a.sch, cli, out), daemon=True).start()
    print("Live-Ansicht: http://localhost:%d (kicad-cli: %s)" % (a.port, cli), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
