#!/usr/bin/env python3
"""Cross objectives off the outline that the model judged already done.

Its own file for the same reason insert_leg.py is: the chain script
already nests a heredoc, and a second sharing the terminator silently
truncated the block it was written into.

Takes 1-based outline positions on the command line. Only positions AHEAD
of the run's high-water mark may be removed — history is not rewritten,
and removing a line behind the mark would shift every later leg under a
counter that has already passed it.

Usage: skip_legs.py N [N...]
"""
import sys
from pathlib import Path

want = sorted({int(a) for a in sys.argv[1:]}, reverse=True)
if not want:
    sys.exit("skip_legs.py: nothing to skip")

p = Path("plans/outline.txt")
lines = [l for l in p.read_text().splitlines() if l.strip()]
try:
    mark = int(Path("run/outline_leg").read_text().strip() or 0)
except (OSError, ValueError):
    mark = 0

kept = []
for n in want:
    if not (mark < n <= len(lines)):
        print(f"refused {n}: not ahead of leg {mark}", file=sys.stderr)
        continue
    kept.append(n)
if not kept:
    sys.exit(3)

# highest first, so each removal leaves the lower positions where they were
for n in kept:
    print(f"crossed off leg {n}: {lines[n - 1]}")
    del lines[n - 1]
p.write_text("\n".join(lines) + "\n")
