#!/usr/bin/env python3
"""A bag slot freed, or a thing gone, can be a witness (2026-09-04).

has_item is "at least N", so "Clear space in the bag" was written as
{"has_item":{"POTION":3}} — meant as "down to three", true with four in the
bag — and the plan completed before its first step ran; the chain caught it
afterwards and burned the attempt. lacks_item and bag_kinds_below say the other
direction. Both need a READABLE bag: an observation taken with a menu up
carries no bag, and an empty read must not pass for an empty bag (the same
round's status line read "BAG 0/20 {}" with twenty kinds held).

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

full = {f"K{i}": 1 for i in range(20)}
ow = lambda bag: {"mode": "overworld", "bag": bag}
ck("bag_kinds_below: fewer kinds than N holds", E.pred_holds({"bag_kinds_below": 20}, ow({"POTION": 4})))
ck("...a full bag does not", not E.pred_holds({"bag_kinds_below": 20}, ow(full)))
ck("...an empty bag in the overworld does", E.pred_holds({"bag_kinds_below": 20}, ow({})))
ck("lacks_item as a name", E.pred_holds({"lacks_item": "REPEL"}, ow({"POTION": 4})))
ck("...as a list, all must be gone", not E.pred_holds({"lacks_item": ["REPEL", "POTION"]}, ow({"POTION": 4})))
ck("...as a dict", E.pred_holds({"lacks_item": {"REPEL": 1}}, ow({"POTION": 4})))
ck("...a kind still held fails it", not E.pred_holds({"lacks_item": "POTION"}, ow({"POTION": 1})))
ck("a bag hidden behind a menu is not an empty bag (bag_kinds_below)",
   not E.pred_holds({"bag_kinds_below": 20}, {"mode": "ui", "bag": {}}))
ck("...nor for lacks_item", not E.pred_holds({"lacks_item": "REPEL"}, {"mode": "ui"}))
ck("...nor in a battle", not E.pred_holds({"bag_kinds_below": 20}, {"mode": "battle", "bag": {}}))
ck("...and a missing bag is unreadable", not E.pred_holds({"bag_kinds_below": 20}, {"mode": "overworld"}))
ck("has_item is unchanged: at least N", E.pred_holds({"has_item": {"POTION": 3}}, ow({"POTION": 4}))
   and not E.pred_holds({"has_item": {"POTION": 5}}, ow({"POTION": 4})))
ck("a bad N fails closed", not E.pred_holds({"bag_kinds_below": "lots"}, ow({"POTION": 4})))
src = (ROOT / "planner" / "executor.py").read_text()
ck("both earn a gate's round budget",
   'is_gate = bool(dw_kind & {"flag", "badge", "has_item", "lacks_item",\n                                  "bag_kinds_below"})' in src)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
