#!/usr/bin/env python3
"""A level-up learn prompt is walked from its first page to the model's
answer, with the facts the summary screen shows, and nothing presses a
button on it blind.

Run 17 (2026-09-14): ZAPPER (PIKACHU) reached 26 and the game offered
SWIFT; a text-rider pressed A through "Delete an older move to make room
for SWIFT?" (YES) and once more on the list with the cursor on slot 1,
and THUNDERBOLT was gone with no record and nobody asked. DUX lost PECK
and then FURY ATTACK the same way. Every rider had been told to stop at
the list; the prompt's three pages of text come first, and by the time
anything looked for the list the YES had already been pressed.

Same cure as the naming grid: while a learn is on the stack the shim
refuses every press except from the ops that own the choice, the bridge
does not ride it, and the observation says a learn is up from its first
page. The executor walks it: A for a page of text, YES at the yes/no (the
list is where the choice is made, and CANCEL there is the no), and the
list goes to the model with each move's type and power. Which move goes
is the model's.
"""
from __future__ import annotations
import copy
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402
import brock_probe                                        # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

PARTY = [{"species": "FARFETCHD", "types": ["NORMAL", "FLYING"]},
         {"species": "CHARMELEON", "types": ["FIRE"]},
         {"species": "PIKACHU", "nickname": "ZAPPER", "types": ["ELECTRIC"], "level": 26}]
LEARN = {"learner": "PIKACHU", "learner_slot": 3,
         "new_move": {"id": "SWIFT", "type": "NORMAL", "power": 60},
         "moves": [{"id": "THUNDERBOLT", "type": "ELECTRIC", "power": 95},
                   {"id": "BODY_SLAM", "type": "NORMAL", "power": 85},
                   {"id": "THUNDER_WAVE", "type": "ELECTRIC", "power": 0},
                   {"id": "QUICK_ATTACK", "type": "NORMAL", "power": 40}],
         "selecting": False}
PAGE = {"mode": "ui", "party": PARTY, "ui": {"learn": copy.deepcopy(LEARN), "is_choice": False}}
CHOICE = {"mode": "ui", "party": PARTY, "ui": {"learn": copy.deepcopy(LEARN), "is_choice": True, "index": 1}}
LIST = {"mode": "ui", "party": PARTY,
        "ui": {"screenId": "MoveLearnMenu", "selecting": True, "index": 1,
               "learner": "PIKACHU", "new_move": "SWIFT",
               "moves": ["THUNDERBOLT", "BODY_SLAM", "THUNDER_WAVE", "QUICK_ATTACK"],
               "learn": dict(copy.deepcopy(LEARN), selecting=True)}}
DONE = {"mode": "overworld", "party": PARTY, "ui": {}}
SG = {"id": "reach_route_9", "goal_text": "Travel north from Vermilion City to Route 9."}

asked = []
def stub(answer, queue):
    o = types.SimpleNamespace(sent=[], logged=[], model="stub", _queue=list(queue))
    o.b = types.SimpleNamespace(send=lambda op, **kw: o.sent.append((op, kw)) or {"result": {"ok": True}})
    o.settle = lambda: (o._queue.pop(0) if o._queue else DONE)
    o.log = lambda kind, **kw: o.logged.append((kind, kw))
    o.FORGET_SYS = E.Executor.FORGET_SYS
    o._is_question = E.Executor._is_question
    for m in ("_maybe_forget", "_resolve_learn"):
        setattr(o, m, types.MethodType(getattr(E.Executor, m), o))
    brock_probe.chat = lambda msgs, model, **kw: (asked.append(msgs) or answer)
    return o

# ---- the walk: text, YES, then the list to the model -----------------------------
o = stub('{"why":"Quick Attack is the weakest and Swift never misses","forget":"QUICK_ATTACK"}',
         [PAGE, CHOICE, LIST, DONE]); asked.clear()
out = o._resolve_learn(PAGE, SG)
ck("a page of the prompt's text is advanced with A", o.sent[0] == ("tap", {"btn": "a"}), o.sent)
ck("...twice, one per page in this stub", o.sent[1] == ("tap", {"btn": "a"}), o.sent)
ck("the yes/no is answered YES by cursor, opening the list", o.sent[2] == ("menu", {"index": 1}), o.sent)
ck("the list goes to the model, once", len(asked) == 1, len(asked))
u = asked[0][-1]["content"]
ck("...with the learner's types", "PIKACHU (ELECTRIC) is trying to learn" in u, u)
ck("...the new move's type and power", "SWIFT (NORMAL, power 60)" in u, u)
ck("...and every known move's type and power",
   "1=THUNDERBOLT (ELECTRIC, power 95)" in u and "2=BODY_SLAM (NORMAL, power 85)" in u
   and "3=THUNDER_WAVE (ELECTRIC)" in u and "4=QUICK_ATTACK (NORMAL, power 40)" in u, u)
ck("...and what the run is in the middle of", SG["goal_text"] in u)
ck("the harness recommends nothing",
   not any(w in (u + asked[0][0]["content"]).lower() for w in ("you should", "keep thunderbolt", "forget quick", "stab")), u)
ck("the model's slot is pressed", o.sent[3] == ("menu", {"index": 4}), o.sent)
ck("...and the answer is on record",
   any(k == "move_forget" and kw.get("forget") == "QUICK_ATTACK" and kw.get("new") == "SWIFT (NORMAL, power 60)"
       for k, kw in o.logged) and sum(1 for k, _ in o.logged if k == "learn_seen") == 1, o.logged)
ck("the observation handed back is the settled one", out is DONE)

# ---- keeping the four is a real answer: CANCEL, then the abandon question -------
o = stub('{"why":"nothing here is worth Thunderbolt","forget":null}', [LIST, {"mode": "ui", "ui": {"index": 1, "is_choice": True}}, DONE]); asked.clear()
o._resolve_learn(PAGE, SG)
ck("a no is CANCEL on the list, then yes to abandoning",
   ("menu", {"index": 5}) in o.sent and ("tap", {"btn": "a"}) in o.sent[o.sent.index(("menu", {"index": 5})):], o.sent)

# ---- an unreadable answer keeps the four moves ---------------------------------
o = stub("sure, drop the weak one", [LIST, DONE]); asked.clear()
o._resolve_learn(LIST, SG)
ck("an answer that is not JSON keeps the four moves (CANCEL), never slot 1",
   ("menu", {"index": 5}) in o.sent and ("menu", {"index": 1}) not in o.sent, o.sent)

# ---- the old shape still works when the shim has not been rebooted yet ----------
OLD = {"mode": "ui", "party": PARTY, "ui": {"screenId": "MoveLearnMenu", "selecting": True, "index": 1,
                                             "learner": "PIKACHU", "new_move": "SWIFT",
                                             "moves": ["THUNDERBOLT", "BODY_SLAM", "THUNDER_WAVE", "QUICK_ATTACK"]}}
o = stub('{"why":"x","forget":"BODY_SLAM"}', [DONE]); asked.clear()
o._maybe_forget(OLD, SG)
ck("without the facts block the question still names the moves and presses the answer",
   "1=THUNDERBOLT" in asked[0][-1]["content"] and o.sent == [("menu", {"index": 2})], (asked, o.sent))

# ---- nothing runs twice on itself, and no learn means no-op ---------------------
o = stub('{"why":"x","forget":"BODY_SLAM"}', [DONE]); asked.clear()
o._resolving_learn = True
ck("re-entry is a no-op", o._resolve_learn(PAGE, SG) is PAGE and o.sent == [])
o = stub('{"why":"x","forget":"BODY_SLAM"}', [DONE])
ck("no learn on the page: nothing pressed", o._resolve_learn(DONE, SG) is DONE and o.sent == [])

# ---- wiring: every settled observation and the ui drain route here ----------------
src = (ROOT / "planner" / "executor.py").read_text()
ck("a settled observation with a learn is walked here",
   'o = self._resolve_learn(o, getattr(self, "_cur_sg", None) or {})' in src)
i_lu = src.index("def _leave_ui(")
ck("the ui drain walks a learn before anything else, so B never abandons one",
   "return self._resolve_learn(obs, sg)" in src[i_lu:i_lu + 1500]
   and src[i_lu:].index("return self._resolve_learn(obs, sg)") < src[i_lu:].index('self.b.send("tap", btn="b")'))

# ---- the shim: nothing lands blind, and the learn is said from page one -----------
lua = (ROOT / "harness" / "shim.lua").read_text()
i_w = lua.index("U.tap = function(game, btn)")
ck("every button is refused while a learn is on the stack, unless its owner presses",
   "if not learn_driver and learn_on_stack and learn_on_stack(game) then" in lua[i_w:i_w + 600]
   and 'REFUSED-LEARN' in lua[i_w:i_w + 900])
ck("the ops that own the choice raise the flag, one op at a time",
   'learn_driver = (cmd.op == "menu" or cmd.op == "tap"\n                      or cmd.op == "use_item")' in lua
   and lua.index("learn_driver = (cmd.op") < lua.index("learn_driver = false\n      result = {"))
ck("the bridge treats a learn as the decision instead of riding it",
   "if learn_on_stack(G) then return true end" in lua[lua.index("local function decision_reached(G)"):][:400])
ck("the observation reports a learn from its first page, with type and power",
   "o.ui.learn = {" in lua and "new_move = movefacts(lm.newMoveId)" in lua
   and "selecting = lm.selecting and true or false" in lua)
ck("the earlier guards still stand (the fight loop and observe)",
   "if _learn or (t and t.screenId == \"MoveLearnMenu\") then" in lua
   and "elseif battle_frame(G) and not learn_on_stack(G) then" in lua)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:400])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
