#!/usr/bin/env python3
"""Echo the input message back and write it to artifacts/echo.txt."""

# aaf:network none
# aaf:timeout 10
# aaf:args {"message": "string"}
from __future__ import annotations

import json
import os
import pathlib
import sys


def main() -> int:
    args = json.loads(sys.stdin.read() or "{}")
    message = args.get("message", "")
    workdir = pathlib.Path(os.environ["AAF_WORKDIR"])
    artifacts = workdir / "artifacts"
    artifacts.mkdir(exist_ok=True)
    out = artifacts / "echo.txt"
    out.write_text(message, encoding="utf-8")
    sys.stdout.write(json.dumps({"echoed": message, "artifact": str(out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
