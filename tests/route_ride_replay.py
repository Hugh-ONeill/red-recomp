"""A leg walked while riding is re-walked while riding.

`cross` hops already carried the ride (_go_surf); DOOR hops did not, and
use_warp walks on foot.  Seafoam's B3F|1,0 --25,14--> B2F|23,10 -- the one
swim joining the island's two halves -- failed on every replay, took a
blocked_at stamp, and darkened all six hops between the halves at once.
Re-opening a way this run opened itself is mechanics, the same class as the
regrown-bush re-cut beside it; WHERE to go was the model's when it asked for
the route.  Fresh water stays opt-in: this fires only on a walked door hop
that just failed to reach, on a floor that has water.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

def should_ride(*, landed_short, is_door, already_rode, knows_surf,
                has_water, detail):
    """The guard as _walk_route applies it."""
    return bool(landed_short and is_door and not already_rode
                and knows_surf and has_water
                and "couldn't reach" in detail)

REACH = ("couldn't reach the warp tile (no path — the ground you can walk "
         "from here is 189 cell(s) and the closest it comes to 25,14 is 18,14)")
BASE = dict(landed_short=True, is_door=True, already_rode=False,
            knows_surf=True, has_water=True, detail=REACH)

ck("the Seafoam swim is re-walked riding", should_ride(**BASE))
ck("a hop that landed is left alone", not should_ride(**{**BASE, "landed_short": False}))
ck("a seam hop is not a door hop", not should_ride(**{**BASE, "is_door": False}))
ck("it never rides twice for one hop", not should_ride(**{**BASE, "already_rode": True}))
ck("no SURF, no ride", not should_ride(**{**BASE, "knows_surf": False}))
ck("a dry floor is never ridden", not should_ride(**{**BASE, "has_water": False}))
ck("a door held shut by a script is not a swim",
   not should_ride(**{**BASE,
                      "detail": "you reached the door and it refused to open"}))
ck("'no fire' is not a reach failure",
   not should_ride(**{**BASE, "detail": "stepped through but no warp fired"}))
ck("somebody in the doorway still counts as unreached",
   should_ride(**{**BASE,
                  "detail": "couldn't reach the warp tile — somebody is "
                            "standing by it"}))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
