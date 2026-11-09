# Schaltplan Live-Ansicht (KiCad-Plugin)

**[English version below](#english)**

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

## Installieren und Updates

**Empfohlen – über das Repository (mit Update-Meldung):**

1. KiCad → *Plugin and Content Manager* → **Repositories verwalten…**
2. Neues Repository mit dieser URL hinzufügen:
   ```
   https://raw.githubusercontent.com/jelli123/kicad-liveview-plugin/main/pcm/repository.json
   ```
3. Repository oben im PCM auswählen, *Schaltplan Live-Ansicht* installieren,
   Änderungen anwenden.

KiCad meldet neue Versionen dann selbst; aktualisiert wird mit einem Klick im
PCM. Ein noch laufender Server älterer Version wird beim nächsten Laden des
Plugins automatisch beendet und neu gestartet, die Browseransicht lädt sich
danach selbst neu. Die laufende Version steht rechts in der Kopfzeile.

**Alternativ – aus Datei:** ZIP von der
[Release-Seite](https://github.com/jelli123/kicad-liveview-plugin/releases)
laden und im PCM über **Aus Datei installieren…** einspielen.

Zum Entfernen im PCM auf *Deinstallieren* klicken.

## Bedienung im Browser

| Aktion | Maus / Taste |
|---|---|
| Vergrößern / Verkleinern | **+** / **−** in der Kopfzeile, Tasten `+` / `-`, Strg+Mausrad |
| An Fenster anpassen | Knopf *An Fenster anpassen*, Taste `0`, Doppelklick |
| Originalgröße (100 %) | Klick auf die Prozentanzeige |
| Blattrahmen ein/aus | Knopf *Rahmen* (wird im Browser gemerkt) |
| Verschieben | Ziehen mit linker oder mittlerer Maustaste, Scrollbalken |
| Blatt wechseln | Reiter in der Kopfzeile |

Zoom und Ausschnitt bleiben beim Speichern in KiCad erhalten.

Sprache: Die Browseransicht ist deutsch, wenn der Browser Deutsch als
bevorzugte Sprache hat, sonst englisch. Der Toolbar-Knopf folgt der in KiCad
eingestellten Sprache.

## Bauen

```bash
python3 build.py
```

Erzeugt `dist/schematic-liveview-<version>.zip` und aktualisiert die
Repository-Dateien in `pcm/` (`repository.json`, `packages.json`,
`resources.zip`). Der Build ist reproduzierbar: Er packt nur von Git verwaltete
Dateien unter `src/`, unkomprimiert und mit festen Zeitstempeln, sodass lokal
und auf GitHub dieselbe SHA-256 entsteht. `python3 build.py --icons` erzeugt die
Icons neu.

## Neue Version veröffentlichen

1. Versionsnummer in `src/metadata.json` **und** `VERSION` in
   `src/plugins/liveview_server.py` erhöhen (der Build bricht bei Abweichung ab).
2. `python3 build.py`
3. Alles einschließlich `pcm/` committen, Tag setzen und pushen:
   ```bash
   git commit -am "Version X.Y.Z"
   git tag vX.Y.Z
   git push origin main vX.Y.Z
   ```

Die GitHub-Action [release.yml](.github/workflows/release.yml) prüft dann, dass
Tag und Version übereinstimmen, führt die Tests aus, baut das Paket, vergleicht
dessen SHA-256 mit `pcm/packages.json` und hängt das ZIP an ein neues Release.
Bis das Release fertig ist (ca. 1 min), sieht der PCM die neue Version schon,
kann sie aber noch nicht laden.

## Entwicklung

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

---

<a id="english"></a>

# Schematic Live View (KiCad plugin)

Shows the schematic of the project currently open in KiCad live in your browser
at <http://localhost:8765>. The view refreshes every time you save. All
hierarchical sheets are available as tabs.

## How it works

- KiCad loads the plugin as soon as its Python environment starts (at the
  latest when the PCB editor opens). This starts the server in the background.
- The server finds the active project on its own: the first entry of KiCad's
  file history that has a lock file `~<name>.kicad_pro.lck`. Switching projects
  is detected automatically. There is nothing to configure.
- When no KiCad process is running any more, the server exits after about 20 s.
- The toolbar button in the PCB editor starts the server if needed and opens
  the view in your default browser.
- Log: `kicad-liveview.log` in `$XDG_RUNTIME_DIR` (Linux) or the temp folder
  (Windows: `%TEMP%`, macOS: `$TMPDIR`)

## Platforms

| | Linux | Windows | macOS |
|---|---|---|---|
| Status | tested | untested | untested |
| KiCad settings | `~/.config/kicad/<ver>` | `%APPDATA%\kicad\<ver>` | `~/Library/Preferences/kicad/<ver>` |
| KiCad running? | `/proc` | `tasklist` | `ps` |
| `kicad-cli` | `PATH` | next to KiCad, else `Program Files\KiCad\<ver>\bin` | next to KiCad, else `/Applications/KiCad/KiCad.app/Contents/MacOS` |
| Python | system `python3` | bundled `pythonw.exe` | bundled Python framework |

`KICAD_CONFIG_HOME` is honoured. A different `kicad-cli` path can be set with
the environment variable `KICAD_LIVEVIEW_CLI`.

## Install and update

**Recommended – via the repository (with update notifications):**

1. KiCad → *Plugin and Content Manager* → **Manage Repositories…**
2. Add a new repository with this URL:
   ```
   https://raw.githubusercontent.com/jelli123/kicad-liveview-plugin/main/pcm/repository.json
   ```
3. Select the repository at the top of the PCM, install *Schematic Live View*,
   apply the pending changes.

KiCad then reports new versions itself; updating is one click in the PCM. A
still running server of an older version is stopped and restarted the next time
the plugin loads, and the browser view reloads by itself. The running version
is shown on the right of the header bar.

**Alternative – from file:** download the ZIP from the
[releases page](https://github.com/jelli123/kicad-liveview-plugin/releases)
and install it in the PCM with **Install from File…**.

To remove it, click *Uninstall* in the PCM.

## Using the browser view

| Action | Mouse / key |
|---|---|
| Zoom in / out | **+** / **−** in the header, keys `+` / `-`, Ctrl+mouse wheel |
| Fit to window | *Fit to window* button, key `0`, double-click |
| Actual size (100 %) | click the percentage display |
| Drawing sheet on/off | *Frame* button (remembered by the browser) |
| Pan | drag with left or middle mouse button, scroll bars |
| Switch sheet | tabs in the header |

Zoom and position are kept when you save in KiCad.

Language: the browser view is German if German is the browser's preferred
language, English otherwise. The toolbar button follows KiCad's language
setting.

## Building

```bash
python3 build.py
```

Creates `dist/schematic-liveview-<version>.zip` and updates the repository
files in `pcm/` (`repository.json`, `packages.json`, `resources.zip`). The build
is reproducible: it packs only Git-tracked files under `src/`, uncompressed and
with fixed timestamps, so a local build and the GitHub build produce the same
SHA-256. `python3 build.py --icons` regenerates the icons.

## Publishing a new version

1. Bump the version in `src/metadata.json` **and** `VERSION` in
   `src/plugins/liveview_server.py` (the build stops if they differ).
2. `python3 build.py`
3. Commit everything including `pcm/`, tag and push:
   ```bash
   git commit -am "Version X.Y.Z"
   git tag vX.Y.Z
   git push origin main vX.Y.Z
   ```

The GitHub action [release.yml](.github/workflows/release.yml) then checks that
tag and version match, runs the tests, builds the package, compares its SHA-256
with `pcm/packages.json` and attaches the ZIP to a new release. Until the
release is done (about 1 min) the PCM already sees the new version but cannot
download it yet.

## Development

Tests (also simulate the Windows and macOS code paths on Linux):

```bash
python3 tests/test_platforms.py
```

Manually without KiCad (e.g. for testing):

```bash
python3 src/plugins/liveview_server.py --sch /path/to/project.kicad_sch
```

Requirements: KiCad 9 or newer with Python plugin support (SWIG action
plugins); on Linux also `python3`.

## License

[LGPL-3.0](LICENSE)
