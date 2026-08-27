#!/usr/bin/env python3
"""A run that only spent things is a dry run.

leg_delta reported "items no longer held: FULL_RESTORE, MAX_POTION" as
WHAT CHANGED, so the Secret Key leg's fourth run counted as a yield and
the dry gate never fired (2026-08-27). The bag going down — a potion
used, a candy tossed, a ball thrown — is not progress in the world.
"""
from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

tmp = Path(tempfile.mkdtemp(prefix="yield_"))
(tmp / "run").mkdir()
os.chdir(tmp)
def state(bag, flags=(), areas=("A|0,0",)):
    (tmp / "run/obs.json").write_text(json.dumps(
        {"flags": list(flags), "bag": bag, "badges": [], "party": [{"species": "GLOOM", "level": 43}],
         "map": {"id": "SAFARI_ZONE_WEST"}}))
    (tmp / "run/explored.json").write_text(json.dumps({"visits": {a: 1 for a in areas}}))
def delta(mode, path="run/snap.json"):
    out = subprocess.run([sys.executable, str(ROOT / "planner/leg_delta.py"), mode, path],
                         capture_output=True, text=True, cwd=tmp)
    return out.stdout.strip()

state({"FULL_RESTORE": 1, "MAX_POTION": 1, "HM_SURF": 1})
delta("snap")
state({"HM_SURF": 1})
t = delta("diff")
ck("a run that only used up items starts with NOTHING", t.startswith("NOTHING"))
ck("...and still says what went", "only the bag went down" in t and "FULL_RESTORE" in t)

state({"HM_SURF": 1}); delta("snap")
state({"HM_SURF": 1, "FULL_RESTORE": 1})
t = delta("diff")
ck("an item picked up is a yield", t.startswith("WHAT CHANGED") and "items gained: FULL_RESTORE x1" in t)

state({"HM_SURF": 1}); delta("snap")
state({"HM_SURF": 1}, areas=("A|0,0", "SAFARI_ZONE_SECRET_HOUSE|2,2"))
t = delta("diff")
ck("a place entered for the first time is a yield", t.startswith("WHAT CHANGED") and "entered for the first time" in t)

state({"HM_SURF": 1, "POTION": 2}); delta("snap")
state({"HM_SURF": 1}, flags=("EVENT_GOT_HM03",))
t = delta("diff")
ck("an event that fired is a yield even while the bag went down",
   t.startswith("WHAT CHANGED") and "EVENT_GOT_HM03" in t and "POTION" in t)

state({"HM_SURF": 1}); delta("snap")
t = delta("diff")
ck("nothing at all: NOTHING, with no aside", t.startswith("NOTHING") and "bag went down" not in t)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
