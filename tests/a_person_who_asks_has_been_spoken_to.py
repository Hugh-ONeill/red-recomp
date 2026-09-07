"""A person who asks you something has been spoken to; an item that asks
"You want it?" and is declined is still lying there.

The fossil rule (a press that opened a question and got no answer is not a
press) was written for items.  Applied to people, it made Pewter's museum
guide -- "Did you check out the MUSEUM?" -- a man never spoken to: the
sweep pressed him blind every round and could only decline, left him "NOT
recorded as done", and the next round's explore pressed him first again.
Twenty-one presses across two attempts of run 16, in the town the party
needed to leave (2026-09-07; user: "it just explored where it could and
talked to the museum nerd a bunch of times").

His question IS his answer.  The kind is read off the map's own object
list; an unknown kind keeps the item rule.
"""
import sys
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E

ASK = ("PEWTERCITY_SUPER_NERD1 is ASKING something and the box is STILL OPEN — "
       "\"Did you check out the MUSEUM?\". No answer was supplied with the interact.")
OBJS = [{"name": "PEWTERCITY_SUPER_NERD1", "kind": "npc", "x": 4, "y": 6},
        {"name": "ITEM_MT_MOON_B2F_5_7", "kind": "item", "x": 5, "y": 7},
        {"name": "MTMOON_COOLTRAINER_M1", "kind": "trainer", "x": 1, "y": 1}]
def obs_with(detail):
    return {"mode": "dialog", "map": {"id": "PEWTER_CITY", "region": "4,2", "objects": OBJS},
            "result": {"ok": True, "detail": detail}}

ck("a person who asked counts as talk", E.Executor._asks_as_talk(obs_with(ASK), "PEWTERCITY_SUPER_NERD1"))
ck("a trainer who asked counts as talk", E.Executor._asks_as_talk(obs_with(ASK), "MTMOON_COOLTRAINER_M1"))
ck("an item that asked does not", not E.Executor._asks_as_talk(obs_with(ASK), "ITEM_MT_MOON_B2F_5_7"))
ck("a name the map does not list keeps the item rule", not E.Executor._asks_as_talk(obs_with(ASK), "NOBODY"))

def bare():
    ex = E.Executor.__new__(E.Executor)
    for a in ("_tried_objs", "_touch_mark", "_touch_bag", "_outcomes", "machines",
              "_machine_stock", "searched", "hints", "hints_at", "region_mark",
              "touched", "explored", "visits", "frontier", "_last_key_items",
              "item_from", "offered", "_seen_asks"):
        setattr(ex, a, {})
    ex._last_key_items = []
    ex._cur_target = "badge:BOULDERBADGE"
    ex._where = lambda o: "PEWTER_CITY|4,2"
    ex._world_mark = lambda o: [0, 0, 0]
    ex.logf = None
    ex.log = lambda *a, **k: None
    return ex

ex = bare()
try:
    got = ex._record_touch("PEWTER_CITY|4,2", "PEWTERCITY_SUPER_NERD1", obs_with(ASK))
    ck("the guide's press is recorded as a touch", got is True
       and "PEWTERCITY_SUPER_NERD1" in ex._tried_objs.get("PEWTER_CITY|4,2", set()))
except Exception as e:                                    # pragma: no cover
    ck(f"the guide's press is recorded as a touch ({type(e).__name__}: {e})", False)
ex = bare()
try:
    got = ex._record_touch("PEWTER_CITY|4,2", "ITEM_MT_MOON_B2F_5_7",
                           obs_with("ITEM_MT_MOON_B2F_5_7 is ASKING something and the box is STILL OPEN — \"You want the DOME FOSSIL?\""))
    ck("a declined take-prompt is still not a touch", got is False
       and "ITEM_MT_MOON_B2F_5_7" not in ex._tried_objs.get("PEWTER_CITY|4,2", set()))
except Exception as e:                                    # pragma: no cover
    ck(f"a declined take-prompt is still not a touch ({type(e).__name__}: {e})", False)

src = Path("planner/executor.py").read_text()
ck("the post-op retraction keeps the same exception",
   "and not self._asks_as_talk(obs, step[\"name\"]," in src)   # ...now with the remembered kinds as a third argument
ck("the sweep says a person it declined for counts as spoken to, and how to say yes",
   src.count("asked_people") >= 4 and "the sweep declined for you" in src
   and 'self._record_outcome(cur, "interact",' in src)

# ...EVEN WHEN THE BOX HE OPENED HID THE MAP. The observation taken while a
# yes/no box is open carries no map, so the kinds remembered per map answer
# (Game Corner coin clerk, run 16, 2026-09-07: two presses, still "never
# spoken to", explore pressed him first again).
ck("with no map in the observation, the remembered kinds say he is a person",
   E.Executor._asks_as_talk({}, "GAMECORNER_CLERK1", {"GAMECORNER_CLERK1": "npc"})
   and not E.Executor._asks_as_talk({}, "ITEM_BALL_3", {"ITEM_BALL_3": "item"})
   and not E.Executor._asks_as_talk({}, "UNKNOWN_THING", {"GAMECORNER_CLERK1": "npc"}))
_src = open("planner/executor.py").read()
ck("kinds are remembered per map as observations arrive", '_kinds[str(_o["name"])] = str(_o["kind"])' in _src)
ck("...and both asks-as-talk call sites consult them",
   "self._asks_as_talk(res_obs, name, self._kinds_for(region))" in _src
   and "self._kinds_for(self._where(pre_obs))" in _src)
ck("the walk fallback says what it rides: a way in used before, door or pad",
   _src.count("door or a pad) was used again") == 3)   # comments may quote the old phrase as history

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
