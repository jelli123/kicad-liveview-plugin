#!/usr/bin/env python3
"""KiCad Schaltplan-Live-Ansicht.

Kleiner HTTP-Server, der den Schaltplan des aktuell in KiCad geoeffneten
Projekts per kicad-cli als SVG exportiert und im Browser anzeigt. Die Seite
aktualisiert sich selbst, sobald eine .kicad_sch-Datei gespeichert wird.

- Offene Projekte (mehrere KiCad-Instanzen moeglich): Projekte mit
  Lockdatei (~<name>.kicad_pro.lck) aus den Ordnern, die das Plugin jeder
  Instanz meldet, den Arbeitsordnern der KiCad-Prozesse (Linux) und der
  KiCad-Dateihistorie (kicad.json). Die Seite bietet eine Projektauswahl.
- Beendet sich selbst, wenn kein KiCad-Prozess mehr laeuft.
- Startet nur einmal: ist der Port belegt, endet der zweite Start sofort.
- Linux, Windows und macOS.
"""
import argparse
import glob
import hashlib
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
import urllib.parse

VERSION = "1.3.0"
KICAD_PROCS = {"kicad", "eeschema", "pcbnew"}
IDLE_EXIT_S = 20
REGISTER_TTL_S = 30   # Meldung eines Plugins gilt so lange (Heartbeat alle 5 s)
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
# Unter Windows kein Konsolenfenster fuer Hilfsprozesse aufblitzen lassen.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0

state = {
    "projects": {},       # id -> Projekt (siehe new_project)
    "seq": 0,             # Zaehler fuer die Reihenfolge (neueste zuerst)
    "active": None,       # zuletzt per Toolbar-Knopf gewaehltes Projekt
    "registered": {},     # Ordner -> Zeitpunkt der letzten Plugin-Meldung
    "error": "",          # allgemeiner Fehler des Beobachters
    "frame": True,        # Blattrahmen mit exportieren
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
def _is_open(pro):
    pdir, name = os.path.split(pro)
    return (pro.endswith(".kicad_pro") and os.path.exists(pro)
            and os.path.exists(os.path.join(pdir, "~" + name + ".lck")))


def history_projects():
    """Offene Projekte aus der KiCad-Dateihistorie (nur eine Instanz schreibt sie)."""
    for d in kicad_config_dirs():
        try:
            with open(os.path.join(d, "kicad.json"), encoding="utf-8") as f:
                hist = json.load(f).get("system", {}).get("file_history", [])
        except (OSError, ValueError):
            continue
        found = [p for p in hist if _is_open(p)]
        if found:
            return found
    return []


def active_project():
    found = history_projects()
    return found[0] if found else None


def projects_in(d):
    """Offene Projekte (mit Lockdatei) in einem Ordner."""
    out = []
    for lck in sorted(glob.glob(os.path.join(glob.escape(d), "~*.kicad_pro.lck"))):
        pro = os.path.join(d, os.path.basename(lck)[1:-4])
        if _is_open(pro):
            out.append(pro)
    return out


def process_dirs():
    """Arbeitsordner der KiCad-Prozesse (nur Linux; KiCad wechselt in den Projektordner)."""
    dirs = []
    for comm in glob.glob("/proc/[0-9]*/comm"):
        try:
            with open(comm) as f:
                if f.read().strip().lower() not in KICAD_PROCS:
                    continue
            dirs.append(os.readlink(os.path.join(os.path.dirname(comm), "cwd")))
        except OSError:
            pass
    return dirs


def open_projects():
    """Alle offenen Projekte, ohne Duplikate."""
    now = time.time()
    with lock:
        reg = [d for d, t in state["registered"].items() if now - t < REGISTER_TTL_S]
    cands = []
    for d in reg + process_dirs():
        cands += projects_in(d)
    cands += history_projects()
    seen, out = set(), []
    for p in cands:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            out.append(os.path.abspath(p))
    return out


def project_id(path):
    return hashlib.sha1(os.path.normcase(path).encode("utf-8")).hexdigest()[:10]


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
        return active_project() is not None or bool(state["projects"])


def sch_signature(sch):
    pdir = os.path.dirname(sch)
    sig = []
    for f in sorted(glob.glob(os.path.join(pdir, "*.kicad_sch"))):
        try:
            sig.append((f, os.path.getmtime(f)))
        except OSError:
            pass
    return tuple(sig)


def export(cli, sch, out, frame=True):
    for f in glob.glob(os.path.join(out, "*.svg")):
        os.remove(f)
    if not cli:
        return [], "kicad-cli not found"  # Browser uebersetzt
    cmd = [cli, "sch", "export", "svg", "-o", out, sch]
    if not frame:
        cmd.insert(4, "--exclude-drawing-sheet")
    p = subprocess.run(cmd, capture_output=True, text=True,
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
                cands = [(None, os.path.abspath(fixed_sch))]
            else:
                cands = [(p, os.path.splitext(p)[0] + ".kicad_sch") for p in open_projects()]
            cands = [(p, sch) for p, sch in cands if os.path.exists(sch)]
            ids = {project_id(sch): (p, sch) for p, sch in cands}

            with lock:
                for i in list(state["projects"]):
                    if i not in ids:  # Projekt geschlossen
                        del state["projects"][i]
                        shutil.rmtree(os.path.join(out, i), ignore_errors=True)
                for i, (p, sch) in reversed(list(ids.items())):
                    if i not in state["projects"]:  # neu: vor die bisherigen
                        state["seq"] += 1
                        state["projects"][i] = dict(project=p, sch=sch, sig=None, ver=0,
                                                    sheets=[], error="", seq=state["seq"])
            for i, (p, sch) in ids.items():
                prj = state["projects"].get(i)
                frame = state["frame"]
                sig = (frame,) + sch_signature(sch)  # Umschalten des Rahmens = neu exportieren
                if prj is None or sig == prj["sig"]:
                    continue
                time.sleep(0.3)  # Speichervorgang abwarten
                d = os.path.join(out, i)
                os.makedirs(d, exist_ok=True)
                sheets, err = export(cli, sch, d, frame)
                with lock:
                    prj.update(sig=sig, sheets=sheets, error=err, ver=prj["ver"] + 1)
            state["error"] = ""
        except Exception as e:  # weiter beobachten
            state["error"] = str(e)
        time.sleep(1)


def selected(pid):
    """Gewuenschtes Projekt, sonst das zuletzt gewaehlte bzw. zuletzt geoeffnete."""
    prjs = state["projects"]
    for i in (pid, state["active"]):
        if i in prjs:
            return i
    return max(prjs, key=lambda i: prjs[i]["seq"]) if prjs else None


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Schematic Live</title>
<style>
html,body{margin:0;height:100%;background:#f5f4ee;font:13px system-ui,sans-serif}
body{display:flex;flex-direction:column}
#bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:6px 10px;background:#222;color:#ddd}
#bar b{color:#fff}
#pj{background:#3a3a3a;color:#fff;border:0;border-radius:3px;padding:3px 6px;font:inherit;font-weight:bold;max-width:40ch}#st{margin-left:auto;opacity:.7}#ver{opacity:.5}
#bar button{background:#3a3a3a;color:#ddd;border:0;border-radius:3px;padding:3px 8px;cursor:pointer;font:inherit}
#bar button:hover{background:#4a4a4a}
#tabs button.on,#bar #fr.on{background:#c8a24a;color:#111}#bar #fr:disabled{opacity:.5;cursor:wait}
#zoom{display:flex;gap:4px;align-items:center}
#zoom button{min-width:26px}#bar #zl{min-width:48px;background:none;opacity:.8}#bar #zl:hover{background:#3a3a3a;opacity:1}
#wrap{flex:1;min-height:0;overflow:auto;display:flex;cursor:grab}
#wrap.drag{cursor:grabbing;user-select:none}
#wrap svg{flex:none;margin:auto;background:#fff;box-shadow:0 0 6px rgba(0,0,0,.15)}
#msg{padding:40px;color:#555}
</style></head><body>
<div id="bar"><b id="proj">&hellip;</b><select id="pj" hidden></select><span id="tabs"></span>
<span id="zoom"><button id="zo">&minus;</button><button id="zl"></button>
<button id="zi">+</button><button id="zf"></button></span>
<button id="fr"></button>
<span id="st"></span><span id="ver">v%VERSION%</span></div>
<div id="wrap"><div id="msg"></div></div>
<script>
// Sprache: Deutsch, wenn der Browser Deutsch bevorzugt, sonst Englisch.
const DE=/^de/i.test((navigator.languages&&navigator.languages[0])||navigator.language||'');
const T=DE?{fr:'Rahmen',frt:'Blattrahmen ein-/ausblenden',zo:'Verkleinern (-)',zl:'Originalgröße 100 %',zi:'Vergrößern (+)',zf:'An Fenster anpassen',zfk:'An Fenster anpassen (0, Doppelklick)',
 wait:'Warte auf KiCad-Projekt …',pj:'Projekt wählen (offene KiCad-Projekte)',none:'Kein offenes KiCad-Projekt gefunden.',noproj:'kein Projekt',
 sch:'Schaltplan',err:'Fehler: ',at:'Stand ',gone:'Server beendet (KiCad geschlossen?)',
 'kicad-cli not found':'kicad-cli nicht gefunden'}
:{fr:'Frame',frt:'Show/hide drawing sheet',zo:'Zoom out (-)',zl:'Actual size 100 %',zi:'Zoom in (+)',zf:'Fit to window',zfk:'Fit to window (0, double-click)',
 wait:'Waiting for KiCad project …',pj:'Choose project (open KiCad projects)',none:'No open KiCad project found.',noproj:'no project',
 sch:'Schematic',err:'Error: ',at:'Updated ',gone:'Server stopped (KiCad closed?)'};
document.documentElement.lang=DE?'de':'en';
document.getElementById('zo').title=T.zo;document.getElementById('zl').title=T.zl;document.getElementById('zi').title=T.zi;
document.getElementById('zf').title=T.zfk;document.getElementById('zf').textContent=T.zf;
document.getElementById('msg').textContent=T.wait;
const FR=document.getElementById('fr');FR.textContent=T.fr;FR.title=T.frt;
let frame=null;  // gewuenschter Rahmen-Zustand, im Browser gemerkt
try{const v=localStorage.getItem('frame');if(v!==null)frame=v==='1';}catch(e){}
function setFrame(on){frame=on;try{localStorage.setItem('frame',on?'1':'0');}catch(e){}
 FR.disabled=true;fetch('/frame/'+(on?1:0),{method:'POST'});}
FR.onclick=()=>setFrame(!FR.classList.contains('on'));
const W=document.getElementById('wrap'), MM=96/25.4, PAD=16, VER='%VERSION%';
let ver=-1, sel=0, names=[], scale=1, fit=true;
// Projekt-ID aus der URL (?p=...); leer = zuletzt gewaehltes/geoeffnetes Projekt.
let P=new URLSearchParams(location.search).get('p')||'', cur=null, plist='';
const PJ=document.getElementById('pj');PJ.title=T.pj;
PJ.onchange=()=>{P=PJ.value;history.replaceState(null,'','?p='+encodeURIComponent(P));tick();};
function svg(){return W.querySelector('svg');}
function dims(s){const v=s.viewBox&&s.viewBox.baseVal;
 if(v&&v.width&&v.height)return [v.width,v.height];
 if(!s._d){const r=s.getBoundingClientRect();s._d=[r.width/MM,r.height/MM];}return s._d;}
function fitScale(){const s=svg();if(!s)return 1;const [w,h]=dims(s);
 return Math.max(0.01,Math.min((W.clientWidth-PAD)/w,(W.clientHeight-PAD)/h));}
function apply(){const s=svg();if(!s){document.getElementById('zl').textContent='';return;}
 if(fit)scale=fitScale();const [w,h]=dims(s);
 s.style.width=(w*scale)+'px';s.style.height=(h*scale)+'px';
 document.getElementById('zl').textContent=Math.round(scale/MM*100)+'%';}
function zoomAt(f,cx,cy){const s=svg();if(!s)return;
 if(cx===undefined){cx=W.clientWidth/2;cy=W.clientHeight/2;}
 const wr=W.getBoundingClientRect(), r=s.getBoundingClientRect();
 const px=(cx-(r.left-wr.left))/scale, py=(cy-(r.top-wr.top))/scale;
 const fs=fitScale();scale=Math.min(MM*40,Math.max(fs/4,scale*f));fit=false;apply();
 const r2=s.getBoundingClientRect();
 W.scrollLeft+=(r2.left-wr.left)+px*scale-cx;W.scrollTop+=(r2.top-wr.top)+py*scale-cy;}
function fitView(){fit=true;apply();}
document.getElementById('zi').onclick=()=>zoomAt(1.25);
document.getElementById('zo').onclick=()=>zoomAt(1/1.25);
document.getElementById('zf').onclick=fitView;
document.getElementById('zl').onclick=()=>zoomAt(MM/scale);
W.addEventListener('wheel',e=>{if(!e.ctrlKey)return;e.preventDefault();
 let d=e.deltaY*(e.deltaMode===1?33:e.deltaMode===2?400:1);d=Math.max(-200,Math.min(200,d));
 const wr=W.getBoundingClientRect();zoomAt(Math.exp(-d*0.002),e.clientX-wr.left,e.clientY-wr.top);},{passive:false});
document.addEventListener('keydown',e=>{if(e.altKey||e.metaKey)return;
 if(e.key==='+'||e.key==='='){zoomAt(1.25);e.preventDefault();}
 else if(e.key==='-'||e.key==='_'){zoomAt(1/1.25);e.preventDefault();}
 else if(e.key==='0'){fitView();e.preventDefault();}});
let drag=null;
W.addEventListener('mousedown',e=>{if(e.button>1)return;e.preventDefault();
 drag={x:e.clientX,y:e.clientY,l:W.scrollLeft,t:W.scrollTop};W.classList.add('drag');});
addEventListener('mousemove',e=>{if(!drag)return;
 W.scrollLeft=drag.l-(e.clientX-drag.x);W.scrollTop=drag.t-(e.clientY-drag.y);});
addEventListener('mouseup',()=>{drag=null;W.classList.remove('drag');});
W.addEventListener('dblclick',fitView);
addEventListener('resize',()=>{if(fit)apply();});
function tabs(){const t=document.getElementById('tabs');t.innerHTML='';
 if(names.length<2)return;names.forEach((n,i)=>{const b=document.createElement('button');
 b.textContent=n;if(i===sel)b.className='on';b.onclick=()=>{sel=i;fit=true;tabs();load();};t.appendChild(b);});}
async function load(){if(!names.length){W.innerHTML=
 '<div id="msg"></div>';W.firstChild.textContent=T.none;apply();return;}
 const r=await fetch('/svg/'+cur+'/'+sel+'?v='+ver);const txt=await r.text();
 const l=W.scrollLeft,t=W.scrollTop;W.innerHTML=txt;apply();
 if(!fit){W.scrollLeft=l;W.scrollTop=t;}}
async function tick(){try{const s=await (await fetch('/state'+(P?'?p='+encodeURIComponent(P):''))).json();
 if(s.version!==VER){location.reload();return;}
 if(s.id!==cur){cur=s.id;ver=-1;sel=0;fit=true;}
 const pl=JSON.stringify(s.projects);if(pl!==plist){plist=pl;PJ.innerHTML='';
  s.projects.forEach(p=>{const o=document.createElement('option');o.value=p.id;o.textContent=p.name;o.title=p.path;PJ.appendChild(o);});}
 PJ.value=s.id||'';PJ.hidden=s.projects.length<2;document.getElementById('proj').hidden=!PJ.hidden;
 if(frame!==null&&frame!==s.frame)setFrame(frame);
 else FR.disabled=s.frame!==s.frame_shown&&!!s.project;
 FR.classList.toggle('on',frame!==null?frame:s.frame);FR.hidden=!s.project;
 document.getElementById('proj').textContent=s.project||T.noproj;
 document.title=(s.project||T.sch)+' \\u00b7 Live';
 if(s.ver!==ver){ver=s.ver;names=s.sheets;if(sel>=names.length)sel=0;tabs();await load();}
 document.getElementById('st').textContent=(s.error?T.err+(T[s.error]||s.error)+' \\u00b7 ':'')+
  T.at+new Date().toLocaleTimeString();
}catch(e){document.getElementById('st').textContent=T.gone;}}
setInterval(tick,1500);tick();
</script></body></html>""".replace("%VERSION%", VERSION).encode()


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
        url = urllib.parse.urlsplit(self.path)
        path, q = url.path, urllib.parse.parse_qs(url.query)
        with lock:
            if path == "/state":
                prjs = state["projects"]
                order = sorted(prjs, key=lambda i: -prjs[i]["seq"])
                sel = selected((q.get("p") or [None])[0])
                prj = prjs.get(sel) or dict(sch=None, sig=None, ver=0, sheets=[], error="")
                name = lambda p: os.path.splitext(os.path.basename(p["sch"]))[0]
                body = json.dumps({"version": VERSION, "id": sel, "ver": prj["ver"],
                                   "project": name(prj) if prj["sch"] else None,
                                   "projects": [{"id": i, "name": name(prjs[i]),
                                                 "path": prjs[i]["sch"]} for i in order],
                                   "sheets": [n for n, _ in prj["sheets"]],
                                   "frame": state["frame"],
                                   "frame_shown": bool(prj["sig"] and prj["sig"][0]),
                                   "error": html.escape((state["error"] or prj["error"])[:200])})
                return self.send(body.encode(), "application/json")
            m = re.fullmatch(r"/svg/(\w+)/(\d+)", path)
            if m:
                prj, i = state["projects"].get(m.group(1)), int(m.group(2))
                if prj and i < len(prj["sheets"]):
                    return self.send(prj["sheets"][i][1], "image/svg+xml")
                return self.send(b"", "text/plain", 404)
        self.send(PAGE, "text/html; charset=utf-8")

    def do_POST(self):
        # Vom Plugin genutzt, um einen veralteten Server abzuloesen.
        if self.path == "/quit":
            self.send(b"bye", "text/plain")
            threading.Timer(0.2, os._exit, (0,)).start()
        elif self.path.startswith("/register?"):
            # Plugin meldet den Projektordner seiner KiCad-Instanz (Heartbeat).
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1])
            d = (q.get("dir") or [""])[0]
            pid = None
            if d and os.path.isdir(d):
                now = time.time()
                with lock:
                    reg = state["registered"]
                    for k in [k for k, t in reg.items() if now - t > REGISTER_TTL_S]:
                        del reg[k]
                    reg[os.path.abspath(d)] = now
                pro = (q.get("pro") or [""])[0]
                if pro:
                    pid = project_id(os.path.abspath(os.path.splitext(pro)[0] + ".kicad_sch"))
                    if q.get("activate"):
                        state["active"] = pid
            self.send((pid or "").encode(), "text/plain")
        elif self.path in ("/frame/0", "/frame/1"):
            with lock:
                state["frame"] = self.path.endswith("1")
            self.send(b"ok", "text/plain")
        else:
            self.send(b"", "text/plain", 404)


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
