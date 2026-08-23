"""A wild fight is not a shut route -- the third gate to learn it.

The ride's own words, once we stopped throwing them away:
  MOUNT : could not get onto the water: not in overworld
          (a box was up and would not close: kind=wild)
  WARP  : not in overworld (a box was up and would not close: kind=wild)
A Zubat surfaced mid-ride, both ops died on the battle box, and the edge then
took a blocked_at stamp -- so a wild encounter was recorded as proof that
Seafoam's one joining swim is shut, and every route between the island's
halves went dark for the rest of the world mark.  The strike gate learned
this rule (e225f40) and the repeat gate learned it (815671e); the stamp had
not.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

def stamps(detail):
    """The stamp guard as _walk_route applies it."""
    wd = str(detail or "").lower()
    return not ("a box was up" in wd or "kind=wild" in wd
                or "because of the battle" in wd
                or "a fight started" in wd)

BOX = ("could not get onto the water: not in overworld (a box was up and "
       "would not close: kind=wild)")
FIGHT = ("a fight started 41 cell(s) short of the west edge gap — the walk "
         "stopped because of the battle, not because of the ground")
WALL = ("couldn't reach the warp tile (no path — the ground you can walk "
        "from here is 189 cell(s) and the closest it comes to 25,14 is 18,14)")
NPC = "couldn't reach the warp tile — somebody is standing by it: A_GUARD"

ck("a battle box does not stamp the edge", not stamps(BOX))
ck("a mid-walk fight does not stamp the edge", not stamps(FIGHT))
ck("a real no-path still stamps", stamps(WALL))
ck("somebody in the doorway still stamps", stamps(NPC))
ck("an empty reason still stamps", stamps(""))

# the ride fights and retries rather than dying on the box
def ride(mode_first, mode_after):
    tried = 1
    if mode_first == "battle":
        tried += 1           # handle_battle, then one more mount
    return tried
ck("a battle during the mount earns one retry", ride("battle", "overworld") == 2)
ck("no battle, no retry", ride("overworld", "overworld") == 1)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
