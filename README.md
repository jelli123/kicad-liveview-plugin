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
| Verschieben | Ziehen mit linker oder mittlerer Maustaste, Scrollbalken |
| Blatt wechseln | Reiter in der Kopfzeile |

Zoom und Ausschnitt bleiben beim Speichern in KiCad erhalten.

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
