#!/usr/bin/env python3
"""A crossing that lands mid-warp is still a crossing.

settle() rode out dialog and nothing else, so an observation taken while
the screen is still mid-warp came back with map.id None.  _where then
reads "None|None", and note_transition returns at its first guard, which
was the one guard that said nothing when it dropped an edge.

Only a DROP lands you there.  Every other way between maps is a use_warp
or a cross, and both settle before the executor reads.  Run 16 walked onto
the Mansion drop at (17,14) on purpose at 15:49:53, came out a floor
below, and the atlas learned nothing: no edge, no visit, no log line.  The
drop rows still read "never taken from here" afterwards, so the one thing
it had just proved was the way out went on being described to it as
untried (user, 2026-09-10: "it should know the way out is through the hole
then").

Synthetic: a scripted observation source, no game.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))


def _mk(reads):
    """An executor whose obs() yields `reads` in order, last one repeating."""
    ex = E.Executor.__new__(E.Executor)
    seen = {"i": 0}

    def _obs():
        i = min(seen["i"], len(reads) - 1)
        seen["i"] += 1
        return reads[i]
    ex.b = type("B", (), {"obs": staticmethod(_obs)})()
    ex.waits = 0

    def _send(op, **kw):
        if op == "wait":
            ex.waits += 1
        return _obs()
    ex._send_safe = _send
    ex._after_settle = lambda o: o
    return ex, seen


MID = {"mode": "overworld", "map": {}, "player": {"x": 16, "y": 14}}
LAND = {"mode": "overworld", "map": {"id": "POKEMON_MANSION_2F",
                                     "region": "10,1"},
        "player": {"x": 18, "y": 14}}

# ---- the mid-warp read is ridden out -----------------------------------
ex, _ = _mk([MID, MID, LAND])
out = ex.settle()
ck("a nameless map is waited out, not returned",
   (out.get("map") or {}).get("id") == "POKEMON_MANSION_2F", out.get("map"))
ck("...with a bounded number of waits", 0 < ex.waits <= 8, ex.waits)

# ---- and a settled read still costs nothing -----------------------------
ex2, _ = _mk([LAND])
ck("an already-settled read waits for nothing",
   ex2.settle() is LAND and ex2.waits == 0, ex2.waits)

# ---- dialog is still ridden out, as before ------------------------------
DLG = {"mode": "dialog", "map": {"id": "POKEMON_MANSION_2F", "region": "10,1"}}
ex3, _ = _mk([DLG, DLG, LAND])
ck("a dialog box is still ridden out",
   (ex3.settle() or {}).get("mode") == "overworld")

# ---- a map that never names itself gives up rather than hanging ---------
ex4, _ = _mk([MID])
ck("a read that never settles still returns", ex4.settle() is not None)
ck("...after a bounded wait", ex4.waits <= 8, ex4.waits)

# ---- and the guard that drops such an edge now says so ------------------
SRC = (ROOT / "planner" / "executor.py").read_text()
blk = SRC.split("def note_transition", 1)[1][:1800]  # widened: the
# guard grew a comment when its first firing showed it printing half a cell
ck("the no-region guard logs the edge it refuses",
   "transition_dropped_no_region" in blk)
ck("...naming where it was going and by which tile",
   'frm=src, to=dst' in blk and "via=" in blk)
# A COORDINATE CUT IN HALF READS LIKE A SEAM. Its first firing logged a
# door at (5,10) as "via 5" (2026-09-10).
ck("...as a whole cell, never half of one",
   'f"{_sx},{_sy}"' in blk and '.get("x", ' not in blk)
ck("...falling back to the direction for a seam",
   '.get("dir")' in blk)
ck("...and every other drop guard already logged",
   SRC.count("transition_dropped_") >= 4)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d) + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
