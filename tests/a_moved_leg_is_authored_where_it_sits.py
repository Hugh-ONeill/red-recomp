#!/usr/bin/env python3
"""A leg that is moved is authored again where it now sits.

A plan is written at the moment its leg starts, with the walked graph
and the journal in front of the author — but a pushed or pulled leg kept
its old plan by name, so "Obtain the Secret Key", moved by hand to after
Cinnabar, started on a v37 written in the Safari Zone and went straight
back there (2026-08-28). On a move the leg's plans are archived (never
deleted) and its next start writes one from where the run actually is.
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(name, ok): checks.append((name, bool(ok)))
sh = (ROOT / "fresh_discovery.sh").read_text()
ck("the script parses", subprocess.run(["bash", "-n", str(ROOT / "fresh_discovery.sh")]).returncode == 0)
h = sh.index("archive_plans_of() {")
blk = sh[h:h + 700]
ck("the helper finds the leg's plans by objective, not by position", 'find_plan.py "$1"' in blk)
ck("...and archives every version rather than deleting", "plans/archive/${_stamp}-moved-" in blk and "rm " not in blk)
for site in ("moved to after leg $at", "authoring failed; moved to after leg $_after", "a pull that put it here was undone"):
    j = sh.index(f'disposed "{site}"')
    ck(f"a move archives the plans: {site[:28]}", 'archive_plans_of "$leg"' in sh[j:j + 200])
ck("a reword needs none (its plans match nothing by name anyway)",
   'archive_plans_of' not in sh[sh.index('disposed "reworded to: $said"'):sh.index('disposed "reworded to: $said"') + 120])
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
