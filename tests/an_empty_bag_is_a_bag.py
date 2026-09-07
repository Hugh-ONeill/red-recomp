"""A thing gone from an EMPTY bag is gone.

Run 16, leg 2 (2026-09-07): the parcel was delivered, EVENT_OAK_GOT_PARCEL
and EVENT_GOT_POKEDEX fired, the status line read "BAG 0/20 {}" -- and the
step's witness {"lacks_item": ["OAKS_PARCEL"]} stayed false through two
attempts, until the model asked to skip the step and the attempt failed.
The shim's bag is a Lua table keyed by item name; an empty Lua table has no
keys to say it was a map, so it arrives as [], and lacks_item read that as
"no readable bag".  The parcel was the only thing the party had ever held,
so the one deed lacks_item was written for (a bag emptied) was the one it
could never witness.

A missing bag, or a screen that is not the overworld, is still unreadable:
those refusals stay.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E

ck("an empty bag, on the overworld, lacks the parcel",
   E.pred_holds({"lacks_item": ["OAKS_PARCEL"]}, {"mode": "overworld", "bag": []}))
ck("...as a single name too",
   E.pred_holds({"lacks_item": "OAKS_PARCEL"}, {"mode": "overworld", "bag": []}))
ck("a bag still holding it does not",
   not E.pred_holds({"lacks_item": ["OAKS_PARCEL"]},
                    {"mode": "overworld", "bag": {"OAKS_PARCEL": 1}}))
ck("a missing bag is unreadable, not empty",
   not E.pred_holds({"lacks_item": ["OAKS_PARCEL"]}, {"mode": "overworld"}))
ck("a box up is unreadable, not empty",
   not E.pred_holds({"lacks_item": ["OAKS_PARCEL"]}, {"mode": "dialog", "bag": []}))
ck("fewer kinds than N holds on an empty bag",
   E.pred_holds({"bag_kinds_below": 20}, {"mode": "overworld", "bag": []}))
ck("has_item on an empty bag is false, as before",
   not E.pred_holds({"has_item": {"POTION": 1}}, {"mode": "overworld", "bag": []}))

# ...and the fold happens where observations enter, for every reader
import json, tempfile
from pathlib import Path
import bridge as B
import author as A
tmp = Path(tempfile.mkdtemp(dir="/tmp/claude-1000/-home-wiz/"
                            "b5fe8565-91da-4233-b62f-8b773e98e750/scratchpad"))
(tmp / "obs.json").write_text(json.dumps({"seq": 1, "mode": "overworld",
                                          "bag": [], "pc_items": [],
                                          "key_items": [], "badges": []}))
o = B.Bridge(tmp).obs()
ck("the bridge hands out an empty bag as a map", o["bag"] == {} and o["pc_items"] == {})
ck("...and leaves lists that are lists alone", o["badges"] == [] and o["key_items"] == [])
ck("the author's reader does the same", A._obs_now(tmp / "obs.json")["bag"] == {})
ck("a full bag is untouched",
   B.normalize_obs({"bag": {"POTION": 2}})["bag"] == {"POTION": 2})

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
