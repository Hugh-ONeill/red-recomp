"""A healing rule that names an item you do not carry never fires.

The battle policy heals with a NAMED item. This run's was authored in a
`partyauthor` evaluation — Pewter and the early rival — where POTION is what
a party holds, and it was never revisited (user, 2026-08-24: "yeah we never
did make that policy v2"). By the Elite Four the rule read `POTION below 30%
HP` against a bag of HYPER_POTION, MAX_POTION and three MAX_REVIVEs, and
`battle_item` had fired ONCE in 6041 battle turns. The party walked into a
gauntlet with no Pokemon Center in it, unable to use its own medicine,
blacked out and paid the toll repeatedly ("its gone through a few times and
lost 90% of its money").

The policy is the model's own file. The harness says only that the rule
cannot fire, and what IS carried.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "planner"))
import executor as E

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


class S:
    pass


def line(spec, bag):
    E.set_active_spec(spec)
    return E.Executor._policy_heal_line(S(), {"bag": bag}).strip()


POTION_RULE = {"battle_items": [{"item": "POTION", "hp_below": 0.3}]}
HELD = {"HYPER_POTION": 2, "MAX_POTION": 1, "MAX_REVIVE": 3, "FULL_HEAL": 1}

l = line(POTION_RULE, HELD)
ck("it says the rule cannot fire", "CANNOT HEAL YOU RIGHT NOW" in l)
ck("...naming the item the rule wants", "POTION in a fight" in l)
ck("...and what is actually carried", "HYPER_POTION" in l and "MAX_REVIVE" in l)
ck("...and that the policy is the model's to change",
   "your own battle policy" in l)
ck("it does not name a substitute to use",
   "use " not in l.lower() and "instead" not in l.lower())

ck("silent when the named item is held",
   line(POTION_RULE, dict(HELD, POTION=3)) == "")
ck("silent when the policy names no items", line({"battle_items": []}, HELD) == "")
ck("silent when one of several rules can still fire",
   line({"battle_items": [{"item": "POTION"}, {"item": "MAX_POTION"}]},
        HELD) == "")
ck("says so plainly when nothing at all is carried",
   "no healing items at all" in line(POTION_RULE, {"BICYCLE": 1}))

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
