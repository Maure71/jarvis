# J.A.R.V.I.S. — Personal AI Voice Assistant (macOS)

> Double-clap. Jarvis wakes up, greets you with the weather and your tasks, answers your questions with dry wit, controls your browser, and sees your screen.

This is a **macOS port** of Julian Ivanov's [jarvis-voice-assistant](https://github.com/Julian-Ivanov/jarvis-voice-assistant), which targets Windows. The Python brain (FastAPI + Claude Haiku + ElevenLabs + Playwright) is unchanged; the launcher, window snapping, auto-start and music control have been rewritten to use AppleScript, `launchd` and Apple Music instead of PowerShell, Task Scheduler and Spotify.

---

## Features

- **Double-Clap Trigger** — Clap twice and your entire workspace launches: Apple Music (AC/DC at 30%), VS Code, Obsidian, Chrome with the Jarvis UI
- **Voice Conversation** — Speak freely through your microphone. Jarvis listens, thinks, and responds with a voice
- **German Sarcastic Butler** — Jarvis speaks German in Sie-form with the personality of Tony Stark's AI: dry, witty, always one step ahead
- **Weather & Tasks** — On startup, Jarvis greets you with the current weather and a summary of your open tasks from Obsidian
- **Browser Automation** — *"Search for X"* → Jarvis opens a real Chromium window, navigates to the page, reads the content, and summarises it
- **Screen Vision** — *"Was ist auf meinem Bildschirm?"* → Jarvis takes a screenshot, analyses it with Claude Vision, and describes what he sees
- **World News** — *"Was passiert in der Welt?"* → Jarvis opens worldmonitor.app and summarises current events
- **Window Snapping** — All launched apps automatically snap into screen quadrants via AppleScript / System Events

---

## Architecture

```
You (speak) → Chrome Browser (Web Speech API) → FastAPI Server (local)
                                                       ↓
                                                Claude Haiku (thinks)
                                                       ↓
                                    ┌──────────────────┼───────────────────┐
                                    ↓                  ↓                   ↓
                             ElevenLabs TTS     Playwright Browser    Screen Capture
                             (speaks back)      (searches/opens)     (Claude Vision)
                                    ↓
                             Audio → Chrome → You (hear)
```

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Speech Input | Web Speech API (Chrome) | Converts your voice to text |
| Server | FastAPI (Python) | Local orchestration — runs on your Mac |
| Brain | Claude Haiku (Anthropic) | Thinks, decides, formulates responses |
| Voice | ElevenLabs TTS | Converts text to natural German speech |
| Browser Control | Playwright | Automates a real browser you can see |
| Screen Vision | Claude Vision + Pillow | Screenshots (via Quartz) and describes your screen |
| Clap Detection | sounddevice + numpy | Listens for double-clap to launch everything |
| Window Management | AppleScript + System Events | Snaps windows into screen quadrants |
| Auto-start | launchd (LaunchAgent) | Starts the clap listener at login |

---

## Prerequisites

- **macOS 13+** (tested on 14/15)
- **Python 3.11+** (3.9 works too, but 3.11+ is recommended)
- **Google Chrome**
- **Apple Music.app** (pre-installed)
- **Obsidian** (optional, for task briefing)

### API Keys Needed

| Service | What For | Cost | Link |
|---------|----------|------|------|
| Anthropic | Claude Haiku (the brain) | ~$0.25 / 1M tokens | [console.anthropic.com](https://console.anthropic.com) |
| ElevenLabs | Voice (text-to-speech) | Free tier: 10k chars/month | [elevenlabs.io](https://elevenlabs.io) |

Both keys are stored in a **gitignored `.env` file**, never in `config.json`.

---

## Quick Start

1. **Clone the repo** (outside iCloud — venv sync is painful):
   ```bash
   mkdir -p ~/code && cd ~/code
   git clone https://github.com/Maure71/jarvis.git
   cd jarvis
   ```

2. **Create a venv and install dependencies:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **Create `config.json` and `.env`:**
   ```bash
   cp config.example.json config.json
   cat > .env <<'EOF'
   ANTHROPIC_API_KEY=sk-ant-...
   ELEVENLABS_API_KEY=sk_...
   EOF
   ```

4. **Edit `config.json`** with your personal paths and voice ID. Leave `anthropic_api_key` and `elevenlabs_api_key` empty — the server reads them from `.env`.
   ```json
   {
     "anthropic_api_key": "",
     "elevenlabs_api_key": "",
     "elevenlabs_voice_id": "YOUR_VOICE_ID",
     "user_name": "Your Name",
     "user_address": "Sir",
     "city": "Hamburg",
     "workspace_path": "/Users/YOU/code/jarvis",
     "browser_url": "https://your-website.com",
     "obsidian_inbox_path": "/Users/YOU/Documents/Obsidian/Inbox",
     "apps": []
   }
   ```

5. **One-time Apple Music setup:** In Apple Music, search for *AC/DC Essentials*, add the playlist to your library, and rename it to **"Jarvis Wake-Up"**. Without this the launcher will fall back to any AC/DC tracks in your library (or log a friendly warning if none).

6. **Grant macOS permissions** (System Settings → Privacy & Security). This is painful but one-time:
   | Permission | App | Why |
   |---|---|---|
   | Microphone | Terminal, Chrome | clap_trigger + Web Speech API |
   | Accessibility | Terminal, osascript | Window positioning via System Events |
   | Screen Recording | Python | `PIL.ImageGrab` screenshots |
   | Automation | osascript | Control Music / Code / Chrome |

7. **Start Jarvis:**
   ```bash
   python server.py
   ```

8. **Open Chrome** at `http://localhost:8340`, click anywhere on the page, then speak.

---

## Usage

### Start Jarvis manually
```bash
python server.py
```
Then open `http://localhost:8340` in Chrome.

### Start the entire workspace with a double-clap
```bash
python scripts/clap_trigger.py
```
Clap twice → Apple Music starts AC/DC @ 30%, VS Code opens, Obsidian opens, Chrome launches with the Jarvis UI, all windows snap into quadrants.

### Auto-start the clap listener on login

The repo ships a `launchd` template:

```bash
cp scripts/com.jarvis.clap.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jarvis.clap.plist
```

Edit the two absolute paths in the plist first if your repo isn't at `/Users/mariopustan/code/jarvis`.

Logs are at `/tmp/jarvis-clap.log` and `/tmp/jarvis-clap.err.log`. To stop auto-start:

```bash
launchctl unload ~/Library/LaunchAgents/com.jarvis.clap.plist
```

---

## What You Can Say

| Command | What Happens |
|---------|-------------|
| *"Guten Morgen, Jarvis"* | Greets you with weather + Obsidian tasks |
| *"Such nach KI-News"* | Opens Chromium, searches DuckDuckGo, summarises results |
| *"Öffne skool.com"* | Opens the URL in your default browser |
| *"Was ist auf meinem Bildschirm?"* | Takes screenshot, describes it via Claude Vision |
| *"Was passiert in der Welt?"* | Opens worldmonitor.app, summarises global news |
| *any question* | Jarvis answers in dry butler style, in German |

---

## Project Structure

```
~/code/jarvis/
├── server.py                        # FastAPI backend — the brain
├── browser_tools.py                 # Playwright browser automation
├── screen_capture.py                # Screenshot + Claude Vision
├── config.json                      # Personal config (gitignored)
├── config.example.json              # Template for new users
├── .env                             # API keys (gitignored)
├── requirements.txt
├── frontend/
│   ├── index.html                   # Jarvis web UI
│   ├── main.js                      # Speech recognition + WebSocket + audio
│   └── style.css                    # Dark theme with animated orb
├── scripts/
│   ├── clap_trigger.py              # Double-clap detection (macOS)
│   ├── launch_session.sh            # Bash orchestrator for the workspace
│   ├── launch_session.applescript   # Quadrant snapping via System Events
│   ├── play_music.applescript       # Apple Music AC/DC @ 30%
│   ├── _read_browser_url.py         # Helper for launch_session.sh
│   └── com.jarvis.clap.plist        # LaunchAgent template for auto-start
├── docs/plans/
│   └── 2026-04-11-jarvis-macos-port*.md
├── CLAUDE.md
└── README.md
```

---

## Customization

### Change Jarvis's personality
Edit the system prompt in `server.py` → `build_system_prompt()`.

### Change the wake-up music
Edit `scripts/play_music.applescript`. The playlist name (`"Jarvis Wake-Up"`), fallback artist (`"AC/DC"`) and volume (`30`) are all at the top of the file.

### Change the voice
Find a German voice on [elevenlabs.io](https://elevenlabs.io), copy the Voice ID into `config.json` under `elevenlabs_voice_id`.

### Change the weather city
```json
{ "city": "Kisdorf" }
```

### Adjust clap sensitivity
In `scripts/clap_trigger.py`:
```python
THRESHOLD = 0.15  # Lower = more sensitive
MAX_GAP = 1.2     # Seconds between claps
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Server crashes with "Missing API keys" | Check `.env` — `server.py` uses `load_dotenv(override=True)` so `.env` always wins over shell env vars |
| Clap trigger fires on random noises | Raise `THRESHOLD` in `scripts/clap_trigger.py` |
| Quadrant snapping does nothing | Grant Accessibility permission to Terminal (and to the launchd helper once you install the plist) |
| Apple Music plays nothing | Create the "Jarvis Wake-Up" playlist in your library, or make sure you have at least one AC/DC track locally |
| Browser search fails | Run `playwright install chromium` inside the venv |
| No audio in Chrome | Click anywhere on the page first (Chrome autoplay policy). After clap-trigger auto-launch, `scripts/mic_workaround.applescript` simulates the click — requires Accessibility permission for osascript. |
| Screenshot tool returns a black image | Grant Screen Recording permission to Python/Terminal |
| Jarvis says "Sir planen" instead of "Sie planen" | Update the grammar rules in `server.py`'s system prompt |

---

## Windows Users

The original Windows version lives upstream at [Julian-Ivanov/jarvis-voice-assistant](https://github.com/Julian-Ivanov/jarvis-voice-assistant). This fork is macOS-only and doesn't try to stay cross-platform — see `docs/plans/2026-04-11-jarvis-macos-port-design.md` for the rationale.

---

## Tech Stack

- **[FastAPI](https://fastapi.tiangolo.com/)** — Python web framework for the local server
- **[Claude Haiku](https://anthropic.com)** — Fast AI model (the brain)
- **[ElevenLabs](https://elevenlabs.io)** — Natural text-to-speech (the voice)
- **[Playwright](https://playwright.dev)** — Browser automation
- **[Web Speech API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API)** — Browser-native speech recognition
- **[sounddevice](https://python-sounddevice.readthedocs.io/)** — Audio input for clap detection
- **AppleScript / System Events** — Window snapping and Apple Music control
- **launchd** — Auto-start at login

---

## Credits

Original Windows version by [Julian Ivanov](https://skool.com/ki-automatisierung) with [Claude Code](https://claude.ai/code). macOS port by [Mario Pustan](https://github.com/Maure71), also with Claude Code.

Inspired by Iron Man's J.A.R.V.I.S. — *"Zu Diensten, Sir."*

---

## License

MIT — use it, modify it, build on it.
