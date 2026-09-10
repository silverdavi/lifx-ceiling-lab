#!/usr/bin/env python3
"""Fail if identifying values appear in git-tracked files.

Run before committing or publishing a fork:

    python3 scripts/check_secrets.py

Checks every tracked text file for:
- full LIFX serials: `d073d5` followed by six hex digits (the masked form
  `d073d5xxxxxx` is fine and expected);
- private-range dotted-quad IPs (10.x, 172.16-31.x, 192.168.x) — the masked
  form `xxx.xxx.xxx.xxx` is fine.

Exit code 0 means clean, 1 means something leaked.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FULL_SERIAL = re.compile(r"d073d5[0-9a-fA-F]{6}")
PRIVATE_IP = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3})\b"
)


def tracked_files() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    return [ROOT / name for name in output.decode().split("\0") if name]


def main() -> int:
    problems: list[str] = []
    for path in tracked_files():
        try:
            text = path.read_text(errors="strict")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable, skip
        relative = path.relative_to(ROOT)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if FULL_SERIAL.search(line):
                problems.append(f"{relative}:{line_number}: full LIFX serial")
            if PRIVATE_IP.search(line):
                problems.append(f"{relative}:{line_number}: private IP address")
    if problems:
        print("Identifying values found in tracked files:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print("clean: no serials or private IPs in tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
