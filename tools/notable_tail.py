#!/usr/bin/env python3
"""Print notable.jsonl lines at or above a severity, as they are appended.

The reader half of planner/notable.py for a session that wants a STREAM
rather than one wake: it blocks on the file growing and prints one short
line per event. Severity floor is argv[1] (default warn), so the info
tier — leg and subgoal starts — stays on disk to be read on demand.
"""
import json
import sys
import time
from pathlib import Path

RANK = {"info": 0, "warn": 1, "plan": 2, "alarm": 3}
floor = RANK.get((sys.argv[1] if len(sys.argv) > 1 else "warn").lower(), 1)
path = Path(__file__).resolve().parent.parent / "run" / "notable.jsonl"

while not path.exists():
    time.sleep(5)
with path.open() as fh:
    fh.seek(0, 2)                       # only what happens from now on
    while True:
        line = fh.readline()
        if not line:
            time.sleep(2)
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if RANK.get(r.get("sev"), 0) >= floor:
            print("[%s] %s: %s" % (str(r.get("sev")).upper(),
                                   r.get("kind"), r.get("what")), flush=True)
