# Jarvis macOS Port Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Port the Windows-only Jarvis voice assistant to macOS by replacing the PowerShell launcher, Win32 window snapping, and startup automation with native macOS equivalents, while leaving the FastAPI server, frontend, browser tools, and screen capture code untouched.

**Architecture:** The FastAPI server, Claude integration, ElevenLabs TTS, Playwright browser automation, PIL-based screen capture, and Chrome frontend all run on macOS without modification. The Windows-specific `launch-session.ps1` is replaced by a bash script that uses `open -a` and an AppleScript helper for window positioning. The clap trigger gets a one-line subprocess change. Startup automation uses `launchd` instead of Windows Task Scheduler. Secrets move to a gitignored `.env` file.

**Tech Stack:** Python 3.11+, FastAPI, Anthropic SDK (Claude Haiku), ElevenLabs HTTP API, Playwright, Pillow, sounddevice, numpy, AppleScript, launchd, bash.

**Design doc:** `docs/plans/2026-04-11-jarvis-macos-port-design.md`

---

## Pre-flight Checks

Before starting Task 1, verify:

- [ ] You are in `~/code/jarvis` (not the iCloud Jarvis folder).
- [ ] `git status` is clean on branch `master`.
- [ ] `git remote -v` shows `origin` → `Maure71/jarvis` and `upstream` → `Julian-Ivanov/jarvis-voice-assistant`.
- [ ] `git config user.name` returns `Mario Pustan`.
- [ ] `python3 --version` returns 3.11 or higher.
- [ ] macOS 14 or later (Sonoma/Sequoia — needed for reliable AppleScript `System Events` behavior).
- [ ] Apple Music is signed in and has either (a) a playlist named "AC/DC Megahits" in the library, or (b) AC/DC tracks saved to the library. Without one of these, the music-start step is a no-op. One-time fix: open Music.app → Search "AC/DC Essentials" → "+ Add" to library → rename to "AC/DC Megahits" (or change the name in `scripts/play_music.applescript`).

If any check fails, stop and resolve before continuing.

---

## Task 1: Extend `.gitignore` for macOS dev workflow

**Files:**
- Modify: `.gitignore`

**Step 1: Read current `.gitignore`**

Run: `cat .gitignore`
Expected output: a short file with maybe `config.json`.

**Step 2: Replace `.gitignore` with expanded version**

```
# Secrets
.env
config.json

# Python
.venv/
__pycache__/
*.pyc
*.pyo
.pytest_cache/

# macOS
.DS_Store
.AppleDouble
.LSOverride
Icon?

# Editor / IDE
.vscode/
.idea/
*.swp

# Logs
*.log
/tmp/jarvis-*.log

# Build artifacts
/build/
/dist/
```

**Step 3: Verify the file is correct**

Run: `cat .gitignore | head -20`
Expected: Lines above appear in order.

**Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: expand .gitignore for macOS dev workflow"
```

---

## Task 2: Create venv and install dependencies

**Files:** None created or modified in git — this is environment setup.

**Step 1: Create venv**

Run: `python3 -m venv .venv`
Expected: No output, `.venv/` directory appears.

**Step 2: Activate and upgrade pip**

Run: `source .venv/bin/activate && pip install --upgrade pip`
Expected: pip upgrade message.

**Step 3: Install requirements**

Run: `pip install -r requirements.txt`
Expected: FastAPI, anthropic, httpx, playwright, Pillow, websockets, uvicorn all installed.

**Step 4: Add `python-dotenv` and `sounddevice` + `numpy` (missing from upstream requirements)**

Run: `pip install python-dotenv sounddevice numpy`
Expected: Three packages installed.

**Step 5: Freeze updated requirements**

Run: `pip freeze | grep -E "^(python-dotenv|sounddevice|numpy)" >> requirements.txt`
Then edit `requirements.txt` by hand to deduplicate and use version ranges.

Final `requirements.txt` should read:

```
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
anthropic>=0.39.0
httpx>=0.27.0
playwright>=1.40.0
Pillow>=10.0.0
websockets>=13.0
python-dotenv>=1.0.0
sounddevice>=0.4.6
numpy>=1.26.0
```

**Step 6: Install Playwright browser binary**

Run: `playwright install chromium`
Expected: Chromium download progress, then "Chromium installed".

**Step 7: Verify installations**

Run: `python -c "import fastapi, anthropic, playwright, PIL, sounddevice, numpy, dotenv; print('OK')"`
Expected: `OK`

**Step 8: Commit updated requirements**

```bash
git add requirements.txt
git commit -m "chore: add python-dotenv, sounddevice, numpy to requirements"
```

---

## Task 3: Port `config.example.json` to macOS paths

**Files:**
- Modify: `config.example.json`

**Step 1: Read current file**

Run: `cat config.example.json`

**Step 2: Replace with macOS-pathed version**

```json
{
  "anthropic_api_key": "",
  "elevenlabs_api_key": "",
  "elevenlabs_voice_id": "YOUR_VOICE_ID",
  "user_name": "Mario",
  "user_address": "Sir",
  "city": "Hamburg",
  "workspace_path": "/Users/YOU/code/jarvis",
  "browser_url": "https://example.com",
  "obsidian_inbox_path": "/Users/YOU/Documents/Obsidian/Inbox",
  "apps": []
}
```

Note: API keys are empty in the example — they come from `.env` now. Spotify is gone — the launcher uses Apple Music directly via AppleScript (see Task 8).

**Step 3: Commit**

```bash
git add config.example.json
git commit -m "chore: port config.example.json to macOS paths"
```

---

## Task 4: Add `.env` support to `server.py`

**Goal:** Load API keys from `.env` first, fall back to `config.json` for backward compatibility.

**Files:**
- Modify: `server.py:1-35`

**Step 1: Read the relevant section**

Run: `sed -n '1,40p' server.py`

**Step 2: Apply the edit**

Find this block (around lines 1–35):

```python
import asyncio
import base64
import json
import os
import re
import time

import anthropic
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

ANTHROPIC_API_KEY = config["anthropic_api_key"]
ELEVENLABS_API_KEY = config["elevenlabs_api_key"]
```

Replace with:

```python
import asyncio
import base64
import json
import os
import re
import time

import anthropic
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Load .env first, then config.json. Env vars win.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or config.get("anthropic_api_key", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY") or config.get("elevenlabs_api_key", "")

if not ANTHROPIC_API_KEY or not ELEVENLABS_API_KEY:
    raise RuntimeError(
        "Missing API keys. Set ANTHROPIC_API_KEY and ELEVENLABS_API_KEY in .env "
        "or config.json."
    )
```

**Step 3: Syntax check**

Run: `python -m py_compile server.py`
Expected: No output. Any error means the edit broke something.

**Step 4: Commit**

```bash
git add server.py
git commit -m "feat(server): load API keys from .env first, fall back to config.json"
```

---

## Task 5: Create local `.env` and `config.json`

**Goal:** Populate the non-committed files so the server can actually run.

**Files:**
- Create: `.env` (NOT committed — gitignored)
- Create: `config.json` (NOT committed — gitignored)

**Step 1: Create `.env`**

Write to `.env`:

```
ANTHROPIC_API_KEY=<ask user>
ELEVENLABS_API_KEY=<ask user>
```

The user must paste or type the real keys. The ElevenLabs key the user posted earlier in chat is considered compromised — a freshly rotated one goes here.

**Step 2: Create `config.json` from example**

Run: `cp config.example.json config.json`
Then edit `config.json`:
- `user_name`: `Mario`
- `workspace_path`: `/Users/mariopustan/code/jarvis`
- `obsidian_inbox_path`: ask user or leave empty string
- `elevenlabs_voice_id`: ask user which German voice from their ElevenLabs library
- `city`: `Hamburg` (or ask)
- `browser_url`: ask user for a default Jarvis-opens-on-activate URL, or leave as `https://example.com`
- `spotify_track`: ask user or leave example

**Step 3: Verify files exist and are NOT staged**

Run: `ls -la .env config.json && git status`
Expected: Both files exist, `git status` does not list them (they are gitignored).

**Step 4: Smoke-test server boots**

Run: `source .venv/bin/activate && timeout 5 python server.py; echo "exit: $?"`
Expected: Server prints the banner `J.A.R.V.I.S. V2 Server`, then the timeout kills it. Exit code non-zero from timeout is fine — we only care that startup did not crash on missing keys or weather fetch.

If the server crashes on `refresh_data()` because `obsidian_inbox_path` is empty, the existing try/except already handles it — no fix needed. If it crashes on weather, that too is a try/except.

**Step 5: No commit** — these files are gitignored by design.

---

## Task 6: Port `clap-trigger.py` for macOS

**Files:**
- Rename: `scripts/clap-trigger.py` → `scripts/clap_trigger.py`
- Modify: `scripts/clap_trigger.py:20-51`

**Step 1: Rename the file (git mv)**

Run: `git mv scripts/clap-trigger.py scripts/clap_trigger.py`
Expected: No output. `git status` shows the rename.

**Step 2: Read current content**

Run: `cat scripts/clap_trigger.py`

**Step 3: Apply the edit**

Find the line:
```python
SCRIPT_PATH = os.path.join(WORKSPACE_PATH, "scripts", "launch-session.ps1")
```
Replace with:
```python
SCRIPT_PATH = os.path.join(WORKSPACE_PATH, "scripts", "launch_session.sh")
```

Find the line:
```python
subprocess.Popen(["powershell", "-ExecutionPolicy", "Bypass", "-File", SCRIPT_PATH])
```
Replace with:
```python
subprocess.Popen(["bash", SCRIPT_PATH])
```

**Step 4: Syntax check**

Run: `python -m py_compile scripts/clap_trigger.py`
Expected: No output.

**Step 5: Verify the file still imports correctly**

Run: `source .venv/bin/activate && python -c "import ast; ast.parse(open('scripts/clap_trigger.py').read()); print('OK')"`
Expected: `OK`

**Step 6: Commit**

```bash
git add scripts/clap_trigger.py
git commit -m "feat(clap): port clap trigger to macOS (bash launcher)"
```

---

## Task 7: Write `launch_session.applescript`

**Files:**
- Create: `scripts/launch_session.applescript`

**Step 1: Write the file**

```applescript
-- Jarvis — Launch Session (macOS)
-- Snaps the four workspace apps into a 2x2 quadrant grid.

tell application "Finder"
  set screenBounds to bounds of window of desktop
  set screenW to item 3 of screenBounds
  set screenH to item 4 of screenBounds
end tell

set menuBarOffset to 25
set halfW to screenW / 2
set halfH to (screenH - menuBarOffset) / 2
set topY to menuBarOffset
set bottomY to menuBarOffset + halfH

tell application "System Events"
  -- Top-left: VS Code
  if exists process "Code" then
    tell process "Code"
      try
        set position of front window to {0, topY}
        set size of front window to {halfW, halfH}
      end try
    end tell
  end if

  -- Top-right: Obsidian
  if exists process "Obsidian" then
    tell process "Obsidian"
      try
        set position of front window to {halfW, topY}
        set size of front window to {halfW, halfH}
      end try
    end tell
  end if

  -- Bottom-left: Google Chrome
  if exists process "Google Chrome" then
    tell process "Google Chrome"
      try
        set position of front window to {0, bottomY}
        set size of front window to {halfW, halfH}
      end try
    end tell
  end if

  -- Bottom-right: Apple Music
  if exists process "Music" then
    tell process "Music"
      try
        set position of front window to {halfW, bottomY}
        set size of front window to {halfW, halfH}
      end try
    end tell
  end if
end tell
```

The `try` blocks and `if exists process` guards keep the script from erroring if one app hasn't fully launched yet.

**Step 2: Syntax-check the AppleScript**

Run: `osacompile -o /tmp/jarvis-launch.scpt scripts/launch_session.applescript && echo OK`
Expected: `OK`. Any syntax error is printed.

**Step 3: Commit**

```bash
git add scripts/launch_session.applescript
git commit -m "feat(launcher): add AppleScript quadrant snapper"
```

---

## Task 8: Write `launch_session.sh` + `play_music.applescript`

**Files:**
- Create: `scripts/launch_session.sh`
- Create: `scripts/play_music.applescript`

Both files are committed together because the bash launcher calls the AppleScript as its music step.

**Step 1: Write `scripts/play_music.applescript`**

Apple Music has no clean public AppleScript search for Apple Music Catalog items, but it can start playlists that live in the user's library and it can play tracks by artist name from the local library. The script tries both: first a user playlist named "AC/DC Megahits", then a fallback of all library tracks whose artist contains "AC/DC", shuffled.

The user needs a one-time setup: open Apple Music, search for AC/DC, and add the "AC/DC Essentials" playlist (or any playlist of their choosing) to their library. Rename it "AC/DC Megahits" — or change the name in this script.

```applescript
-- Jarvis — Play Music (macOS)
-- Starts Apple Music, sets volume to 30%, plays AC/DC shuffled.

set targetPlaylistName to "AC/DC Megahits"
set targetArtistName to "AC/DC"
set targetVolume to 30

tell application "Music"
  launch
  activate

  -- App-level volume (not system volume)
  set sound volume to targetVolume

  try
    set shuffle enabled to true
  end try

  -- Strategy 1: named playlist
  set playedSomething to false
  try
    set thePlaylist to first playlist whose name is targetPlaylistName
    play thePlaylist
    set playedSomething to true
  end try

  -- Strategy 2: all library tracks by artist, shuffled
  if not playedSomething then
    try
      set acdcTracks to (every track of library playlist 1 whose artist contains targetArtistName)
      if (count of acdcTracks) > 0 then
        play item 1 of acdcTracks
        set playedSomething to true
      end if
    end try
  end if

  if not playedSomething then
    display notification "Keine '" & targetPlaylistName & "' Playlist und keine AC/DC-Tracks in der Library gefunden. Bitte einmal Apple Music einrichten." with title "Jarvis"
  end if
end tell
```

**Step 2: Syntax-check `play_music.applescript`**

Run: `osacompile -o /tmp/jarvis-music.scpt scripts/play_music.applescript && echo OK`
Expected: `OK`

**Step 3: Write `scripts/launch_session.sh`**

```bash
#!/usr/bin/env bash
# Jarvis — Launch Session (macOS)
# Starts the FastAPI server, opens workspace apps, snaps windows, plays music.

set -euo pipefail

JARVIS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_PATH="$JARVIS_DIR/config.json"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "[jarvis] Missing config.json at $CONFIG_PATH" >&2
  exit 1
fi

BROWSER_URL=$(python3 -c "import json; print(json.load(open('$CONFIG_PATH')).get('browser_url',''))")

# 1. Start server in a new Terminal window so logs are visible
osascript -e "tell application \"Terminal\" to do script \"cd $JARVIS_DIR && source .venv/bin/activate && python server.py\""

# 2. Launch workspace apps
open -a "Visual Studio Code" "$JARVIS_DIR" || true
open -a "Obsidian" || true

# 3. Start Apple Music with AC/DC shuffled at 30%
osascript "$JARVIS_DIR/scripts/play_music.applescript" || echo "[jarvis] Warning: music start failed"

# 4. Give apps a moment to appear
sleep 3

# 5. Open Chrome with Jarvis UI (+ configured URL if set)
if [[ -n "$BROWSER_URL" ]]; then
  open -a "Google Chrome" --args --autoplay-policy=no-user-gesture-required "http://localhost:8340" "$BROWSER_URL"
else
  open -a "Google Chrome" --args --autoplay-policy=no-user-gesture-required "http://localhost:8340"
fi

# 6. Wait for Chrome to finish opening
sleep 2

# 7. Snap the four windows into quadrants
osascript "$JARVIS_DIR/scripts/launch_session.applescript" || echo "[jarvis] Warning: window snapping failed"

echo "[jarvis] Workspace launched."
```

**Step 4: Make it executable**

Run: `chmod +x scripts/launch_session.sh`

**Step 5: Bash lint**

Run: `bash -n scripts/launch_session.sh && echo OK`
Expected: `OK`

**Step 6: Dry-run — verify the script parses its config without errors**

Run: `bash -c 'set -e; CONFIG_PATH=config.json; python3 -c "import json; print(json.load(open(\"$CONFIG_PATH\")).get(\"browser_url\",\"\"))"'`
Expected: The `browser_url` value from your `config.json` prints.

**Step 7: Commit both files together**

```bash
git add scripts/launch_session.sh scripts/play_music.applescript
git commit -m "feat(launcher): bash launcher + Apple Music AC/DC player"
```

---

## Task 9: Delete the Windows launcher

**Files:**
- Delete: `scripts/launch-session.ps1`

**Step 1: Verify nothing else references it**

Run: `grep -r "launch-session.ps1" . --exclude-dir=.git --exclude-dir=.venv || echo "no references"`
Expected: `no references`. If there are hits in `README.md` or `SETUP.md`, note them but proceed — those will be updated in Task 12.

**Step 2: Delete**

Run: `git rm scripts/launch-session.ps1`

**Step 3: Commit**

```bash
git commit -m "chore: remove Windows PowerShell launcher"
```

---

## Task 10: Manual end-to-end test of launcher

**This task has no file changes and no commit.** It is a verification gate.

**Step 1: Grant macOS permissions (one-time, before first run)**

Open: Systemeinstellungen → Datenschutz & Sicherheit.

Add Terminal (or whichever shell you use) to:
- Bedienungshilfen (Accessibility)
- Automation → allow controlling Music, VS Code, Obsidian, Google Chrome, System Events
- Bildschirmaufnahme (Screen Recording) — for Pillow's `ImageGrab`
- Mikrofon (Microphone)

Grant Chrome microphone access too.

**Step 2: Run the launcher directly**

Run: `bash scripts/launch_session.sh`

**Expected:**
- A new Terminal window opens with the FastAPI server running (banner visible).
- VS Code opens in the Jarvis directory.
- Obsidian opens.
- Apple Music opens and starts playing AC/DC shuffled at 30% volume.
- Chrome opens with `http://localhost:8340` and the Jarvis UI loads.
- Within ~5 seconds, the four app windows snap into quadrants.

**Step 3: Talk to Jarvis**

In the Chrome tab, click the mic button and say: "Jarvis activate"

Expected: A German voice response with weather + a greeting. If nothing happens, check the server's Terminal window for errors.

**Step 4: If it works, note it in the commit log with a marker tag**

```bash
git commit --allow-empty -m "test: manual end-to-end launcher verification PASSED"
```

**Step 5: If it does not work**

Stop here. Debug using the server Terminal output. Common issues:
- Accessibility permission not granted → AppleScript window-snapping silently fails.
- ElevenLabs voice ID wrong → server logs show HTTP 400 from TTS.
- Chrome microphone permission missing → Web Speech API returns nothing.

Do not proceed to Task 11 until end-to-end test passes.

---

## Task 11: Test clap trigger

**This task has no file changes and no commit.** Verification gate.

**Step 1: Run the clap trigger in the foreground**

Run: `source .venv/bin/activate && python scripts/clap_trigger.py`

Expected: `[jarvis] Listening for double clap...`

**Step 2: Clap twice**

Within 1.2 seconds, clap twice. Loudly.

Expected:
- `[jarvis] First clap detected`
- `[jarvis] Double clap detected! Firing launch script. Shutting down.`
- The launcher runs (same as Task 10).

**Step 3: Tune threshold if needed**

If first clap does not register, edit `scripts/clap_trigger.py` and lower `THRESHOLD = 0.15` to `0.08` or `0.10`. Then commit the tuning:

```bash
git add scripts/clap_trigger.py
git commit -m "tune(clap): lower clap threshold for macOS mic sensitivity"
```

Otherwise no commit.

---

## Task 12: Create launchd plist for auto-start

**Files:**
- Create: `scripts/com.jarvis.clap.plist` (template, committed)
- Install: `~/Library/LaunchAgents/com.jarvis.clap.plist` (not committed — lives outside repo)

**Step 1: Write the plist template**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.jarvis.clap</string>

  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/code/jarvis/.venv/bin/python</string>
    <string>/Users/YOU/code/jarvis/scripts/clap_trigger.py</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/Users/YOU/code/jarvis</string>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/tmp/jarvis-clap.log</string>

  <key>StandardErrorPath</key>
  <string>/tmp/jarvis-clap.err.log</string>
</dict>
</plist>
```

**Step 2: Install — copy, substitute the home path, and load**

```bash
sed "s|/Users/YOU|$HOME|g" scripts/com.jarvis.clap.plist > ~/Library/LaunchAgents/com.jarvis.clap.plist
launchctl unload ~/Library/LaunchAgents/com.jarvis.clap.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.jarvis.clap.plist
```

**Step 3: Verify it is running**

Run: `launchctl list | grep jarvis`
Expected: A line like `12345  0  com.jarvis.clap` (PID, status, label).

**Step 4: Verify logs are flowing**

Run: `tail -5 /tmp/jarvis-clap.log`
Expected: `[jarvis] Listening for double clap...`

**Step 5: Commit the template (not the installed copy)**

```bash
git add scripts/com.jarvis.clap.plist
git commit -m "feat(autostart): add launchd plist template for clap trigger"
```

---

## Task 13: Update README for macOS

**Files:**
- Modify: `README.md`

**Step 1: Read the current README**

Run: `wc -l README.md && head -40 README.md`

**Step 2: Add a macOS setup section near the top**

Locate the "Quick Start" or "Setup" header and insert a new subsection **before it**:

```markdown
## macOS Setup (this fork)

This fork ports Jarvis from Windows to macOS. The original Windows-only instructions below still describe the intent; these are the concrete macOS steps.

### Prerequisites
- macOS 14 or later
- Python 3.11 or later
- Google Chrome
- Anthropic API key (Claude Haiku)
- ElevenLabs API key (German voice recommended)

### Install

```bash
git clone git@github.com:Maure71/jarvis.git ~/code/jarvis
cd ~/code/jarvis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp config.example.json config.json
```

Edit `config.json` with your paths, then create `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
ELEVENLABS_API_KEY=sk_...
```

### macOS Permissions (one-time)

In Systemeinstellungen → Datenschutz & Sicherheit, grant these to Terminal and Chrome:
- Mikrofon
- Bedienungshilfen
- Bildschirmaufnahme
- Automation (Spotify, Google Chrome, VS Code, Obsidian, System Events)

### Run

Manually: `bash scripts/launch_session.sh`

Auto-start on login:
```bash
sed "s|/Users/YOU|$HOME|g" scripts/com.jarvis.clap.plist > ~/Library/LaunchAgents/com.jarvis.clap.plist
launchctl load ~/Library/LaunchAgents/com.jarvis.clap.plist
```

Then just clap twice.
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add macOS setup section"
```

---

## Task 14: Push to `Maure71/jarvis`

**Files:** None changed.

**Step 1: Confirm branch and history**

Run: `git log --oneline -15`
Expected: Your commits on top of upstream history. Should see roughly 10 new commits from this plan.

**Step 2: Confirm remote**

Run: `git remote -v | grep origin`
Expected: `origin git@github.com:Maure71/jarvis.git (push)`

**Step 3: Push**

Run: `git push -u origin master`

Expected: Push succeeds. If it fails with permission denied, the `mariopustan` SSH key does not have write access to `Maure71/jarvis`. Stop and ask the user to either add the key to the `Maure71` GitHub account or switch to a different repo.

**Step 4: Verify on GitHub**

Run: `open https://github.com/Maure71/jarvis`
Expected: The commits appear in the GitHub UI.

**Step 5: Final status**

The port is complete. Remaining optional polish (not in this plan):
- Eigener Chrome-Profilordner für Jarvis, damit Autoplay-Policy zuverlässig greift
- Hammerspoon statt AppleScript für sauberere Fensterpositionierung
- Pytest-Coverage für die Hilfsmodule `browser_tools` und `screen_capture`
- Deutsche Butler-Voice-ID in `config.example.json` dokumentieren

---

## Rollback Plan

If anything breaks beyond repair:
```bash
git reset --hard upstream/master
```
This throws away all work from this plan and returns to the upstream state. Since we have been committing frequently, a partial rollback via `git rebase -i upstream/master` is also an option to drop specific tasks.
