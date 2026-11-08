"""Simuliert die Windows-/macOS-Zweige des Live-Ansicht-Plugins unter Linux."""
import importlib.util, json, os, subprocess, sys, tempfile, types

PLUG = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "plugins")
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise SystemExit("FEHLER: " + msg)
    ok += 1
    print("ok  ", msg)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


srv = load("srv", os.path.join(PLUG, "liveview_server.py"))
tmp = tempfile.mkdtemp()


def touch(p, content=""):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(content)


# ---- Konfigurationsordner -------------------------------------------------
env0 = dict(os.environ)
os.environ.pop("KICAD_CONFIG_HOME", None)
srv.IS_WIN, srv.IS_MAC = True, False
os.environ["APPDATA"] = os.path.join(tmp, "AppData", "Roaming")
check(srv.kicad_config_base() == os.path.join(tmp, "AppData", "Roaming", "kicad"), "Windows: %APPDATA%\\kicad")
srv.IS_WIN, srv.IS_MAC = False, True
check(srv.kicad_config_base() == os.path.expanduser("~/Library/Preferences/kicad"), "macOS: ~/Library/Preferences/kicad")
srv.IS_WIN = srv.IS_MAC = False
os.environ["KICAD_CONFIG_HOME"] = "/x/y"
check(srv.kicad_config_base() == "/x/y", "KICAD_CONFIG_HOME hat Vorrang")
os.environ.pop("KICAD_CONFIG_HOME")

# ---- Versionsordner + aktives Projekt ------------------------------------
base = os.path.join(tmp, "cfg", "kicad")
proA = os.path.join(tmp, "projA", "A.kicad_pro"); touch(proA)
proB = os.path.join(tmp, "projB", "B.kicad_pro"); touch(proB)
touch(os.path.join(tmp, "projB", "~B.kicad_pro.lck"))           # nur B offen
touch(os.path.join(base, "9.0", "kicad.json"), json.dumps({"system": {"file_history": [proA]}}))
touch(os.path.join(base, "10.0", "kicad.json"), json.dumps({"system": {"file_history": [proA, proB]}}))
os.environ["KICAD_CONFIG_HOME"] = base
check(srv.kicad_config_dirs()[0].endswith("10.0"), "neueste KiCad-Version zuerst (10.0 vor 9.0)")
check(srv.active_project() == proB, "aktives Projekt = erstes mit Lockdatei")
os.environ["KICAD_CONFIG_HOME"] = os.path.join(base, "10.0")
check(srv.kicad_config_dirs() == [os.path.join(base, "10.0")], "KICAD_CONFIG_HOME direkt auf Versionsordner")
os.environ.pop("KICAD_CONFIG_HOME")

# ---- kicad-cli-Suche ------------------------------------------------------
srv.shutil.which = lambda n: None
os.environ.pop("KICAD_LIVEVIEW_CLI", None)
pf = os.path.join(tmp, "Program Files")
for v in ("9.0", "10.0"):
    touch(os.path.join(pf, "KiCad", v, "bin", "kicad-cli.exe"))
os.environ["ProgramFiles"] = pf
srv.IS_WIN, srv.IS_MAC = True, False
check(srv.find_kicad_cli().endswith(os.path.join("10.0", "bin", "kicad-cli.exe")), "Windows: neuestes Program Files\\KiCad\\<ver>\\bin")
hint = os.path.join(tmp, "hint", "kicad-cli.exe"); touch(hint)
check(srv.find_kicad_cli(hint) == hint, "Hinweis vom Plugin hat Vorrang")
srv.IS_WIN, srv.IS_MAC = False, True
srv.glob.glob, real_glob = (lambda pat: [os.path.join(tmp, "mac", "kicad-cli")] if "KiCad.app" in pat else []), srv.glob.glob
touch(os.path.join(tmp, "mac", "kicad-cli"))
check(srv.find_kicad_cli() == os.path.join(tmp, "mac", "kicad-cli"), "macOS: KiCad.app/Contents/MacOS/kicad-cli")
srv.glob.glob = real_glob
srv.IS_WIN = srv.IS_MAC = False

# ---- Prozesserkennung -----------------------------------------------------
real_isdir, real_run = os.path.isdir, subprocess.run
srv.os.path.isdir = lambda p: False if p == "/proc/self" else real_isdir(p)


def fake_run(out):
    return lambda *a, **k: types.SimpleNamespace(stdout=out, returncode=0, stderr="")


srv.IS_WIN = True
srv.subprocess.run = fake_run('"System Idle Process","0","Services","0","8 K"\n'
                              '"kicad.exe","4711","Console","1","300.000 K"\n'
                              '"pythonw.exe","4800","Console","1","20.000 K"\n')
check(srv.kicad_running(), "Windows: kicad.exe in tasklist erkannt")
srv.subprocess.run = fake_run('"explorer.exe","1","Console","1","1 K"\n')
check(not srv.kicad_running(), "Windows: ohne KiCad -> nicht laufend")
srv.IS_WIN, srv.IS_MAC = False, True
srv.subprocess.run = fake_run("COMM\nlaunchd\n/Applications/KiCad/KiCad.app/Contents/MacOS/kicad\nFinder\n")
check(srv.kicad_running(), "macOS: kicad in ps erkannt")
srv.subprocess.run = fake_run("COMM\nlaunchd\nFinder\n")
check(not srv.kicad_running(), "macOS: ohne KiCad -> nicht laufend")


def boom(*a, **k):
    raise OSError("kein ps")


srv.subprocess.run = boom
srv.active_project = lambda: "/x.kicad_pro"
check(srv.kicad_running(), "Prozessliste nicht lesbar -> offenes Projekt zaehlt")
srv.os.path.isdir, srv.subprocess.run = real_isdir, real_run
srv.IS_WIN = srv.IS_MAC = False

# ---- Plugin: Interpreter + kicad-cli-Hinweis -------------------------------
sys.modules["pcbnew"] = types.SimpleNamespace(ActionPlugin=type("AP", (), {"register": lambda s: None}))
os.environ["XDG_RUNTIME_DIR"] = tmp
plg_src = open(os.path.join(PLUG, "__init__.py")).read().replace("    ensure_server()\nexcept", "    pass\nexcept")
plg = types.ModuleType("plg"); plg.__file__ = os.path.join(PLUG, "__init__.py")
exec(compile(plg_src, plg.__file__, "exec"), plg.__dict__)

win_bin = os.path.join(tmp, "KiCadWin", "bin")
touch(os.path.join(win_bin, "pythonw.exe")); touch(os.path.join(win_bin, "kicad-cli.exe"))
plg.IS_WIN = True
plg.sys = types.SimpleNamespace(executable=os.path.join(win_bin, "kicad.exe"), prefix=win_bin, exec_prefix=win_bin)
check(plg._python() == os.path.join(win_bin, "pythonw.exe"), "Windows: mitgeliefertes pythonw.exe")
check(plg._kicad_cli_hint() == os.path.join(win_bin, "kicad-cli.exe"), "Windows: kicad-cli neben KiCad")
plg.sys = types.SimpleNamespace(executable=os.path.join(win_bin, "python.exe"), prefix=win_bin, exec_prefix=win_bin)
check(plg._python() == os.path.join(win_bin, "pythonw.exe"), "Windows: python.exe -> pythonw.exe")

app = os.path.join(tmp, "Applications", "KiCad", "KiCad.app", "Contents")
fw = os.path.join(app, "Frameworks", "Python.framework", "Versions", "3.11")
touch(os.path.join(fw, "bin", "python3")); touch(os.path.join(app, "MacOS", "kicad-cli"))
plg.IS_WIN = False
plg.sys = types.SimpleNamespace(executable=os.path.join(app, "MacOS", "kicad"), prefix=fw, exec_prefix=fw)
check(plg._python() == os.path.join(fw, "bin", "python3"), "macOS: Python aus KiCad.app-Framework")
check(plg._kicad_cli_hint() == os.path.join(app, "MacOS", "kicad-cli"), "macOS: kicad-cli im App-Bundle")
plg.sys = types.SimpleNamespace(executable="/usr/bin/kicad", prefix="/usr", exec_prefix="/usr")
check(plg._python() == "/usr/bin/python3", "Linux: /usr/bin/python3")

os.environ.clear(); os.environ.update(env0)
print("\n%d Pruefungen bestanden" % ok)
