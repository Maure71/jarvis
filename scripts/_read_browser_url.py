#!/usr/bin/env python3
"""
Tiny helper for launch_session.sh: prints config.json's "browser_url"
field to stdout, or nothing if missing/invalid. Exits 0 on success,
non-zero only on unexpected crashes (which the shell ignores).

Split out from launch_session.sh so we don't have to juggle nested
quotes between bash, osascript and python heredocs.
"""

import json
import sys


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    try:
        with open(sys.argv[1], "r") as f:
            url = (json.load(f).get("browser_url") or "").strip()
    except (OSError, ValueError):
        return 0
    if url:
        print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
