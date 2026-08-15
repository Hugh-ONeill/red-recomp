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

# CROSSED OFF IS NOT FORGOTTEN. An objective that leaves the list because
# it is finished is still something this run accomplished, and the record
# of what is done — outline.done, which nothing ever schedules from — is
# what later passes read to know which doors are open.
ledger = Path("plans/outline.done")
try:
    seen = {l.split("\t")[0].strip().lower()
            for l in ledger.read_text().splitlines() if l.strip()}
except OSError:
    seen = set()

# highest first, so each removal leaves the lower positions where they were
with ledger.open("a") as fh:
    for n in kept:
        text = lines[n - 1]
        print(f"crossed off leg {n}: {text}")
        if text.strip().lower() not in seen:
            fh.write(f"{text}\t\n")
            seen.add(text.strip().lower())
        del lines[n - 1]
p.write_text("\n".join(lines) + "\n")
