# Schaltplan Live-Ansicht (KiCad-Plugin)

Zeigt den Schaltplan des gerade in KiCad geöffneten Projekts live im Browser
unter <http://localhost:8765>. Die Ansicht aktualisiert sich bei jedem Speichern.
Alle Hierarchie-Blätter sind über Reiter erreichbar.

## Funktionsweise

- KiCad lädt das Plugin, sobald seine Python-Umgebung startet (spätestens beim
  Öffnen des PCB-Editors). Dabei wird der Server im Hintergrund gestartet.
- Der Server ermittelt das aktive Projekt selbst: den ersten Eintrag der
  KiCad-Dateihistorie, für den eine Lockdatei `~<name>.kicad_pro.lck` existiert.
  Ein Projektwechsel wird automatisch erkannt. Es gibt keine Konfiguration.
- Läuft kein KiCad-Prozess mehr, beendet sich der Server nach etwa 20 s.
- Der Toolbar-Knopf im PCB-Editor startet den Server bei Bedarf und öffnet die
  Ansicht im Standardbrowser.
- Log: `kicad-liveview.log` in `$XDG_RUNTIME_DIR` (Linux) bzw. im Temp-Ordner
  (Windows: `%TEMP%`, macOS: `$TMPDIR`)

## Plattformen

| | Linux | Windows | macOS |
|---|---|---|---|
| Status | getestet | ungetestet | ungetestet |
| KiCad-Einstellungen | `~/.config/kicad/<ver>` | `%APPDATA%\kicad\<ver>` | `~/Library/Preferences/kicad/<ver>` |
| KiCad läuft? | `/proc` | `tasklist` | `ps` |
| `kicad-cli` | `PATH` | neben KiCad, sonst `Program Files\KiCad\<ver>\bin` | neben KiCad, sonst `/Applications/KiCad/KiCad.app/Contents/MacOS` |
| Python | System-`python3` | mitgeliefertes `pythonw.exe` | mitgeliefertes Python-Framework |

`KICAD_CONFIG_HOME` wird berücksichtigt. Ein abweichender `kicad-cli`-Pfad lässt
sich über die Umgebungsvariable `KICAD_LIVEVIEW_CLI` setzen.

## Bauen / Installieren / Entfernen

```bash
python3 build.py
```

KiCad → *Plugin and Content Manager* → **Aus Datei installieren…** →
`dist/schematic-liveview-<version>.zip`. Zum Entfernen im PCM auf
*Deinstallieren* klicken.

Tests (simulieren unter Linux auch die Windows- und macOS-Zweige):

```bash
python3 tests/test_platforms.py
```

Manuell ohne KiCad (z. B. zum Testen):

```bash
python3 src/plugins/liveview_server.py --sch /pfad/zum/projekt.kicad_sch
```

Voraussetzungen: KiCad 9 oder neuer mit Python-Plugin-Unterstützung (SWIG
Action Plugins); unter Linux zusätzlich `python3`.

## Lizenz

[LGPL-3.0](LICENSE)
