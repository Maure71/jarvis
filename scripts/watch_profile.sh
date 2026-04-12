#!/bin/bash
#
# watch_profile.sh
# -----------------
# User-session watcher for the Jarvis profile file. This wraps
# sync_profile.sh in a mtime-polling loop so we get a near-realtime
# MacBook → Mini sync whenever you edit Jarvis.md in Obsidian.
#
# WHY NOT LAUNCHD?
#   macOS TCC (Transparency, Consent & Control) blocks launchd-
#   spawned processes from reading iCloud Mobile Documents, no
#   matter what's in the plist. launchd WatchPaths therefore cannot
#   reach the Obsidian vault. Processes spawned from your interactive
#   Terminal *do* inherit your Terminal's TCC grant for iCloud, so
#   running this watcher as a Terminal-child process (via nohup or
#   tmux) works reliably.
#
# STARTUP:
#   nohup ~/code/jarvis/scripts/watch_profile.sh >/dev/null 2>&1 &
#
#   or auto-start at login — add to ~/.zprofile:
#     if ! pgrep -f "watch_profile.sh" >/dev/null; then
#         nohup ~/code/jarvis/scripts/watch_profile.sh >/dev/null 2>&1 &
#     fi
#
# STOP:
#   pkill -f watch_profile.sh
#
# STATUS:
#   pgrep -lf watch_profile.sh
#   tail -f ~/Library/Logs/jarvis-profile-sync.log
#

set -u

SRC="/Users/mariopustan/Library/Mobile Documents/iCloud~md~obsidian/Documents/MP_OS/00 INBOX/Jarvis.md"
SYNC_SCRIPT="$(cd "$(dirname "$0")" && pwd)/sync_profile.sh"
LOG="$HOME/Library/Logs/jarvis-profile-sync.log"
PIDFILE="$HOME/Library/Caches/jarvis-profile-sync.pid"
INTERVAL=3

ts() { date "+%Y-%m-%d %H:%M:%S"; }

# Single-instance guard. If another watcher is already alive, just
# exit so you can safely blast this from multiple shells or a
# .zprofile without forking a zoo of pollers.
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE" 2>/dev/null || echo "")
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[$(ts)] watcher already running (pid $OLD_PID), exiting" >> "$LOG"
        exit 0
    fi
fi
echo $$ > "$PIDFILE"

# Clean up the pidfile on exit so a later invocation knows we're gone.
trap 'rm -f "$PIDFILE"' EXIT INT TERM

echo "[$(ts)] watcher started (pid $$, interval ${INTERVAL}s)" >> "$LOG"

# stat -f %m is the BSD/macOS flavour for mtime-as-epoch. Linux would
# need `stat -c %Y`, but we only run on macOS so the BSD flag is fine.
last_mtime=""
if [ -f "$SRC" ]; then
    last_mtime=$(stat -f %m "$SRC" 2>/dev/null || echo "")
    # Trigger an initial sync on startup, so the first thing we do is
    # bring the Mini in line with whatever's in Obsidian right now.
    bash "$SYNC_SCRIPT" >/dev/null 2>&1 || true
fi

while true; do
    sleep "$INTERVAL"
    if [ ! -f "$SRC" ]; then
        # Source file vanished (unusual). Just keep waiting.
        continue
    fi
    current_mtime=$(stat -f %m "$SRC" 2>/dev/null || echo "")
    if [ -n "$current_mtime" ] && [ "$current_mtime" != "$last_mtime" ]; then
        last_mtime="$current_mtime"
        bash "$SYNC_SCRIPT" >/dev/null 2>&1 || true
    fi
done
