#!/usr/bin/env python3
"""Forget that named things on one floor were ever pressed.

    tools/forget_press.py "ROUTE_12_GATE_2F|0,2" ROUTE12GATE2F_BRUNETTE_GIRL \
        TEXT_ROUTE12GATE2F_LEFT_BINOCULARS --item TM_SWIFT

FOR WHEN THE GAME WENT BACK AND THE MEMORY DID NOT. The memory file is
written as the run goes; the game is saved at the end of an attempt. An
attempt that died mid-round (run 16, 2026-09-08, before the executor learned
to save on a crash) left the game reloaded from the leg's opening save while
the memory still held presses made after it: the Route 12 gate's upstairs
girl "handed over TM39", and the bag had no TM39. A press the game has no
record of is a press that never happened, so this drops it from every place
the memory keeps one: touched, touch_mark, the hint she spoke, its clock,
the outcome rows, and the item's giver. Sightings stay (she was seen) and
walked ground stays (ground does not roll back).

Refuses while an executor runs: it holds the memory in RAM and writes it
back, so an edit under it would be lost. Backs the file up first.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEM = ROOT / "run" / "explored.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region", help='e.g. "ROUTE_12_GATE_2F|0,2"')
    ap.add_argument("names", nargs="+", help="object names as the ledger prints them")
    ap.add_argument("--item", action="append", default=[],
                    help="an item whose giver record (item_from) should go too")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if subprocess.run(["pgrep", "-f", "planner/executor.py"], capture_output=True).returncode == 0:
        sys.exit("an executor is running and would write the memory back over this edit; "
                 "run this between attempts")
    d = json.loads(MEM.read_text())
    names = set(a.names)
    changes = []

    lst = d.get("touched", {}).get(a.region) or []
    keep = [n for n in lst if n not in names]
    if len(keep) != len(lst):
        changes.append(f"touched: -{len(lst) - len(keep)}")
        d["touched"][a.region] = keep
    tm = d.get("touch_mark", {}).get(a.region) or {}
    for n in list(tm):
        if n in names:
            del tm[n]; changes.append(f"touch_mark: -{n}")
    hints = d.get("hints", {}).get(a.region) or []
    keep = [h for h in hints if not any(str(h).startswith(n + ":") for n in names)]
    if len(keep) != len(hints):
        changes.append(f"hints: -{len(hints) - len(keep)}")
        d["hints"][a.region] = keep
    ha = d.get("hints_at", {}).get(a.region) or {}
    for h in list(ha):
        if any(str(h).startswith(n + ":") for n in names):
            del ha[h]; changes.append("hints_at: -1")
    for key, rows in (d.get("outcomes") or {}).items():
        if not str(key).endswith("|" + a.region) or not isinstance(rows, dict):
            continue
        for n in list(rows):
            if n in names:
                del rows[n]; changes.append(f"outcomes[{key.split('|')[0]}]: -{n}")
    for it in a.item:
        if it in (d.get("item_from") or {}):
            del d["item_from"][it]; changes.append(f"item_from: -{it}")

    if not changes:
        print("nothing to forget: no such presses recorded"); return
    print("\n".join(changes))
    if a.dry:
        print("(dry run; nothing written)"); return
    bak = MEM.with_name(f"explored.{time.strftime('%H%M%S')}.pre-forget.bak.json")
    bak.write_text(MEM.read_text())
    MEM.write_text(json.dumps(d, indent=1))
    print(f"written; backup at {bak.name}")


if __name__ == "__main__":
    main()
