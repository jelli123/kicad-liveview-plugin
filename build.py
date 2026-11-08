#!/usr/bin/env python3
"""Baut das KiCad-PCM-Paket dist/schematic-liveview-<version>.zip.

Installation in KiCad: Plugin and Content Manager -> "Aus Datei installieren..."
"""
import json
import os
import struct
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")


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


def main():
    png(os.path.join(SRC, "plugins", "icon.png"), 24)
    png(os.path.join(SRC, "resources", "icon.png"), 64)
    meta = json.load(open(os.path.join(SRC, "metadata.json"), encoding="utf-8"))
    version = meta["versions"][0]["version"]
    os.makedirs(os.path.join(HERE, "dist"), exist_ok=True)
    out = os.path.join(HERE, "dist", "schematic-liveview-%s.zip" % version)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(SRC):
            for f in sorted(files):
                if f.endswith(".pyc") or "__pycache__" in root:
                    continue
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, SRC))
    print(out)
    for n in zipfile.ZipFile(out).namelist():
        print("  ", n)


if __name__ == "__main__":
    main()
