#!/usr/bin/env python3
"""A drop paragraph hands over an op, so it has to say the op can run.

The shim marks every drop cell reachable or not, and this paragraph read
that only to say "N of them you can walk to" -- a clause for a MIXED
floor, skipped when they are all reachable and skipped again when NONE
is.  All-none is the case that matters.

Run 16 stood in POKEMON_MANSION_3F|5,8 thirteen times.  The page named
the three drop cells and handed over the walk_to form to take one, and no
walk from that part of the floor reaches any of them; the other part it
has walked does.  It never took one, and leg 40 failed on the basement
through three subgoals in a row while those drops were the only way into
the sealed room the basement stairs stand in.

The statue paragraph learned this on 2026-08-23 and says "BUT NO WALK
FROM WHERE YOU STAND REACHES THAT PRESS CELL RIGHT NOW" one clause after
its op.  Drops never got the same sentence.  Synthetic: no game, no
model.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger                                          # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))


class _Ex:
    explored = {"POKEMON_MANSION_3F|5,8": {}}
    visits = {"POKEMON_MANSION_3F|5,8": 13}
    frontier = {}
    def _where(self, _o): return "POKEMON_MANSION_3F|5,8"
    def __getattr__(self, _n): return {}


def head(holes):
    m = {"id": "POKEMON_MANSION_3F", "region": "5,8", "holes": holes}
    return ledger.render([], _Ex(), {"party": [], "map": m}).splitlines()[0]


def drop(x, y, grp, reach):
    return {"x": x, "y": y, "drop": grp, "reachable": reach}


NONE = [drop(16, 14, 1, False), drop(17, 14, 1, False), drop(19, 14, 2, False)]
MIXED = [drop(16, 14, 1, True), drop(19, 14, 2, False)]
ALL = [drop(16, 14, 1, True), drop(19, 14, 2, True)]

h_none, h_mixed, h_all = head(NONE), head(MIXED), head(ALL)

# ---- none of them reachable --------------------------------------------
ck("the drops are still named", "(16,14)+(17,14), (19,14)" in h_none)
ck("...and it says no walk from here reaches any of them",
   "BUT NO WALK FROM WHERE YOU STAND REACHES ANY OF THEM RIGHT NOW" in h_none)
ck("...and the walk_to form is still offered",
   '{"op":"walk_to","x":N,"y":N}' in h_none)
ck("...and it does not also mark each one, having said it once",
   "(no walk from here reaches it)" not in h_none)
ck("...and it does not claim a count you can walk to",
   "of them you can walk to" not in h_none)

# ---- some of them ------------------------------------------------------
ck("a mixed floor still counts the ones you can walk to",
   "1 of them you can walk to" in h_mixed)
ck("...and marks the one you cannot, beside its coordinates",
   "(19,14) (no walk from here reaches it)" in h_mixed)
ck("...and does not say none of them can be reached",
   "REACHES ANY OF THEM" not in h_mixed)

# ---- all of them -------------------------------------------------------
ck("when every drop can be walked to, nothing is said about reach",
   "no walk" not in h_all and "of them you can walk to" not in h_all)
ck("...and the drops and the op are still there",
   "(16,14)" in h_all and '{"op":"walk_to","x":N,"y":N}' in h_all)

# ---- the rest of the paragraph is untouched ----------------------------
for nm, h in (("none", h_none), ("mixed", h_mixed), ("all", h_all)):
    ck(f"a drop is still one-way ({nm})",
       "no climbing back up it" in h and "takes no use_warp" in h)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
if bad:
    for nm, h in (("NONE", h_none), ("MIXED", h_mixed), ("ALL", h_all)):
        i = h.find("ONE-WAY DROP")
        print("\n" + nm + ":", h[max(0, i - 20):i + 280])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
