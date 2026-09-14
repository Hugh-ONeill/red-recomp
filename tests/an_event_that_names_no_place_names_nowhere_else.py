#!/usr/bin/env python3
"""check-done's place guard speaks only when every event on offer names a
place, and none of them names this one.

The guard exists for the Snorlax case: "Wake the Snorlax sleeping on ROUTE
12" was judged done on EVENT_BEAT_ROUTE16_SNORLAX, the other Snorlax, a
map away. But it also refused the completed trade leg: "this objective
names VERMILION_CITY and the events it could rest on name somewhere else
(EVENT_LEFT_BILLS_HOUSE_AFTER_HELPING, EVENT_TRADED_SPEAROW_FOR_
FARFETCHD)" -- the deed's own event, which carries no town and no route,
read as evidence of elsewhere (2026-09-14). DUX was in the party; the leg
went down the ladder and was crossed off a rung later, and the outline
came out with the CUT leg ahead of the HM01 leg.

An event that names no place names nowhere else. Towns are the first word
of their events (CINNABAR, VERMILION), routes are ROUTE16 or ROUTE_16;
a person, a thing or a deed in a name places it nowhere.
"""
from __future__ import annotations
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import author as A                                       # noqa: E402
import brock_probe                                       # noqa: E402
from pinned_world import pinned                          # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

brock_probe.chat = lambda msgs, model, **kw: '{"why": "DUX the FARFETCHD is in the party", "done": true}'
START = ("standing in VERMILION_TRADE_HOUSE with PIKACHU L20, CHARMELEON L29, "
         "NIDORINO L19, FARFETCHD L10 (party at full HP), 2 badges, 6000 money")

def judge(goal, flags, start=START):
    out = io.StringIO()
    with pinned(obs={"flags": flags, "map": {"id": "VERMILION_TRADE_HOUSE"}}), redirect_stdout(out):
        ok = A.check_done(goal, start, "m", observed=None, gained="")
    return ok, out.getvalue()

# ---- what an event names -----------------------------------------------------
ck("a town's first word places an event", A._event_names_a_place("EVENT_BEAT_CINNABAR_GYM_TRAINER_0"))
ck("...and so does a route, either spelling",
   A._event_names_a_place("EVENT_BEAT_ROUTE16_SNORLAX") and A._event_names_a_place("EVENT_BEAT_ROUTE_4_TRAINER_0"))
ck("a deed, a person, a thing: nowhere",
   not A._event_names_a_place("EVENT_TRADED_SPEAROW_FOR_FARFETCHD")
   and not A._event_names_a_place("EVENT_LEFT_BILLS_HOUSE_AFTER_HELPING")
   and not A._event_names_a_place("EVENT_GOT_HM01"))

# ---- the trade leg -------------------------------------------------------------
ok, said = judge("Trade a SPEAROW for the FARFETCHD at the Vermilion City trade house",
                 ["EVENT_TRADED_SPEAROW_FOR_FARFETCHD", "EVENT_LEFT_BILLS_HOUSE_AFTER_HELPING"])
ck("a deed whose event names no place is the model's to judge", ok is True, said)
ck("...and the guard said nothing", "somewhere else" not in said, said)

# ---- the Snorlax case still refuses --------------------------------------------
ok, said = judge("Wake the Snorlax sleeping on Route 12", ["EVENT_BEAT_ROUTE16_SNORLAX"],
                 start="standing on ROUTE_12 with SNORLAX L30 asleep ahead, 6 badges")
ck("every event on offer naming a DIFFERENT place is still refused",
   ok is False and "somewhere else" in said and "ROUTE_12" in said, said)

# ---- mixed: one placed elsewhere, one placeless: the record cannot say -----------
ok, said = judge("Wake the Snorlax sleeping on Route 12",
                 ["EVENT_BEAT_ROUTE16_SNORLAX", "EVENT_FOUND_POKE_FLUTE_SNORLAX"],
                 start="standing on ROUTE_12 with SNORLAX gone, 6 badges")
ck("with a placeless event among them, the guard steps aside", "somewhere else" not in said, said)

# ---- the right place still passes ---------------------------------------------
ok, said = judge("Defeat Blaine on Cinnabar Island", ["EVENT_BEAT_CINNABAR_GYM_TRAINER_0", "EVENT_BEAT_BLAINE"],
                 start="standing in CINNABAR_GYM, 7 badges")
ck("an event naming this very place passes as before", "somewhere else" not in said, said)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300].replace("\n", " | "))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
