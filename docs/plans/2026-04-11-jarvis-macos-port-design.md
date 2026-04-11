# Jarvis macOS-Portierung — Design

**Datum:** 2026-04-11
**Autor:** Mario Pustan
**Status:** Validiert, bereit zur Umsetzung
**Upstream:** `Julian-Ivanov/jarvis-voice-assistant`
**Ziel-Repo:** `Maure71/jarvis`

## Ziel

Jarvis (FastAPI + Claude Haiku + ElevenLabs + Playwright) auf macOS lauffähig machen, ohne Features zu verlieren. Der Upstream ist Windows-only (PowerShell, Win32 MoveWindow). Diese Portierung ersetzt die Windows-Pfade durch macOS-Äquivalente und behält alles andere bei.

## Nicht-Ziele

- Keine neuen Features. Reiner Port.
- Keine Cross-Platform-Abstraktionsschicht. macOS-only ist explizit OK.
- Kein Porcupine-Wake-Word. Double-Clap bleibt Trigger.
- Keine Datenbank. In-Memory-Konversations­historie genügt.

## Feature-Scope

Alle vier Kernbereiche bleiben:

1. Voice-In/Out + Claude-Brain (FastAPI + Web Speech API + ElevenLabs)
2. Double-Clap Workspace-Launcher (Apple Music statt Spotify, AC/DC-Megahits @ 30%)
3. Browser-Automation via Playwright ("such nach X")
4. Screenshot + Claude Vision + Tages-Briefing mit Wetter und Obsidian-Tasks

## Was im Upstream schon passt

Beim Durchlesen des Upstream-Codes zeigt sich: die Portierung ist kleiner als zunächst gedacht.

| Datei | Status |
| --- | --- |
| `server.py` | Unverändert. System-Prompt ist bereits deutsch, siezt "Sir", Butler-Persona exakt wie gewünscht. |
| `browser_tools.py` | Unverändert. Playwright ist cross-platform. |
| `screen_capture.py` | Unverändert. `PIL.ImageGrab` funktioniert nativ auf macOS via Quartz. |
| `frontend/*` | Unverändert. Web Speech API läuft in Chrome. |
| `scripts/clap-trigger.py` | Eine Zeile: der `subprocess.Popen(["powershell", ...])` wird zu `subprocess.Popen(["bash", SCRIPT_PATH])`. |
| `requirements.txt` | Unverändert. Alle Deps laufen auf macOS. |

## Was portiert werden muss

### 1. `scripts/launch-session.ps1` → `launch_session.sh` + `launch_session.applescript`

Der PowerShell-Launcher startet Apps und snapped Fenster via Win32 `MoveWindow`. Ersatz:

**`launch_session.sh`** — Orchestrierung via `open -a`, Apple Music wird durch einen dedizierten `play_music.applescript` angestoßen:
```bash
#!/usr/bin/env bash
set -euo pipefail

JARVIS_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Server im Hintergrund starten
osascript -e "tell application \"Terminal\" to do script \"cd $JARVIS_DIR && source .venv/bin/activate && python server.py\""

# Apps starten
open -a "Visual Studio Code" "$JARVIS_DIR"
open -a "Obsidian"

# Apple Music: AC/DC shuffled auf 30% Lautstärke
osascript "$JARVIS_DIR/scripts/play_music.applescript"

sleep 2

# Chrome mit Jarvis + zusätzlichem Tab
open -na "Google Chrome" --args \
  --autoplay-policy=no-user-gesture-required \
  "http://localhost:8340" \
  "$(python3 -c "import json; print(json.load(open('$JARVIS_DIR/config.json'))['browser_url'])")"

# Fenster in Quadranten snappen
sleep 3
osascript "$(dirname "$0")/launch_session.applescript"
```

**`scripts/play_music.applescript`** — Öffnet Apple Music, setzt Lautstärke auf 30%, startet Playlist "AC/DC Megahits" (Fallback: alle AC/DC-Library-Tracks) shuffled. Der User muss einmalig "AC/DC Essentials" aus Apple Music als Playlist "AC/DC Megahits" in seine Library speichern, sonst greift nur der Fallback auf lokal vorhandene AC/DC-Titel.

**`launch_session.applescript`** — Quadranten-Snapping via `System Events`:

```applescript
tell application "Finder"
  set screenBounds to bounds of window of desktop
  set screenW to item 3 of screenBounds
  set screenH to item 4 of screenBounds
end tell

set halfW to screenW / 2
set halfH to screenH / 2

tell application "System Events"
  tell process "Code"
    set position of front window to {0, 25}
    set size of front window to {halfW, halfH}
  end tell
  tell process "Obsidian"
    set position of front window to {halfW, 25}
    set size of front window to {halfW, halfH}
  end tell
  tell process "Google Chrome"
    set position of front window to {0, halfH + 25}
    set size of front window to {halfW, halfH}
  end tell
  tell process "Music"
    set position of front window to {halfW, halfH + 25}
    set size of front window to {halfW, halfH}
  end tell
end tell
```

Die `25`-Offset berücksichtigt die Menüleiste.

### 2. `config.json` — macOS-Pfade

Der Upstream hat Windows-Pfade in `config.example.json`. Neue Defaults:

```json
{
  "anthropic_api_key": "YOUR_ANTHROPIC_API_KEY",
  "elevenlabs_api_key": "YOUR_ELEVENLABS_API_KEY",
  "elevenlabs_voice_id": "YOUR_VOICE_ID",
  "user_name": "Mario",
  "user_address": "Sir",
  "city": "Hamburg",
  "workspace_path": "/Users/mariopustan/code/jarvis",
  "browser_url": "https://example.com",
  "obsidian_inbox_path": "/Users/mariopustan/Documents/Obsidian/Inbox",
  "apps": []
}
```

Spotify-Track-Felder entfallen; die Musik-Config ist im `play_music.applescript` hardcodiert (AC/DC-Megahits @ 30%) und kann dort direkt editiert werden.

Die Env-Vars `ANTHROPIC_API_KEY` und `ELEVENLABS_API_KEY` landen zusätzlich in einer `.env`-Datei (gitignored), damit sie nicht im JSON stehen müssen. `server.py` wird minimal erweitert, Env-Vars vor JSON zu bevorzugen.

### 3. `scripts/clap-trigger.py` — Trigger-Zeile

Eine Zeile ändern:

```python
# vorher (Windows):
subprocess.Popen(["powershell", "-ExecutionPolicy", "Bypass", "-File", SCRIPT_PATH])

# nachher (macOS):
subprocess.Popen(["bash", SCRIPT_PATH])
```

Plus: `SCRIPT_PATH` zeigt auf `launch_session.sh` statt `.ps1`.

### 4. Auto-Start — `launchd` statt Task Scheduler

Ein `~/Library/LaunchAgents/com.jarvis.clap.plist`, das `clap_trigger.py` beim Login startet:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.jarvis.clap</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/mariopustan/code/jarvis/.venv/bin/python</string>
    <string>/Users/mariopustan/code/jarvis/scripts/clap_trigger.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/jarvis-clap.log</string>
  <key>StandardErrorPath</key><string>/tmp/jarvis-clap.err.log</string>
</dict>
</plist>
```

Aktivieren mit `launchctl load ~/Library/LaunchAgents/com.jarvis.clap.plist`.

## Workspace-Layout

```
~/code/jarvis/                        ← echtes Repo, außerhalb iCloud
├── .venv/                            ← gitignored
├── .env                              ← gitignored, enthält Keys
├── .git/
├── config.json                       ← gitignored
├── config.example.json
├── server.py
├── browser_tools.py
├── screen_capture.py
├── requirements.txt
├── frontend/
├── scripts/
│   ├── clap_trigger.py
│   ├── launch_session.sh
│   └── launch_session.applescript
├── docs/plans/
│   └── 2026-04-11-jarvis-macos-port-design.md
├── CLAUDE.md
├── README.md
└── SETUP.md

~/Library/LaunchAgents/com.jarvis.clap.plist
```

Plus ein Symlink im iCloud-Jarvis-Ordner:
```
~/Library/Mobile Documents/com~apple~CloudDocs/Jarvis/jarvis → ~/code/jarvis
```

So liegt der echte Code außerhalb iCloud (kein Venv-Sync-Chaos, keine `.env` in der Cloud), aber vom iCloud-Workflow aus ist er weiterhin erreichbar.

## Datenfluss (unverändert)

```
Mic → Chrome Web Speech API → WebSocket → server.py
  → Claude Haiku (System-Prompt + Historie + Tools)
  → tool_use? → browser_tools | screen_capture | news
  → Antwort-Text → ElevenLabs TTS → WebSocket → Browser <audio>
```

## macOS-Permissions (einmalig, manuell)

Systemeinstellungen → Datenschutz & Sicherheit:

| Permission | Betroffene App | Wofür |
| --- | --- | --- |
| Mikrofon | Terminal, Chrome | clap_trigger + Web Speech API |
| Bedienungshilfen | Terminal, osascript | Fensterpositionierung |
| Bildschirmaufnahme | Python | `PIL.ImageGrab` Screenshots |
| Automation | osascript | Music/VS Code/Chrome steuern |

## Umsetzungsschritte

1. Repo clonen und Remotes setzen — **erledigt**
2. Design-Dokument schreiben und committen — **dieser Schritt**
3. `.gitignore` erweitern (`.venv`, `.env`, `config.json`)
4. Venv anlegen, Dependencies installieren, Playwright-Browser ziehen
5. `config.example.json` auf macOS-Pfade anpassen
6. `.env` lokal mit beiden Keys befüllen (nicht committen)
7. `server.py` minimal erweitern: Env-Vars lesen falls gesetzt
8. `launch_session.sh` und `launch_session.applescript` schreiben
9. `clap-trigger.py` auf macOS anpassen, umbenennen zu `clap_trigger.py`
10. Windows-`launch-session.ps1` löschen
11. `launchd` plist schreiben, laden, testen
12. Ende-zu-Ende-Test: Double-Clap → Workspace, Sprachbefehl → Antwort
13. README um macOS-Setup-Abschnitt erweitern
14. Push auf `Maure71/jarvis`

## Risiken & Offene Punkte

- **AppleScript-Permission-Prompt** beim ersten Lauf — harmlos, aber erfordert User-Klick.
- **Chrome-Autoplay-Policy** — der `--autoplay-policy` Flag greift nur, wenn Chrome frisch ohne bestehenden User-Profile-Prozess startet. Workaround: eigenes Chrome-Profil für Jarvis.
- **ElevenLabs-Stimme** — vorherige Stimme war englisch. Deutsche Butler-Stimme muss im ElevenLabs-Katalog gewählt werden. Voice-ID kommt in `config.json`.
- **Obsidian-Inbox-Pfad** — Tasks-Integration hängt davon ab, dass der Pfad existiert. Falls leer, zeigt `server.py` einfach kein Task-Briefing.
- **ElevenLabs-Key rotieren** — der Key aus dem Chat gilt als kompromittiert und wird nicht verwendet.
- **Apple Music Library-Abhängigkeit** — AppleScript hat keinen offiziellen Zugriff auf den Apple Music Streaming-Katalog. Die AC/DC-Wiedergabe funktioniert nur, wenn eine Playlist "AC/DC Megahits" in der Library liegt oder AC/DC-Titel lokal gespeichert sind. One-time-Setup: "AC/DC Essentials" aus Apple Music in die Library speichern und als "AC/DC Megahits" umbenennen.
