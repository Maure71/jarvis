# CLAUDE.md

Dieses Workspace ist **Jarvis** — ein persoenlicher KI-Assistent mit Sprachsteuerung, Browser-Kontrolle und Doppelklatschen-Trigger.

---

## Workflow: Cowork + Claude Code

Mario entwickelt mit **Claude Code** (CLI) und nutzt **Cowork** (Desktop-App) fuer Planung, Recherche und UI-Aufgaben.

**Wenn Cowork an Grenzen stoesst** (z.B. kein SSH, kein Terminal-Tippen, kein Xcode-Build), soll Cowork:
1. Einen **kopierfertigen Claude-Code-Prompt** bereitstellen, der die Aufgabe praezise beschreibt
2. Den Prompt so formulieren, dass Claude Code sofort loslegen kann — inkl. Dateipfade, Kontext und was bereits erledigt wurde
3. Format: Prompt im Codeblock, damit Mario ihn direkt kopieren kann

**Infrastruktur-Hinweise fuer Claude Code:**
- Jarvis-Server laeuft auf dem **Mac Mini** (Tailscale IP: `100.93.26.13`, Hostname: `mac-mini-mario`)
- Tailscale CLI auf dem Mac Mini: `/opt/homebrew/bin/tailscale` (Homebrew-Installation)
- Tailscale Funnel ist aktiv: `https://mac-mini-mario.taile91bf3.ts.net/`
- iOS App liegt unter `ios/` — Xcode-Projekt, SwiftUI, deployed aufs iPhone
- SSH vom MacBook zum Mac Mini: `ssh 100.93.26.13`

---

## Fuer Claude Code: Setup-Modus

Wenn der Nutzer nach dem Setup fragt oder "Richte Jarvis ein" sagt, folge den Anweisungen in `SETUP.md`. Frage den Nutzer nach seinem Namen, seiner Taetigkeit, und wie er angesprochen werden moechte — diese Infos muessen in den Systemprompt in `server.py` eingetragen werden (ersetze die aktuellen Platzhalter "Julian", "KI-Berater und Automatisierungsexperte", "Sir").

**WICHTIG — Pruefe und installiere zuerst alle Voraussetzungen:**

1. **Python**: Pruefe ob Python 3.10+ installiert ist (`python --version`). Falls nicht, installiere es:
   - Windows: `winget install Python.Python.3.12`
   - Warte bis die Installation abgeschlossen ist und pruefe erneut

2. **Google Chrome**: Pruefe ob Chrome installiert ist. Falls nicht, weise den Nutzer an Chrome von https://google.com/chrome zu installieren.

3. **pip Dependencies**: `pip install -r requirements.txt`

4. **Playwright Browser**: `playwright install chromium`

Erst NACHDEM alle Voraussetzungen installiert sind, fahre mit dem Setup in `SETUP.md` fort (API Keys abfragen, config.json erstellen, etc.).

---

## Workspace Structure

```
.
├── CLAUDE.md              # This file
├── SETUP.md               # Setup-Anleitung fuer Claude Code
├── config.json            # Persoenliche Config (gitignored)
├── config.example.json    # Template mit Platzhaltern
├── requirements.txt       # Python Dependencies
├── server.py              # FastAPI Backend (Claude Haiku + ElevenLabs TTS)
├── browser_tools.py       # Playwright Browser-Steuerung
├── screen_capture.py      # Screenshot + Claude Vision
├── frontend/
│   ├── index.html         # Jarvis Web-UI
│   ├── main.js            # Speech Recognition + WebSocket + Audio
│   └── style.css          # Dark Theme mit Orb-Animation
└── scripts/
    ├── clap-trigger.py    # Doppelklatschen-Erkennung
    └── launch-session.ps1 # Startet alle Apps + Jarvis
```
