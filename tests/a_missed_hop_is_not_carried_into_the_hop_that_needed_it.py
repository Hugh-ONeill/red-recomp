#!/usr/bin/env python3
"""A failed PLACE step is not carried into another place step naming a map
the run has never walked.

The carry exists so ONE missed map hop does not forfeit a plan whose later
steps may still be reachable. Three place steps in a chain are the case it
was not written for: leg 9 gave up on go_to_vermilion_city, carried, gave
up on enter_ss_anne (SS_ANNE_BOW, never walked), carried, and was trying
reach_ss_anne_1f from Cerulean. Each step was strictly harder than the one
just abandoned, and each spends its own escalation budget from a place it
cannot succeed from (2026-09-14, user: "can multiple things get carried
past? it seems that way").

Now the plan ends there and is rewritten from where the party stands,
which is the honest state to plan from. Carrying into a DEED, or into a
place the run has already walked, is untouched, and so is the rule that
an event gate is never carried past at all.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

src = (ROOT / "planner" / "executor.py").read_text()
i = src.index("_chain and not last")
blk = src[i - 2600:i + 900]

ck("the rule reads the NEXT step", "_nxt = (subgoals[idx + 1]" in blk)
ck("...only when that next step is a pure place step",
   '_PLACE = {"map", "area", "not_area", "new_part"}' in blk
   and "(_keys(_nxt) or set()) <= _PLACE" in blk)
ck("...and takes its map from whichever place key it used",
   '_dw.get("map") or _dw.get("new_part")' in blk and '.get("area") or "").split("|")[0]' in blk)
ck("...and asks the run's own feet whether that map is known",
   'str(r).split("|")[0] == _nxt_map' in blk and "for r in (self.visits or {})" in blk)
ck("the failed step must itself be a place step",
   "bool(_keys(sg)) and (_keys(sg) or set()) <= _PLACE" in blk)
ck("...and then the plan stops instead of carrying",
   "not carrying a \"\n                          f\"missed hop into the hop that needed it" in blk)
ck("...saying which step wanted what", 'f"({_nxt.get(\'id\')}) asks for {_nxt_map}, which "' in blk)
ck("...and it is on the record", '"chain_subgoal_failed"' in blk)
ck("an event gate is still never carried past, and is tested first",
   blk.index("if gate:") < blk.index("elif _chain and not last:"))
ck("the ordinary carry still follows it",
   blk.index("elif _chain and not last:") < blk.index("elif fails < 3 and not last:"))
ck("the last subgoal is still never carried",
   blk.count("and not last") >= 2)

# the shape of the decision, checked as arithmetic on the same predicates
PLACE = {"map", "area", "not_area", "new_part"}
def chain(failed_keys, next_keys, next_map, walked):
    return (bool(failed_keys) and set(failed_keys) <= PLACE
            and set(next_keys) <= PLACE and bool(next_map)
            and not any(r.split("|")[0] == next_map for r in walked))
ck("place then unwalked place: the chain stops",
   chain({"map"}, {"map"}, "SS_ANNE_BOW", {"CERULEAN_CITY|1,1"}))
ck("place then a place already walked: carried as before",
   not chain({"map"}, {"map"}, "VERMILION_CITY", {"VERMILION_CITY|18,0"}))
ck("place then a DEED: carried as before",
   not chain({"map"}, {"has_item"}, "", {"CERULEAN_CITY|1,1"}))
ck("a DEED that failed is carried as before, wherever it points",
   not chain({"has_item"}, {"map"}, "SS_ANNE_BOW", {"CERULEAN_CITY|1,1"}))
ck("a step with no condition at all is left to the other rules",
   not chain(set(), {"map"}, "SS_ANNE_BOW", {"CERULEAN_CITY|1,1"}))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
