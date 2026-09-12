#!/usr/bin/env python3
"""A stone in the bag and a party member with an evolution ahead of it are
one fact, and the harness held both and joined neither.

Run 16 carried a MOON_STONE to the Hall of Fame. The harness knew the whole
time that it was carrying one, and knew from the engine's own species table
which members still had an evolution open — that judgment is what
{"party_fully_evolved"} is decided on. The two halves only ever met on a
page built for a party_fully_evolved GOAL, which that run never had (user,
2026-09-11: "similar with stones, like, if you got it and you CAN use it,
why not do so?").

WHICH stone suits WHICH species is still never said, and that is not a gap:
it is the one question the game answers for free. slot "any" tries a stone
on each member in turn and hands it back if nobody takes it, so the cost of
finding out is one op. What the harness names is what it can see — what you
hold, and who has somewhere left to go.

...AND THE JOIN ALONE WOULD NOT HAVE DONE IT. The machine note taught that
lesson at a cost of 110 firings and six teaches: a fact on a page loses to
the subgoal for the round it would cost, every time. So the stone is a
QUESTION on the same hook, asked once per (stones held, candidates), with
"spend none" a first-class answer.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                       # noqa: E402
import brock_probe as B                                    # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

M = lambda *m: [{"id": x} for x in m]
PARTY = [{"species": "CHARIZARD", "level": 36, "moves": M("SLASH")},
         {"species": "GLOOM", "level": 30, "moves": M("ABSORB", "ACID")},
         {"species": "EEVEE", "level": 25, "moves": M("TACKLE")}]
DONE = [{"species": "CHARIZARD", "level": 61, "moves": M("SLASH")},
        {"species": "VAPOREON", "level": 53, "moves": M("SURF")}]
SG = {"id": "beat_koga", "goal_text": "Defeat Koga for the Soul Badge"}


def fresh(reply=""):
    ex = E.Executor.__new__(E.Executor)
    ex._stone_asked = {}
    ex.model = "stub"
    ex.sent = []
    ex.asked = []
    ex.log = lambda *a, **k: None
    ex.settle = lambda: None
    ex._send_safe = lambda op, **kw: (
        ex.sent.append((op, kw)) or
        {"result": {"ok": True, "detail": "GLOOM EVOLVED into VILEPLUME!"}})
    B.chat = lambda msgs, model, **k: (
        ex.asked.append(msgs[-1]["content"]) or reply)
    return ex


# ---- the two halves --------------------------------------------------
ex = fresh()
st, left = ex._stone_pair({"bag": {"MOON_STONE": 1, "POTION": 3},
                           "party": PARTY})
ck("the stones come off the bag and nothing else does", st == ["MOON_STONE"])
ck("...and the candidates off the engine's species table, by slot",
   left == [(2, "GLOOM"), (3, "EEVEE")])
ck("a fully evolved party has no candidates",
   ex._stone_pair({"bag": {"MOON_STONE": 1}, "party": DONE})[1] == [])

# ---- the join --------------------------------------------------------
j = ex._stone_join({"bag": {"MOON_STONE": 1, "LEAF_STONE": 1},
                    "party": PARTY})
ck("the join names what you hold", "LEAF_STONE, MOON_STONE" in j)
ck("...and who still has somewhere to go, by slot",
   "GLOOM (slot 2)" in j and "EEVEE (slot 3)" in j)
ck("...and never which stone suits which", "VILEPLUME" not in j
   and "NIDOQUEEN" not in j and "VAPOREON" not in j)
ck("...saying where that judgment comes from",
   "engine's own species table" in j and "party_fully_evolved" in j)
ck("...and that finding the taker costs one op",
   '"slot":"any"' in j and "costs ONE op" in j
   and "hands the stone back if nobody takes it" in j)
ck("a stone with nobody to use it on says exactly that",
   "NOBODY in your party has an evolution left to them"
   in ex._stone_join({"bag": {"MOON_STONE": 1}, "party": DONE}))
ck("no stone, no paragraph",
   ex._stone_join({"bag": {"POTION": 1}, "party": PARTY}) == "")

# ---- the question ----------------------------------------------------
ex = fresh('{"why":"Vileplume is stronger for Koga","item":"LEAF_STONE",'
           '"use":"any"}')
ex._ask_stone({"bag": {"LEAF_STONE": 1, "MOON_STONE": 1},
               "party": PARTY}, SG)
q = ex.asked[0]
ck("the question names the stones and the candidates",
   "LEAF_STONE, MOON_STONE" in q and "slot 2: GLOOM L30" in q)
ck("...and says everyone else is done", "no evolution left to them" in q)
ck("...and that the taker need not be known",
   'tries each member in turn' in q)
ck("...and that it cannot be undone", "cannot be undone" in q)
ck("...and that no round rides on it", "No round is spent" in q)
ck("an answer of any is carried out as one op",
   ex.sent == [("use_item", {"item": "LEAF_STONE", "slot": "any"})])
ck("...and the game's own answer is kept",
   "EVOLVED" in (list(ex._stone_asked.values())[0].get("detail") or ""))

ex = fresh('{"why":"Flareon is wrong for a water gym","use":null}')
ex._ask_stone({"bag": {"FIRE_STONE": 1}, "party": PARTY}, SG)
ck("spending none is a real answer", ex.sent == [])
ex._ask_stone({"bag": {"FIRE_STONE": 1}, "party": PARTY}, SG)
ck("...and it is not asked again for the same party and stones",
   len(ex.asked) == 1)
ex._ask_stone({"bag": {"FIRE_STONE": 1, "MOON_STONE": 1},
               "party": PARTY}, SG)
ck("a new stone is a new question", len(ex.asked) == 2)

# nothing to ask about
ex = fresh('{"why":"x","item":"MOON_STONE","use":"any"}')
ex._ask_stone({"bag": {"MOON_STONE": 1}, "party": DONE}, SG)
ck("nobody to evolve, nothing asked", ex.asked == [] and ex.sent == [])
ex._ask_stone({"bag": {"POTION": 1}, "party": PARTY}, SG)
ck("no stone, nothing asked", ex.asked == [])

# ---- the answer is checked against bag and party, and no further -------
for reply, why in [
        ('{"why":"x","item":"SUN_STONE","use":"any"}', "a stone not carried"),
        ('{"why":"x","use":"any"}', "no stone named"),
        ('{"why":"x","item":"MOON_STONE","use":1}',
         "a slot with no evolution ahead of it")]:
    ex = fresh(reply)
    ex._ask_stone({"bag": {"MOON_STONE": 1}, "party": PARTY}, SG)
    ck(f"refused before it is sent: {why}", ex.sent == [])

ex = fresh('{"why":"x","item":"MOON_STONE","use":2}')
ex._ask_stone({"bag": {"MOON_STONE": 1}, "party": PARTY}, SG)
ck("a named slot with an evolution ahead goes through",
   ex.sent == [("use_item", {"item": "MOON_STONE", "slot": 2})])

# THE HARNESS NEVER RULES ON WHICH STONE SUITS WHICH SPECIES: a MOON_STONE
# aimed at a GLOOM is a wrong guess the GAME answers, not one we refuse.
ex = fresh('{"why":"x","item":"MOON_STONE","use":"any"}')
ex._ask_stone({"bag": {"MOON_STONE": 1}, "party": PARTY}, SG)
ck("a stone that suits nobody is still tried, not pre-judged",
   ex.sent == [("use_item", {"item": "MOON_STONE", "slot": "any"})])

ex = fresh("not json at all")
ex._ask_stone({"bag": {"MOON_STONE": 1}, "party": PARTY}, SG)
ck("an unusable reply spends nothing", ex.sent == [])
ex._ask_stone({"bag": {"MOON_STONE": 1}, "party": PARTY}, SG)
ck("...and does not re-ask for ever", len(ex.asked) == 1)

# ---- the wiring ------------------------------------------------------
SRC = (ROOT / "planner" / "executor.py").read_text()
ck("the join rides the bag on every page, not a party_fully_evolved goal",
   "_rs_line = self._stone_join(obs) + _rs_line" in SRC)
ck("the question runs at the round boundary",
   "start = self._ask_stone(start, sg) or start" in SRC)
ck("what was asked survives the process that asked it",
   '"stone_asked": getattr(self, "_stone_asked", {})' in SRC
   and 'self._stone_asked = data.get("stone_asked") or {}' in SRC)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
