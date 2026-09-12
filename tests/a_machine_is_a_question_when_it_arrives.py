#!/usr/bin/env python3
"""A machine that arrives is ASKED about, not mentioned.

Run 16, off its own journal: the TM arrival note fired 110 times. The round
that followed named the TM in its prose 14 times and taught one SIX times —
and five of the run's twelve teaches came from legs written by hand for the
purpose. A MOON_STONE and TM_THUNDER_WAVE rode to the Hall of Fame.

That is not a model ignoring a fact. Teaching never advances the subgoal
under escalation, so a correct round-by-round choice declines it 104 times
out of 110: we had made improvement compete with progress for the same
round. The precedent for the fix is already here — _maybe_forget asks a
short question with a small answer space at the moment the game raises it,
costs no round, and answered well.

And the note's own words were false by the time they were read. It said
compatibility "is not something this harness knows" while obs.machines
carried the ABLE list off the very screen a machine opens, and the TOSS
guard printed that list at the moment of DESTRUCTION. The facts were
withheld where they would have helped and shown where they could not.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                       # noqa: E402
import brock_probe as B                                    # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

FOUR = ["FLAMETHROWER", "SLASH", "EARTHQUAKE", "FLY"]


def obs(bag=None, machines=None, party=None):
    return {"mode": "overworld", "player": {"x": 1, "y": 1},
            "bag": dict(bag if bag is not None else {"TM_BLIZZARD": 1}),
            "machines": dict(machines if machines is not None else {
                "TM_BLIZZARD": {"move": "BLIZZARD",
                                "able": ["VAPOREON", "NIDOQUEEN"],
                                "not_able": ["CHARIZARD"]}}),
            "party": party if party is not None else [
                {"species": "CHARIZARD", "level": 61,
                 "moves": [{"id": m} for m in FOUR]},
                {"species": "VAPOREON", "level": 53,
                 "moves": [{"id": "SURF"}, {"id": "BITE"}]},
                {"species": "NIDOQUEEN", "level": 50,
                 "moves": [{"id": m} for m in
                           ["BODY_SLAM", "THRASH", "DOUBLE_KICK", "TACKLE"]]}],
            "map": {"id": "SEAFOAM_ISLANDS_B3F", "region": "1,1",
                    "objects": []}}


def fresh(reply):
    ex = E.Executor.__new__(E.Executor)
    ex._tm_asked = {}
    ex.model = "stub"
    ex.sent = []
    ex.asked = []
    ex.log = lambda *a, **k: None
    ex._item_from = {}
    ex.settle = lambda: None
    ex._send_safe = lambda op, **kw: (
        ex.sent.append((op, kw)) or {"result": {"ok": True, "detail": "ok"}})
    B.chat = lambda msgs, model, **k: (
        ex.asked.append(msgs[-1]["content"]) or reply)
    return ex


SG = {"id": "cross_seafoam", "goal_text": "Cross the Seafoam Islands"}

# ---- what counts as teachable ------------------------------------------
ex = fresh('{"why":"no","teach":null}')
t = ex._teachable_now(obs())
ck("a machine nobody knows, with somebody ABLE, is a question",
   len(t) == 1 and t[0][0] == "TM_BLIZZARD" and t[0][1] == "BLIZZARD")
ck("...and it carries the slots the GAME marks able, with their moves",
   [(i, sp) for i, sp, _ in t[0][2]] == [(2, "VAPOREON"), (3, "NIDOQUEEN")])
ck("a machine somebody already knows is not asked about",
   ex._teachable_now(obs(machines={"TM_FLY": {"move": "FLY",
                                              "able": ["CHARIZARD"],
                                              "not_able": []}},
                         bag={"TM_FLY": 1})) == [])
ck("a machine NOBODY is able to learn is not asked about",
   ex._teachable_now(obs(machines={"TM_X": {"move": "SELFDESTRUCT",
                                            "able": [],
                                            "not_able": ["CHARIZARD"]}},
                         bag={"TM_X": 1})) == [])
ck("a plain item is not a machine", ex._teachable_now(
    obs(bag={"POTION": 3}, machines={})) == [])

# ---- the question, and what it is given --------------------------------
ex = fresh('{"why":"Vaporeon has a free slot and no Ice move","teach":2}')
ex._ask_teach(obs(), SG)
q = ex.asked[0]
ck("the question names the machine and its move",
   "TM14 (TM_BLIZZARD)" in q and "BLIZZARD" in q)
ck("...and that a TM is used up", "USED UP THE MOMENT IT WORKS" in q)
ck("...and lists only the ABLE, with their levels and current moves",
   "slot 2: VAPOREON L53" in q and "SURF, BITE" in q
   and "slot 3: NIDOQUEEN L50" in q and "CHARIZARD" not in q)
ck("...marking who is already full", "FOUR moves: one must go" in q)
ck("...and says what the run is trying to do",
   "Cross the Seafoam Islands" in q)
ck("...and that no round rides on the answer", "No round is spent" in q)
ck("the answer is carried out as the teach op",
   ex.sent == [("use_item", {"item": "TM_BLIZZARD", "slot": 2})])

# ---- no is a real answer ------------------------------------------------
ex = fresh('{"why":"every able one would lose a better move","teach":null}')
ex._ask_teach(obs(), SG)
ck("a no teaches nothing", ex.sent == [])
ck("...and is remembered so it is not asked again", ex._tm_asked)
ex._ask_teach(obs(), SG)
ck("...and asking twice for the same party does not happen",
   len(ex.asked) == 1)

# ---- a changed party reopens it ----------------------------------------
p2 = obs()["party"] + [{"species": "LAPRAS", "level": 40, "moves": []}]
m2 = {"TM_BLIZZARD": {"move": "BLIZZARD",
                      "able": ["VAPOREON", "NIDOQUEEN", "LAPRAS"],
                      "not_able": ["CHARIZARD"]}}
ex._ask_teach(obs(party=p2, machines=m2), SG)
ck("a party that changed is a new question", len(ex.asked) == 2)

# ---- an answer is checked against the same screen it came from ---------
for reply, why in [
        ('{"why":"x","teach":1}', "a slot the game marks NOT ABLE"),
        ('{"why":"x","teach":3}', "a full party member with no forget"),
        ('{"why":"x","teach":3,"forget":"PSYCHIC"}', "a move it does not know"),
        ('{"why":"x","teach":9}', "a slot that is not in the party")]:
    ex = fresh(reply)
    ex._ask_teach(obs(), SG)
    ck(f"refused before it is sent: {why}", ex.sent == [])

ex = fresh('{"why":"x","teach":3,"forget":"TACKLE"}')
ex._ask_teach(obs(), SG)
ck("a sound forget goes through, named",
   ex.sent == [("use_item", {"item": "TM_BLIZZARD", "slot": 3,
                             "forget": "TACKLE"})])

# an HM move can never be the one dropped
hm = obs()
hm["party"][1]["moves"] = [{"id": m} for m in
                           ["SURF", "BITE", "ICE_BEAM", "WATER_GUN"]]
ex = fresh('{"why":"x","teach":2,"forget":"SURF"}')
ex._ask_teach(hm, SG)
ck("an HM move is never the move dropped", ex.sent == [])

# a reply that is not JSON at all closes the question rather than looping
ex = fresh("I think you should probably teach it to Vaporeon.")
ex._ask_teach(obs(), SG)
ck("an unusable reply teaches nothing", ex.sent == [])
ex._ask_teach(obs(), SG)
ck("...and is not re-asked every round for ever", len(ex.asked) == 1)

# ---- the page and the wiring -------------------------------------------
SRC = (ROOT / "planner" / "executor.py").read_text()
ck("the false compatibility line is gone",
   "can learn a given TM is not something this harness knows" not in SRC)
ck("the page's standing list names who the game marks ABLE",
   "MACHINES YOU CARRY THAT NOBODY IN YOUR PARTY KNOWS" in SRC
   and "ABLE / NOT ABLE is the machine's own party screen" in SRC)
_flat = " ".join(SRC.split())
ck("...and says a taught-over move is gone",
   "THAT MOVE IS THEN \" \"GONE. A TM is spent when it works; an HM never is."
   in _flat)
ck("...and that nobody able today may be able after an evolution",
   "what a species can learn CHANGES WHEN IT \" \"EVOLVES, and a different "
   "party member could" in _flat)
ck("...and that each becomes a question once, and can be acted on any time",
   "asked about each of these once when it \" \"becomes teachable" in _flat)
ck("the question runs at the round boundary, not in the round",
   "start = self._ask_teach(start, sg) or start" in SRC)
ck("what was asked survives the process that asked it",
   '"tm_asked": getattr(self, "_tm_asked", {})' in SRC
   and 'self._tm_asked = data.get("tm_asked") or {}' in SRC)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
