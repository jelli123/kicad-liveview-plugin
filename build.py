#!/usr/bin/env python3
"""Baut das KiCad-PCM-Paket und die Repository-Dateien.

    python3 build.py           Paket bauen, pcm/ aktualisieren
    python3 build.py --check   nur pruefen, ob das Paket zu pcm/packages.json passt (CI)
    python3 build.py --icons   Icons neu erzeugen

Ergebnis:
    dist/schematic-liveview-<version>.zip   Paket (Release-Asset, "Aus Datei installieren")
    pcm/repository.json                     URL zum Eintragen im PCM
    pcm/packages.json                       Paketliste mit allen Versionen
    pcm/resources.zip                       Icon fuer die PCM-Liste

Der Build ist reproduzierbar (feste Zeitstempel, unkomprimiert, nur von Git
verwaltete Dateien), damit lokal und in der GitHub-Action dieselbe
SHA-256 entsteht.
"""
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
PCM = os.path.join(HERE, "pcm")
DIST = os.path.join(HERE, "dist")

GITHUB = "jelli123/kicad-liveview-plugin"
RAW = "https://raw.githubusercontent.com/%s/main/pcm/" % GITHUB
DOWNLOAD = "https://github.com/%s/releases/download/v{v}/schematic-liveview-{v}.zip" % GITHUB
ZIP_DATE = (2020, 1, 1, 0, 0, 0)


def png(path, size):
    """Einfaches Icon: dunkles Feld, gelbe Leitung mit Bauteil, gruener Punkt."""
    bg, fg, ok = (43, 43, 43), (200, 162, 74), (90, 190, 110)
    s = size / 24.0
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            u, v = x / s, y / s
            c, a = bg, 255
            r = 3.0  # abgerundete Ecken
            cx = min(max(u, r), 24 - r)
            cy = min(max(v, r), 24 - r)
            if (u - cx) ** 2 + (v - cy) ** 2 > r * r:
                a = 0
            elif 11 <= v <= 13 and (3 <= u <= 8 or 16 <= u <= 21):
                c = fg  # Leitung
            elif 8 <= u <= 16 and 9 <= v <= 15 and not (9.5 <= u <= 14.5 and 10.5 <= v <= 13.5):
                c = fg  # Bauteilkoerper
            elif (u - 18.5) ** 2 + (v - 5.5) ** 2 <= 4:
                c = ok  # "live"-Punkt
            row += bytes(c) + bytes([a])
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    data = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def source_files():
    """Paketinhalt: von Git verwaltete Dateien unter src/ (ohne Git: alle)."""
    try:
        out = subprocess.run(["git", "ls-files", "-z", "src"], cwd=HERE, check=True,
                             capture_output=True, text=True).stdout
        files = [os.path.join(HERE, p) for p in out.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        files = [os.path.join(r, f) for r, _, fs in os.walk(SRC) for f in fs]
    return sorted(f for f in files if os.path.isfile(f) and not f.endswith(".pyc"))


def write_zip(out, entries):
    """entries: [(name im Archiv, Bytes)] -> reproduzierbares ZIP."""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for name, data in entries:
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.external_attr = 0o644 << 16
            z.writestr(info, data)


def read(path):
    with open(path, "rb") as f:
        return f.read()


def sha256(path):
    return hashlib.sha256(read(path)).hexdigest()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    """Schreibt nur bei inhaltlicher Aenderung; liefert True, wenn geschrieben."""
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    if os.path.exists(path) and read(path).decode("utf-8") == text:
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def stamp(entry, path):
    """sha256 und Zeitstempel fuer einen Eintrag in repository.json."""
    digest = sha256(path)
    if entry.get("sha256") == digest:
        return entry
    now = int(time.time())
    return {"url": entry["url"], "sha256": digest, "update_timestamp": now,
            "update_time_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now))}


def main():
    check = "--check" in sys.argv
    if "--icons" in sys.argv:
        png(os.path.join(SRC, "plugins", "icon.png"), 24)
        png(os.path.join(SRC, "resources", "icon.png"), 64)

    meta = load_json(os.path.join(SRC, "metadata.json"), None)
    version = meta["versions"][0]["version"]
    m = re.search(r'^VERSION = "([^"]+)"',
                  read(os.path.join(SRC, "plugins", "liveview_server.py")).decode(), re.M)
    if not m or m.group(1) != version:
        raise SystemExit("Version in liveview_server.py (%s) passt nicht zu metadata.json (%s)"
                         % (m and m.group(1), version))

    # Paket
    os.makedirs(DIST, exist_ok=True)
    pkg = os.path.join(DIST, "schematic-liveview-%s.zip" % version)
    entries = [(os.path.relpath(f, SRC).replace(os.sep, "/"), read(f)) for f in source_files()]
    write_zip(pkg, entries)
    digest = sha256(pkg)
    print(pkg)
    for name, _ in entries:
        print("  ", name)
    print("   sha256", digest)

    pkgs_path = os.path.join(PCM, "packages.json")
    packages = load_json(pkgs_path, {"packages": []})
    old = next((p for p in packages["packages"] if p["identifier"] == meta["identifier"]), {})
    old_versions = {v["version"]: v for v in old.get("versions", [])}

    if check:
        known = old_versions.get(version, {}).get("download_sha256")
        if known != digest:
            raise SystemExit("pcm/packages.json passt nicht zum Paket %s (erwartet %s, gebaut %s).\n"
                             "Lokal 'python3 build.py' ausfuehren und pcm/ committen."
                             % (version, known, digest))
        print("pcm/packages.json passt zu Version", version)
        return

    # packages.json: aktuelle Version neu, aeltere Versionen behalten
    ver = dict(meta["versions"][0])
    ver.update(download_url=DOWNLOAD.format(v=version), download_sha256=digest,
               download_size=os.path.getsize(pkg),
               install_size=sum(len(d) for _, d in entries))
    old_versions[version] = ver
    entry = {k: v for k, v in meta.items() if k not in ("$schema", "versions")}
    entry["versions"] = sorted(old_versions.values(),
                               key=lambda v: [int(n) for n in re.findall(r"\d+", v["version"])],
                               reverse=True)
    packages["packages"] = [p for p in packages["packages"]
                            if p["identifier"] != meta["identifier"]] + [entry]
    os.makedirs(PCM, exist_ok=True)
    save_json(pkgs_path, packages)

    # resources.zip: Icon unter <identifier>/icon.png
    res_path = os.path.join(PCM, "resources.zip")
    write_zip(res_path, [(meta["identifier"] + "/icon.png",
                          read(os.path.join(SRC, "resources", "icon.png")))])

    # repository.json: Zeitstempel nur bei geaenderten Dateien erneuern
    repo_path = os.path.join(PCM, "repository.json")
    repo = load_json(repo_path, {})
    repo = {
        "$schema": "https://go.kicad.org/pcm/schemas/v1#/definitions/Repository",
        "name": "jelli123 KiCad-Plugins",
        "maintainer": {"name": meta["author"]["name"],
                       "contact": {"web": "https://github.com/" + GITHUB}},
        "packages": stamp(repo.get("packages", {"url": RAW + "packages.json"}), pkgs_path),
        "resources": stamp(repo.get("resources", {"url": RAW + "resources.zip"}), res_path),
    }
    save_json(repo_path, repo)
    print("PCM-Repository:", RAW + "repository.json")


if __name__ == "__main__":
    main()
