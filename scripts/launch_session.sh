#!/usr/bin/env bash
# Jarvis — Workspace Launcher (macOS)
# Starts the Jarvis server in Terminal, opens VS Code + Obsidian + Chrome,
# kicks off Apple Music with AC/DC at 30%, then snaps everything into
# screen quadrants. Invoked by scripts/clap_trigger.py on double-clap.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
JARVIS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$JARVIS_DIR/config.json"
VENV_PYTHON="$JARVIS_DIR/.venv/bin/python"

log() { echo "[jarvis-launcher] $*"; }

log "Starting Jarvis workspace from $JARVIS_DIR"

# 1. Jarvis server in a new Terminal window.
#    The single-quoted outer string keeps $JARVIS_DIR from being expanded
#    by osascript's shell — we do the expansion ourselves via printf.
SERVER_CMD=$(printf 'cd %q && source .venv/bin/activate && python server.py' "$JARVIS_DIR")
osascript -e "tell application \"Terminal\" to do script \"$SERVER_CMD\"" >/dev/null
log "Server launched in Terminal"

# 2. Launch editor + notes
open -a "Visual Studio Code" "$JARVIS_DIR"
open -a "Obsidian"
log "VS Code + Obsidian launched"

# 3. Apple Music: AC/DC shuffled at 30%
osascript "$SCRIPT_DIR/play_music.applescript" || log "play_music.applescript returned non-zero (continuing)"

# 4. Chrome with Jarvis UI and optional extra tab from config.json.
#    Read browser_url via a separate helper file so we don't have to
#    juggle nested quotes between bash, osascript and python heredocs.
BROWSER_URL=""
if [[ -f "$CONFIG_FILE" && -x "$VENV_PYTHON" ]]; then
  BROWSER_URL=$("$VENV_PYTHON" "$SCRIPT_DIR/_read_browser_url.py" "$CONFIG_FILE" 2>/dev/null || true)
fi

# Give the server a moment so the Jarvis URL actually responds when Chrome
# opens it — avoids a 'site unreachable' flash.
sleep 2

if [[ -n "$BROWSER_URL" ]]; then
  open -na "Google Chrome" --args \
    --autoplay-policy=no-user-gesture-required \
    "http://localhost:8340" \
    "$BROWSER_URL"
  log "Chrome launched with Jarvis + extra tab: $BROWSER_URL"
else
  open -na "Google Chrome" --args \
    --autoplay-policy=no-user-gesture-required \
    "http://localhost:8340"
  log "Chrome launched with Jarvis only (no browser_url configured)"
fi

# 5. Wait for windows to exist, then snap into quadrants.
sleep 3
osascript "$SCRIPT_DIR/launch_session.applescript" || log "Quadrant snap returned non-zero (check Accessibility permissions)"

# 6. WebKit mic workaround — simulate a click inside Chrome so
#    webkitSpeechRecognition can start without waiting for a manual
#    click on the orb. frontend/main.js auto-starts listening on the
#    first document-level click or keydown.
sleep 1
osascript "$SCRIPT_DIR/mic_workaround.applescript" || log "mic_workaround returned non-zero (mic may need manual click)"

# 7. Tailscale Funnel — expose Jarvis publicly so it works over 5G.
#    --bg runs the funnel as a background daemon. If Tailscale is not
#    installed or not logged in this just prints a warning and continues.
if command -v tailscale &>/dev/null || [[ -x /opt/homebrew/bin/tailscale ]]; then
  "$SCRIPT_DIR/tailscale_funnel.sh" start || log "Tailscale Funnel konnte nicht gestartet werden (weiter ohne)"
else
  log "Tailscale nicht installiert — Jarvis nur lokal erreichbar"
fi

log "Launch sequence done."
