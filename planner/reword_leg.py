#!/usr/bin/env python3
"""Replace one outline objective with the model's own restatement.

Its own file for the same reason insert_leg.py, skip_legs.py and
pull_leg.py are: the chain script already nests a heredoc, and a second
sharing the terminator silently truncated the block it was written into.

Only a position AHEAD of the run's high-water mark may be reworded — a
finished objective is history and history is not edited.

Usage: reword_leg.py N "the objective, said accurately"
"""
import sys
from pathlib import Path

if len(sys.argv) < 3:
    sys.exit(__doc__)
n, new = int(sys.argv[1]), sys.argv[2].strip()
if not new:
    sys.exit("reword_leg: empty objective")

p = Path("plans/outline.txt")
lines = [l for l in p.read_text().splitlines() if l.strip()]
try:
    mark = int(Path("run/outline_leg").read_text().strip() or 0)
except (OSError, ValueError):
    mark = 0
if not (mark < n <= len(lines)):
    sys.exit(f"reword_leg: {n} is not ahead of leg {mark}")

old = lines[n - 1]
lines[n - 1] = new
p.write_text("\n".join(lines) + "\n")
with Path("run/outline_rewordings").open("a") as fh:
    fh.write(f"{n}\t{old}\t{new}\n")
print(f"leg {n} reworded\n  was: {old}\n  now: {new}")
