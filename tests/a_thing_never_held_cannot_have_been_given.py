#!/usr/bin/env python3
"""An objective that says a key item was given away is not already done
when the run has never once held it.

_item_not_held stands aside when the objective says GIVE or DELIVER,
because the thing being gone from the bag is what success looks like.
That left "Deliver the OAKS_PARCEL to Professor Oak" wholly to the
model, which said DONE with the parcel never collected -- "the player has
already battled the rival in Oak's lab, which occurs after the parcel has
been delivered" (it does not). The leg was crossed off and the chain
walked on to "Obtain POKE BALLS from Professor Oak", which cannot happen
without it, and stopped there (2026-09-14; user: "it went up to v7
without seeing the mart, somethings definitely wrong with the harness
still").

The record could have said no: the engine sets EVENT_GOT_OAKS_PARCEL the
moment the clerk hands it over, and it had not fired. So: a key item the
objective says was given away, not in the bag, with an engine flag that
names it and none of those flags fired, was never held -- refused before
the model is asked. Key items only (a POKE_BALL can be bought); where the
engine names no flag for the item, the record is silent and the judgment
stays the model's.
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

# the model, if it is reached, says DONE in plain words
brock_probe.chat = lambda msgs, model, **kw: (
    '{"why": "the parcel is no longer in the bag", "done": true}')

START = ("standing in VIRIDIAN_CITY with CHARMANDER L7 (FIRE) 23/23hp "
         "knowing SCRATCH/GROWL, no badges, 3175 money, and TOWN_MAP x1")
EARLY = ["EVENT_GOT_STARTER", "EVENT_BATTLED_RIVAL_IN_OAKS_LAB",
         "EVENT_GOT_TOWN_MAP"]                    # the run as it stood

def judge(goal, start=START, flags=EARLY, obs=True):
    out = io.StringIO()
    kw = {"obs": {"flags": flags, "map": {"id": "VIRIDIAN_CITY"}}} if obs else {}
    with pinned(**kw), redirect_stdout(out):
        ok = A.check_done(goal, start, "m", observed=None, gained="")
    return ok, out.getvalue()

# ---- the table the rule reads --------------------------------------------
ck("the engine's key items are known", "OAKS_PARCEL" in A.ENGINE_KEY_ITEMS
   and "POKE_FLUTE" in A.ENGINE_KEY_ITEMS and "GOLD_TEETH" in A.ENGINE_KEY_ITEMS)
ck("...and a thing you can buy is not one of them",
   "POKE_BALL" not in A.ENGINE_KEY_ITEMS and "POTION" not in A.ENGINE_KEY_ITEMS)
ck("...nor a badge, nor the safari's thirty balls, nor the ROM's unused slot",
   not any(k.endswith("BADGE") for k in A.ENGINE_KEY_ITEMS)
   and "SAFARI_BALL" not in A.ENGINE_KEY_ITEMS
   and "ITEM_2C" not in A.ENGINE_KEY_ITEMS, sorted(A.ENGINE_KEY_ITEMS))

# ---- the leg that was crossed off ----------------------------------------
ok, said = judge("Deliver the OAKS_PARCEL to Professor Oak")
ck("delivering a parcel the run never held is refused", ok is False)
ck("...naming the item and the reason",
   "OAKS_PARCEL" in said and "never once held" in said, said)
ck("...before the model is asked", "no longer in the bag" not in said)

ok, said = judge("Collect the OAKS_PARCEL from the clerk at the Viridian "
                 "City Poke Mart and deliver it to Professor Oak")
ck("the fused collect-and-deliver leg is refused the same way",
   ok is False and "never once held" in said, said)

# ---- and the record that would let it through ----------------------------
ok, said = judge("Deliver the OAKS_PARCEL to Professor Oak",
                 flags=EARLY + ["EVENT_GOT_OAKS_PARCEL"])
ck("once the engine says the parcel was handed over, the model judges",
   ok is True and "never once held" not in said, said)
ok, said = judge("Deliver the OAKS_PARCEL to Professor Oak",
                 flags=EARLY + ["EVENT_GOT_OAKS_PARCEL", "EVENT_OAK_GOT_PARCEL"])
ck("...and so with the delivery itself on record", ok is True)
ok, said = judge("Deliver the OAKS_PARCEL to Professor Oak",
                 start=START + ", and OAKS_PARCEL x1")
ck("a parcel still in the bag is the model's to weigh, as before", ok is True)

# ---- what the rule does not touch ----------------------------------------
ok, said = judge("Give a FRESH WATER from the Celadon Department Store "
                 "roof to the thirsty guard at a Saffron City gate")
ck("a bought thing given away is the model's call: no flag names it",
   ok is True and "never once held" not in said, said)
ok, said = judge("Use a POKE BALL to catch a PIDGEY on Route 1")
ck("...and so is a consumable", ok is True and "never once held" not in said)
ok, said = judge("Retrieve the OAKS_PARCEL from the clerk at the Poke Mart")
ck("a fetch that is not a giving keeps the bag rule it always had",
   ok is False and "not in the bag" in said, said)
ok, said = judge("Deliver the OAKS_PARCEL to Professor Oak", obs=False)
ck("no observation on disk: the record is silent and the model judges",
   ok is True and "never once held" not in said, said)

ok, said = judge("Give the GOLD TEETH to the Safari Zone Warden",
                 flags=EARLY + ["EVENT_GAVE_GOLD_TEETH"])
ck("a flag that IS the giving counts as having held it", ok is True, said)
ok, said = judge("Give the GOLD TEETH to the Safari Zone Warden")
ck("...and without it the teeth were never held", ok is False, said)

# ---- the whole-run judge asks the same question --------------------------
def judge_run(goal, flags=EARLY):
    err = io.StringIO()
    with pinned(obs={"flags": flags, "map": {"id": "VIRIDIAN_CITY"}}):
        import contextlib
        with contextlib.redirect_stderr(err):
            ok = A.check_already_done(goal, START, "m", observed=None)
    return ok, err.getvalue()

ok, said = judge_run("Deliver the OAKS_PARCEL to Professor Oak")
ck("check_already_done refuses it too", ok is False and "never once held" in said, said)
ok, said = judge_run("Deliver the OAKS_PARCEL to Professor Oak",
                     flags=EARLY + ["EVENT_GOT_OAKS_PARCEL"])
ck("...and steps aside once the parcel was held", "never once held" not in said, said)

# ---- source: it sits in the family, after the bag rule -------------------
src = (ROOT / "planner" / "author.py").read_text()
i_bag = src.index("item = _item_not_held(goal, start)")
i_new = src.index("gone = _never_held(goal, start)")
i_ask = src.index('{"role": "system", "content": CHECKDONE_SYS}')
ck("check_done asks it after the bag rule and before the model",
   i_bag < i_new < i_ask)
ck("both rules read one list of the deeds that end with the thing gone",
   src.count("re.search(GIVE_VERBS, goal, re.I)") == 2)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300].replace("\n", " | "))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
