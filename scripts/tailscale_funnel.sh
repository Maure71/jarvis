#!/usr/bin/env bash
# Jarvis — Tailscale Funnel Manager
# Exposes the local Jarvis server (port 8340) to the public internet
# via Tailscale Funnel so Mario can use Jarvis over 5G from anywhere.
#
# Usage:
#   ./tailscale_funnel.sh start   — enable funnel (survives reboot via --bg)
#   ./tailscale_funnel.sh stop    — disable funnel
#   ./tailscale_funnel.sh status  — show current funnel state
#   ./tailscale_funnel.sh url     — print the public Jarvis URL
#
# Tailscale Funnel provides:
#   - Automatic HTTPS with a valid Let's Encrypt certificate
#   - A public URL like https://<hostname>.tail<net>.ts.net/
#   - WebSocket (wss://) support out of the box
#   - No port forwarding, no dynamic DNS, no firewall changes needed

set -euo pipefail

PORT=8340

# Homebrew installs tailscale to /opt/homebrew/bin on Apple Silicon Macs.
# Fall back to bare 'tailscale' if the Homebrew path doesn't exist.
if [[ -x /opt/homebrew/bin/tailscale ]]; then
    TS=/opt/homebrew/bin/tailscale
else
    TS=tailscale
fi

log() { echo "[jarvis-funnel] $*"; }

get_hostname() {
    "$TS" status --json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
dns = data.get('Self', {}).get('DNSName', '')
# DNSName ends with a trailing dot — strip it
print(dns.rstrip('.'))
" 2>/dev/null || echo "<unbekannt>"
}

case "${1:-status}" in
    start)
        log "Aktiviere Tailscale Funnel auf Port $PORT ..."
        # --bg runs the funnel in the background as a daemon.
        # Tailscale handles TLS termination and proxies HTTPS→HTTP
        # and WSS→WS transparently.
        "$TS" funnel --bg "$PORT"
        HOSTNAME=$(get_hostname)
        log "Funnel aktiv!"
        log ""
        log "  Jarvis ist jetzt erreichbar unter:"
        log "  https://$HOSTNAME/"
        log ""
        log "  Auf dem iPhone: URL in Safari öffnen → 'Zum Home-Bildschirm' → fertig."
        ;;
    stop)
        log "Deaktiviere Tailscale Funnel ..."
        "$TS" funnel --bg off
        log "Funnel gestoppt. Jarvis ist nur noch lokal erreichbar."
        ;;
    status)
        log "Aktueller Funnel-Status:"
        "$TS" funnel status 2>/dev/null || log "(kein Funnel aktiv)"
        ;;
    url)
        HOSTNAME=$(get_hostname)
        echo "https://$HOSTNAME/"
        ;;
    *)
        echo "Usage: $0 {start|stop|status|url}"
        exit 1
        ;;
esac
