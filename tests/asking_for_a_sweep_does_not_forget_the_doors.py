#!/usr/bin/env python3
"""Asking for a sweep does not make the harness forget untaken doors.

explore's destination picker ranks the areas the run has walked by what is
left to do in them, in tiers, with distance deciding only INSIDE a tier.
Three things count as left to do:

  unseen   ground on that floor never on screen
  left     an exit there never taken
  _unr     a doorway on ground you HAVE stood on that no walk from there
           reaches — the Seafoam far door, the Route 20 west mat

The ordinary branch counts all three. The sweep branch — taken whenever the
model writes an `until` or `steps` on its explore, which it does almost
every time — counted the first two and dropped the third, so a region whose
whole remaining business was a door nobody can reach ranked BELOW a region
with nothing left at all.

Live, 2026-09-05, five rounds running, with the party on Route 20's water
and Cinnabar the goal (user: "when its doing sweep its being directed to rt
15 or 18 ... from like, doing sweep in the ocean" / "it would be cool if
sweep would bring it closer to its goal instead of the opposite
direction"). Every round the model wrote {"op":"explore","until":
"map_change"}; every round the picker walked it three or four legs to Route
15 or Route 18 for their unseen spots; every round the model wrote "I am on
Route 15, I need to go back to Route 20" and walked itself back. Its
judgment was right each time and the harness overrode it each time.

Unseen ground still leads under a sweep intent — that is what `until` asked
to go and look at. What this pins is that a way out never taken is not
nothing.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

def tier(sweep_intent, *, unseen, left, unr, map_goal=True):
    """The picker's _pri, both branches, as _explore_step computes it."""
    if sweep_intent:
        return 0 if unseen else 1 if (left or unr) else 2
    return (0 if (left or unseen or unr) else 1) if map_goal else 0

# Route 20, as it actually stood: Seafoam 1F one leg away with two doors
# never opened and nothing to sweep; Route 18 three legs away with unseen
# ground; a worked-out room with nothing at all.
SEAFOAM = dict(unseen=0, left=0, unr=2)
ROUTE18 = dict(unseen=5, left=1, unr=0)
EMPTY   = dict(unseen=0, left=0, unr=0)

for intent in (True, False):
    what = "under a sweep intent" if intent else "on a plain explore"
    ck(f"a door nobody can reach beats nothing at all, {what}",
       tier(intent, **SEAFOAM) < tier(intent, **EMPTY))
ck("...and that was the bug: it used to tie with nothing",
   (0 if SEAFOAM["unseen"] else 1 if SEAFOAM["left"] else 2)
   == (0 if EMPTY["unseen"] else 1 if EMPTY["left"] else 2))

ck("unseen ground still leads when a sweep was what was asked for",
   tier(True, **ROUTE18) < tier(True, **SEAFOAM))
ck("...and on a plain explore the two are one tier, so distance decides",
   tier(False, **ROUTE18) == tier(False, **SEAFOAM))
ck("an untaken exit and an unreachable doorway rank together under a sweep",
   tier(True, unseen=0, left=1, unr=0) == tier(True, **SEAFOAM))
ck("a worked-out area is last either way",
   tier(True, **EMPTY) == 2 and tier(False, **EMPTY) == 1)

src = (ROOT / "planner/executor.py").read_text()
i = src.index("_sweep_intent = bool(")
ck("the sweep tier counts unreachable ways out",
   "_pri = 0 if unseen else 1 if (left or _unr) else 2" in src[i:i + 1600])
ck("...and the ordinary tier still counts all three",
   "_pri = (0 if (left or unseen or _unr) else 1) if _map_goal else 0" in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
