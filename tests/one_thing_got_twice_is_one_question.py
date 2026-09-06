"""Two legs that both GET one thing, named two ways, are one question for
the model -- and the era conversation is the first draft.

Both outlines drawn on 2026-09-06 carried "Retrieve the Pokemon Flute from
Mr. Fuji" AND "Obtain the Snorlax-blocking Poke Flute"; run 15 played the
second as a leg of its own.  The dedupe needs two names in common, for a
reason it documents: "Defeat Giovanni" and "Defeat Giovanni for the Earth
Badge" are two fights sharing one name, and must both survive.  A thing the
game hands over once, written two ways, shares one name too -- so the
harness cannot tell the pairs apart, and does not try.  It lists the pairs
of ACQUISITION legs sharing exactly one name and asks the model, which
wrote both, to say which pairs are one thing.  The later wording of a
"same" pair is dropped and kept as a note, the dedupe's own rule; a pair
the model calls two things is not touched.

And the parcel: the constrained draws never named Oak's parcel (0-for-2 on
2026-09-06, 1-for-9 in August), while the loose three-era conversation the
user designed produced it by hand.  That conversation is now the first
draft the merge chooses from.  Nothing is decided here: the menu is wider.
"""
import sys
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import author as A

LEGS = [
    "Obtain a starter Pokemon",
    "Defeat Giovanni in the Rocket Hideout",
    "Retrieve the Pokemon Flute from Mr. Fuji",
    "Retrieve the HM01 from the S.S. Anne",
    "Defeat Giovanni for the Earth Badge",
    "Obtain the Snorlax-blocking Poke Flute",
    "Wake Snorlax to clear the path",
    "Obtain the S.S. Ticket from Bill",
]

pairs = A._twin_pairs(LEGS)
names = {(LEGS[i], LEGS[j]) for i, j, _ in pairs}
ck("the two flute legs are a pair",
   ("Retrieve the Pokemon Flute from Mr. Fuji",
    "Obtain the Snorlax-blocking Poke Flute") in names)
ck("Giovanni's two fights are not — they are not acquisitions",
   not any("Giovanni" in a and "Giovanni" in b for a, b in names))
ck("a leg that USES the flute is not paired with one that gets it",
   not any("Wake Snorlax" in a or "Wake Snorlax" in b for a, b in names))
# the S.S. Anne's HM and the S.S. Ticket share the one name "ss": they ARE
# a pair, and the model's answer ("two things") is what settles it — the
# harness proposes, and never rules a pair out on its own
ck("two acquisitions sharing one name are proposed, whatever they are",
   ("Retrieve the HM01 from the S.S. Anne",
    "Obtain the S.S. Ticket from Bill") in names)
ck("two acquisitions sharing nothing are not a pair",
   not any(a == "Obtain a starter Pokemon" or b == "Obtain a starter Pokemon"
           for a, b in names))

# the model says "same": the later wording goes, and is kept as a note
A.OUTLINE_NOTES.clear()
flute = next(n for n, (i, j, _) in enumerate(pairs)
             if LEGS[j] == "Obtain the Snorlax-blocking Poke Flute")
out = A._apply_twins(LEGS, pairs, [flute])
ck("the later flute leg is dropped",
   "Obtain the Snorlax-blocking Poke Flute" not in out)
ck("the first flute leg stays", "Retrieve the Pokemon Flute from Mr. Fuji" in out)
ck("everything else stays", len(out) == len(LEGS) - 1)
ck("what the loser said is kept as a note in the dedupe's own words",
   any(kept == "Retrieve the Pokemon Flute from Mr. Fuji"
       and "also written as 'Obtain the Snorlax-blocking Poke Flute'" in note
       for kept, note in A.OUTLINE_NOTES))

# the model says "two things": nothing moves
ck("a pair the model calls two things is untouched",
   A._apply_twins(LEGS, pairs, []) == LEGS)

# the question itself, with the model's reply faked
asked = {}
def fake_chat(msgs, model):
    asked["sys"] = msgs[0]["content"]; asked["user"] = msgs[1]["content"]
    return '["A"]'
_real = A.brock_probe.chat
A.brock_probe.chat = fake_chat
try:
    A.OUTLINE_NOTES.clear()
    got = A._twin_check("Become the Champion", LEGS, "m")
finally:
    A.brock_probe.chat = _real
ck("the question lists the pair by number and the shared name",
   "share: flute" in asked.get("user", ""))
ck("the question asks for letters, choose-only",
   "letters of the pairs that are the SAME" in asked.get("sys", ""))
ck("the reply is applied verbatim",
   "Obtain the Snorlax-blocking Poke Flute" not in got
   and len(got) == len(LEGS) - 1)

# no pairs, no call
called = []
A.brock_probe.chat = lambda *a, **k: called.append(1) or "[]"
try:
    same = A._twin_check("g", ["Obtain a starter Pokemon",
                               "Defeat Brock for the Boulder Badge"], "m")
finally:
    A.brock_probe.chat = _real
ck("no pairs means no question", not called and len(same) == 2)

# the pipeline: the era conversation is the first draft, the twin question
# runs once on the final list, and the CLI can turn the eras off
src = Path("planner/author.py").read_text()
ck("the era conversation is the first draft",
   "d = outline_eras(goal, model)" in src
   and "draft 1 (three eras, asked loosely)" in src)
ck("the twin question runs on the final list before the stages are written",
   src.index("legs = _twin_check(goal, legs, model)")
   < src.index("STAGES_PATH.write_text(")
   and src.index("legs = _twin_check(goal, legs, model)")
   > src.index("_stage_missing(goal, legs, stages, model)"))
ck("--no-eras exists", '"--no-eras"' in src and "eras=not args.no_eras" in src)

# the era checklist comes back in the past tense, and a verb in any tense
# is not what an objective is about: its badge lines are eight things
ck("past-tense verbs are not names",
   A._objective_key("Defeated Misty and earned the Cascade Badge")
   == frozenset({"misty", "cascade"}))
ck("...so two badge lines in that voice are not repeats of each other",
   len(A._objective_key("Defeated Misty and earned the Cascade Badge")
       & A._objective_key("Defeated Brock and earned the Boulder Badge")) == 0)

# a different number is a different objective: the dedupe kept "at least 3
# Pokemon" and dropped "at least 4 Pokemon" as the same thing (live,
# 2026-09-06)
A.OUTLINE_NOTES.clear()
kept = A._dedupe_outline(["the party has at least 3 Pokemon",
                          "the party has at least 4 Pokemon",
                          "every party member is at least level 12",
                          "every party member is at least level 20",
                          "Obtain the S.S. Ticket",
                          "Obtain the S.S. Ticket from Bill"])
ck("legs that differ only by their number both survive",
   "the party has at least 4 Pokemon" in kept
   and "every party member is at least level 20" in kept)
ck("...and the wordless twin is still dropped", len(kept) == 5)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
