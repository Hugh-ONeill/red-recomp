#!/usr/bin/env python3
"""What was unset while you were away is said, from the run's own record.

Victory Road, 2026-09-06. The game keeps each boulder-switch barrier in an
event flag and clears those flags from OTHER maps: 1F's when 2F or the
Plateau lobby is entered, 2F's and 3F's when Route 23 is (data/scripts/
story.lua, flavor/route_23.lua). Boulders go back to their starts on every
floor load. So the run walked out to Route 23 to heal and came back to every
way it had opened shut again, with its own plan echo still saying "the path
at (6,10) is already open".

The page already said "what UNSETS it again, if anything, is not recorded
here" — true of the RULE, which is the game's to keep. The FACT is the run's:
this way was open the last time the party stood on this floor, it is shut
now, and these are the maps entered since. Which of them did it is the
model's to work out, the way a player works it out over two trips (user:
"yeah do the since-your-last-visit note").

The trail folds consecutive repeats, numbers every entry so trimming never
moves a record's pointer, and a switch off screen (open_now nil) is never
recorded — no claim without the state on the page.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import executor as E                                 # noqa: E402
import ledger                                        # noqa: E402
import candidates as C                               # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

class Bare:                     # only what the two recorders touch
    def __init__(self):
        self._map_trail, self._map_seq, self.switch_seen = [], 0, {}
        self.saved = 0
    def _save_memory(self): self.saved += 1

def obs_on(mid, switches=None):
    o = {"map": {"id": mid, "region": "2,0", "warps": []},
         "player": {"x": 3, "y": 2}, "party": [], "bag": {}}
    if switches is not None:
        o["map"]["boulder_switches"] = switches
    return o

def sw(open_now):
    return [{"x": 3, "y": 5, "opens_x": 6, "opens_y": 10, "open_now": open_now,
             "held": False, "reachable": False}]

# --- the trail --------------------------------------------------------
b = Bare()
for mid in ("VICTORY_ROAD_3F", "VICTORY_ROAD_3F", "ROUTE_23", "VIRIDIAN_CITY",
            "VIRIDIAN_CITY", "VIRIDIAN_POKECENTER", "VIRIDIAN_CITY"):
    E.Executor._note_map(b, obs_on(mid))
ck("the trail folds consecutive repeats",
   [e[1] for e in b._map_trail] == ["VICTORY_ROAD_3F", "ROUTE_23", "VIRIDIAN_CITY",
                                    "VIRIDIAN_POKECENTER", "VIRIDIAN_CITY"])
ck("...and numbers every entry", [e[0] for e in b._map_trail] == [1, 2, 3, 4, 5] and b._map_seq == 5)
E.Executor._note_map(b, {"map": {"id": None}})
E.Executor._note_map(b, {})
ck("no map, no entry", b._map_seq == 5)
for i in range(60):
    E.Executor._note_map(b, obs_on(f"M{i}"))
ck("the trail is trimmed but the numbering is not",
   len(b._map_trail) == 40 and b._map_seq == 65 and b._map_trail[-1] == [65, "M59"])

# --- the switch record -------------------------------------------------
b = Bare(); E.Executor._note_map(b, obs_on("VICTORY_ROAD_3F"))
E.Executor._note_switches(b, obs_on("VICTORY_ROAD_3F", sw(None)))
ck("a switch off screen is not recorded", b.switch_seen == {} and b.saved == 0)
E.Executor._note_switches(b, obs_on("VICTORY_ROAD_3F", sw(True)))
ck("seen open, the record points at this moment in the trail",
   b.switch_seen.get("VICTORY_ROAD_3F|3,5") == {"open_at": 1, "shut": False} and b.saved == 1)
E.Executor._note_switches(b, obs_on("VICTORY_ROAD_3F", sw(True)))
ck("...and an unchanged state is not re-saved", b.saved == 1)
for mid in ("ROUTE_23", "VIRIDIAN_CITY", "VIRIDIAN_POKECENTER", "VIRIDIAN_CITY",
            "ROUTE_22", "ROUTE_23", "VICTORY_ROAD_1F", "VICTORY_ROAD_2F", "VICTORY_ROAD_3F"):
    E.Executor._note_map(b, obs_on(mid))
E.Executor._note_switches(b, obs_on("VICTORY_ROAD_3F", sw(False)))
ck("seen shut, the record keeps where it was last open",
   b.switch_seen["VICTORY_ROAD_3F|3,5"] == {"open_at": 1, "shut": True})

# --- the page -----------------------------------------------------------
def page(ex, open_now, mid="VICTORY_ROAD_3F"):
    ex._where = lambda o: f"{mid}|2,0"
    ex._explore_trips = {}
    return ledger.render([], ex, obs_on(mid, sw(open_now)), "map:INDIGO_PLATEAU")

ex = C.make(); ex.switch_seen = dict(b.switch_seen); ex._map_trail = list(b._map_trail)
t = page(ex, False)
ck("a way seen shut that was open last visit is said so",
   "that way is SHUT right now" in t and "IT WAS OPEN THE LAST TIME YOU STOOD ON THIS FLOOR" in t)
ck("...with the maps entered since, in order, folded, and this floor left off the end",
   "Since then you have entered: ROUTE_23, VIRIDIAN_CITY, VIRIDIAN_POKECENTER, ROUTE_22, "
   "VICTORY_ROAD_1F, VICTORY_ROAD_2F." in t)
ck("...and no word on which of them did it",
   "Which of those did it is not recorded here; your own path is" in t
   and "Route 23 resets" not in t and "resets" not in t.lower().split("since then")[1][:200])
ck("a way seen open carries no such note",
   "IT WAS OPEN THE LAST TIME" not in page(ex, True) and "OPEN RIGHT NOW" in page(ex, True))
t_off = page(ex, None)
ck("a switch off screen claims no present state",
   all(s not in t_off for s in ("SHUT right now", "OPEN RIGHT NOW", "IT WAS OPEN THE LAST TIME")))
# ...but the run's own last look is said as a last look (2026-09-06: the model
# shoved a boulder onto 2F's (1,16) whose way it had seen open earlier in the
# visit, because the off-screen line carried no verdict at all)
ex4 = C.make(); ex4.switch_seen = {"VICTORY_ROAD_3F|3,5": {"open_at": 1, "shut": False}}
ex4._map_trail = [[1, "VICTORY_ROAD_3F"]]
t4 = page(ex4, None)
ck("...off screen, the last look is said as a last look",
   "this switch is off screen now; the last time it was on screen its way was OPEN, on this visit" in t4
   and "what it is now is not known from here" in t4)
ex5 = C.make(); ex5.switch_seen = {"VICTORY_ROAD_3F|3,5": {"open_at": 1, "shut": False}}
ex5._map_trail = [[1, "VICTORY_ROAD_3F"], [2, "VICTORY_ROAD_2F"], [3, "VICTORY_ROAD_3F"]]
ck("...with the maps entered since when there are any",
   "its way was OPEN, and you have entered VICTORY_ROAD_2F since" in page(ex5, None))
ex6 = C.make(); ex6.switch_seen = {"VICTORY_ROAD_3F|3,5": {"open_at": None, "shut": True}}; ex6._map_trail = []
ck("...and a way last seen shut is said shut", "its way was SHUT — what it is now" in page(ex6, None))
ex7 = C.make(); ex7.switch_seen = {}; ex7._map_trail = []
ck("never seen, nothing is claimed", "off screen now" not in page(ex7, None))
ex2 = C.make(); ex2.switch_seen = {}; ex2._map_trail = list(b._map_trail)
ck("shut with no record of it ever open says nothing about the past",
   "IT WAS OPEN THE LAST TIME" not in page(ex2, False) and "SHUT right now" in page(ex2, False))
ex3 = C.make(); ex3.switch_seen = {"VICTORY_ROAD_3F|3,5": {"open_at": 1, "shut": True}}
ex3._map_trail = [[30, "ROUTE_23"], [31, "VICTORY_ROAD_3F"]]
t3 = page(ex3, False)
ck("a trail trimmed past the record says so with an ellipsis",
   "Since then you have entered: …, ROUTE_23." in t3)

# --- wired into the round, after the page is built ----------------------
src = (ROOT / "planner/executor.py").read_text()
ck("the trail is fed at the round start and at every op",
   "start = self.settle()\n            self._note_map(start)" in src
   and "self._note_map(obs)\n            before = self._snapshot(obs)" in src)
_i = src.index("self._note_switches(start)")
ck("the switches are recorded AFTER the round's page is composed and before it is logged",
   src.index("memory += self._bag_pressure_line(start)") < _i
   and src.find('self.log("escalate_context"', _i) > 0
   and src.find('self.log("escalate_context"', _i) - _i < 6000)
ck("both survive a relaunch", '"switch_seen": getattr(self, "switch_seen", {})' in src
   and 'self.switch_seen = data.get("switch_seen", {}) or {}' in src
   and '"map_trail": list(getattr(self, "_map_trail", []) or [])[-40:]' in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
