#!/usr/bin/env python3
"""A walk_to written before a press that finds its own way does not make
it a different set of ops, so the repeat guard cannot be dodged with one.

Vermilion Gym, run 17 (2026-09-14): a round of [walk_to 9,11; interact
TRASH_CAN_14; walk_to 3,9; interact TRASH_CAN_4] changed nothing and was
refused on its repeat. The next rounds sent the same two presses behind
walk_to (9,12), then (5,5), then (0,11), then (0,0), and each was a new
key and was carried out: twelve rounds on two cans, with the plan text
saying "To avoid the 'identical ops' refusal, I will walk to a different
coordinate first". A press by name paths to the thing itself; the walk
before it is not part of what was done. The guard now keys on the ops that
decide what happens, and its refusal says which walks were not counted.
A walk before a cross, a sweep, a grind, or an untargeted press still
counts: those act from where you stand.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

K = E.Executor._repeat_key_ops
W = lambda x, y: {"op": "walk_to", "x": x, "y": y}
P14 = {"op": "interact", "name": "TRASH_CAN_14", "answer": "yes"}
P4 = {"op": "interact", "name": "TRASH_CAN_4", "answer": "yes"}

base, n0 = K([W(9, 11), P14, W(3, 9), P4])
ck("walks before presses by name are left out of the key", base == [P14, P4] and n0 == 2, (base, n0))
for decoy in ([W(9, 12), P14, W(3, 10), P4],
              [W(5, 5), W(9, 11), P14, W(3, 9), P4],
              [W(0, 0), W(9, 11), P14, W(3, 9), P4],
              [P14, P4]):
    ops, n = K(decoy)
    ck(f"...so {decoy[0]} first keys the same as the bare presses", ops == base, (ops, n))
ck("...and the count of walks left out is reported", K([W(0, 0), W(9, 11), P14, W(3, 9), P4])[1] == 3)

# what still counts: ops that act from where you stand
cross = {"op": "cross", "dir": "west"}
ck("a walk before a cross is kept (the crossing cell decides where you come out)",
   K([W(3, 20), cross]) == ([W(3, 20), cross], 0))
sweep = {"op": "sweep"}
ck("a walk before a sweep is kept", K([W(3, 20), sweep]) == ([W(3, 20), sweep], 0))
grind = {"op": "grind", "intent": "catch", "want": "SPEAROW"}
ck("a walk before a grind is kept", K([W(6, 4), grind]) == ([W(6, 4), grind], 0))
surf = {"op": "field_move", "move": "SURF"}
ck("a walk before an untargeted field move is kept", K([W(3, 20), surf]) == ([W(3, 20), surf], 0))
cut = {"op": "field_move", "move": "CUT", "x": 15, "y": 18}
ck("...but one before a targeted field move is not", K([W(14, 18), cut]) == ([cut], 1))
press_here = {"op": "interact"}
ck("a walk before a press with no target is kept", K([W(3, 6), press_here]) == ([W(3, 6), press_here], 0))
door = {"op": "use_warp", "x": 12, "y": 19}
ck("a walk before a door op is not", K([W(12, 20), door]) == ([door], 1))
go = {"op": "go", "to": "ROUTE_5"}
ck("a walk before a go is not", K([W(1, 1), go]) == ([go], 1))
ck("a trailing walk is left to the strip that owns it", K([P14, W(3, 9)]) == ([P14, W(3, 9)], 0))
ck("non-dict entries are ignored", K([None, "x", P14]) == ([P14], 0))
ck("an empty macro keys empty", K([]) == ([], 0) and K(None) == ([], 0))

# the guard uses it, and says so when it mattered
src = (ROOT / "planner" / "executor.py").read_text()
i = src.index("_key_ops, _decoy_walks = self._repeat_key_ops(macro)")
ck("the repeat key is built from the deciding ops",
   'json.dumps(_key_ops, sort_keys=True), str(_mk_now))' in src[i:i + 400])
ck("the refusal says which walks were not counted",
   "walk_to step(s) you wrote" in src and "find their own way" in src
   and "different walk before them" in src and "the same set of ops." in src)
ck("...and the record carries the count", "decoy_walks=_decoy_walks" in src)
ck("nothing here names a can or a room", "TRASH_CAN" not in src[i - 2000:i + 3000])

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
