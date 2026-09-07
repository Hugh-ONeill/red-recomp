"""A done verdict that reasons from one fact to another is not a verdict.

Run 16 (2026-09-07): check-done crossed "Chase the Team Rocket thief out of
the burgled house in Cerulean City" off the list with the reason "the
player has already helped Bill, and the event record indicates they have
left Bill's house, implying the thief sequence in Cerulean is complete".
No EVENT_BEAT_CERULEAN_ROCKET_THIEF had fired, no TM28 was in the bag, the
house had never been entered.  The prompts already ask for something you can
point at; the model's own hedging words -- implying, suggests, likely,
presumably, must have -- are the tell that it is pointing at nothing.

Refusing a hedged claim decides nothing: the leg simply runs.  A reason
that names the fact is never refused.
"""
import json
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import author as A

ck("the run's own false reason is read as an inference",
   A._inferred("The player has already helped Bill, and the event record indicates they "
               "have left Bill's house, implying the thief sequence in Cerulean is complete."))
for w in ("This suggests the badge was earned.", "The thief was likely chased out.",
          "They must have cleared the house.", "Presumably the parcel was delivered."):
    ck(f"hedged: {w[:40]}", A._inferred(w))
for w in ("EVENT_BEAT_MISTY has fired and CASCADEBADGE is worn.",
          "The S.S. Ticket is in the bag.", "The run has stood in Cerulean City."):
    ck(f"pointed: {w[:40]}", not A._inferred(w))

_real = A.brock_probe.chat
def fake(why, done=True):
    return lambda msgs, model: json.dumps({"why": why, "done": done})
try:
    A.brock_probe.chat = fake("The player helped Bill and left the house, implying the thief sequence is complete.")
    ck("already-done refuses the inferred verdict",
       A.check_already_done("Chase the Team Rocket thief out of the burgled house", "standing in CERULEAN_GYM", "m") is False)
    A.brock_probe.chat = fake("EVENT_BEAT_MISTY has fired and the CASCADEBADGE is worn.")
    ck("...and accepts one that points at the deed",
       A.check_already_done("Defeat the gym leader of the second gym", "standing in CERULEAN_GYM with CASCADEBADGE", "m") is True)
    A.brock_probe.chat = fake("Helping Bill suggests the rest was done too.", done=[1, 2])
    ck("a sweep whose one reason hedges names nothing",
       A.sweep_already_done([(1, "Chase the thief"), (2, "Reach Vermilion City")], "standing in CERULEAN_CITY", "m") == [])
finally:
    A.brock_probe.chat = _real

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
