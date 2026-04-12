#!/bin/bash
#
# sync_profile.sh
# ----------------
# Syncs the Obsidian-hosted Jarvis profile from the MacBook's local
# iCloud Mobile Documents folder to the Mac Mini where the Jarvis
# server runs. The server's LaunchAgent cannot read iCloud Mobile
# Documents directly (macOS TCC blocks headless launchd processes from
# reaching protected locations), so we cache a plain-file copy at
# ~/code/jarvis/profile.md on the Mini and refresh it from here
# whenever Obsidian writes to the source.
#
# This script is triggered by com.jarvis.profile-sync.plist via
# launchd's WatchPaths mechanism — any change under the Obsidian INBOX
# directory fires the job. The script is idempotent, so running it
# more often than strictly necessary is harmless.
#
# The Mini is addressed via its Tailscale IP so no MagicDNS / corporate
# DNS interference can break the sync.
#

set -u

SRC="/Users/mariopustan/Library/Mobile Documents/iCloud~md~obsidian/Documents/MP_OS/00 INBOX/Jarvis.md"
DST_HOST="100.93.26.13"
DST_PATH="/Users/mariopustan/code/jarvis/profile.md"
LOG="$HOME/Library/Logs/jarvis-profile-sync.log"

ts() { date "+%Y-%m-%d %H:%M:%S"; }

# Bail out cleanly if the source file doesn't exist yet (e.g. Obsidian
# has not finished writing it, or iCloud is still pulling it in).
if [ ! -f "$SRC" ]; then
    echo "[$(ts)] skip: source file missing" >> "$LOG"
    exit 0
fi

# Only sync if the file actually changed since last run. We stash a
# hash in /tmp so repeated directory-change events for unrelated files
# in the same Obsidian folder don't cause needless scp traffic.
HASH_NEW=$(shasum "$SRC" | awk '{print $1}')
HASH_CACHE="$HOME/Library/Caches/jarvis-profile-sync.hash"
if [ -f "$HASH_CACHE" ]; then
    HASH_OLD=$(cat "$HASH_CACHE")
    if [ "$HASH_NEW" = "$HASH_OLD" ]; then
        # Nothing to do — unrelated INBOX change.
        exit 0
    fi
fi

# scp with:
#   -q     quiet (don't print progress)
#   -p     preserve mtime (helps debugging)
#   -B     batch mode (no interactive password prompt — we rely on
#          your SSH key pointing at the Tailscale host)
#   ConnectTimeout=5 — fail fast if the Mini is asleep / unreachable
#   StrictHostKeyChecking=accept-new — accept on first contact, then
#          pin the host key like normal
if scp -q -p -B \
    -o ConnectTimeout=5 \
    -o StrictHostKeyChecking=accept-new \
    "$SRC" "$DST_HOST:$DST_PATH" 2>> "$LOG"; then
    echo "$HASH_NEW" > "$HASH_CACHE"
    echo "[$(ts)] synced ($HASH_NEW)" >> "$LOG"
else
    echo "[$(ts)] scp FAILED (Mini unreachable?)" >> "$LOG"
    exit 1
fi
