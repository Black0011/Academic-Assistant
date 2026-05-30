#!/usr/bin/env python3
"""Sleep for `seconds` seconds (default 30) — used to test timeouts."""

# aaf:network none
# aaf:timeout 120
# aaf:args {"seconds": "number"}
from __future__ import annotations

import json
import sys
import time


def main() -> int:
    args = json.loads(sys.stdin.read() or "{}")
    seconds = float(args.get("seconds", 30))
    time.sleep(seconds)
    sys.stdout.write(json.dumps({"slept": seconds}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
