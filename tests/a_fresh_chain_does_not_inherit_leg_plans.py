#!/usr/bin/env python3
"""A fresh chain keeps the outline and drops the leg plans.

Run 15, 2026-08-29: the chain archived the save, the journal and every
ledger, kept plans/outline.txt as banked luck — and also kept
leg_14_a_party_pokemon_knows_cut.v1.json, which said "Teach the move CUT
to Gloom using HM01 from the bag". Gloom belonged to the Hall of Fame
world; the run opened every PC in Vermilion hunting it (user: "we probably
shouldnt keep the leg plans on a fresh chain, that wouldnt exactly be
fresh would it?"). An outline is a list of objectives; a leg plan is
written in front of a party, a bag and a walked graph, all of which the
fresh block has just archived. Archived, not deleted.
"""
import sys
from pathlib import Path
sh = (Path(__file__).resolve().parents[1] / "fresh_discovery.sh").read_text()
blk = sh[sh.index("if [ \"$done_legs\" = 0 ]; then"):sh.index("if [ -s plans/outline.txt ]; then")]
checks = []
def ck(n, ok): checks.append((n, bool(ok)))
ck("the fresh block archives this world's leg plans",
   "for _p in plans/leg_[0-9]*.json; do" in blk
   and 'mv -f "$_p" "plans/archive/${ts}-pre-discovery-$(basename "$_p")"' in blk)
ck("...and the outline's per-leg sidecars with them",
   "for _f in plans/outline.stages plans/outline.upkeep plans/outline.notes" in blk)
ck("...archived, never deleted", "rm -f plans/leg_" not in blk)
ck("the outline itself is still kept (banked luck)",
   "keeping existing plans/outline.txt" in sh
   and "outline restored as authored" in sh)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
