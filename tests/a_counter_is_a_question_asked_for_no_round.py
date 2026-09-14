#!/usr/bin/env python3
"""Standing in a room with a shop counter, the harness asks what to buy,
for no round, and does only what the answer says.

Buying was the one shop action still costing a round. The page already
said what each walked counter sells and that the battle policy was
reaching for a POTION the bag did not hold, and nothing brought the two
together except the model spending a round on it. Watched on leg 10
(2026-09-14): three blackouts against Misty, 466 money, a Center visit to
withdraw ONE Potion from the PC, and the Cerulean mart three doors away
never entered. So it is the Center heal's shape: the facts of the room
(the shelf, the money, the bag and its slots, what the policy cannot
find), a small answer space, one model call, no round.

A question, not a deed: buying spends money that has competing uses and
fills bag slots, which is why the stow order exists. Both are judgments,
so the harness asks and executes and recommends nothing. Asked once per
visit, on every visit with money (user: "every visit yeah").
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

E.set_active_spec({"battle_items": [{"item": "POTION", "hp_below": 0.3}]})

SHELF = ["POKE_BALL", "POTION", "ANTIDOTE", "PARLYZ_HEAL", "BURN_HEAL", "REPEL"]
MART = {"mode": "overworld", "money": 466,
        "map": {"id": "CERULEAN_MART", "region": "0,2",
                "objects": [{"name": "CERULEANMART_CLERK", "kind": "person",
                             "reachable": True, "x": 0, "y": 3}]},
        "bag": {"POKE_BALL": 9, "ESCAPE_ROPE": 1, "DOME_FOSSIL": 1,
                "S_S_TICKET": 1, "TM_WATER_GUN": 1},
        "party": [{"species": "PIKACHU", "nickname": "Sparky", "level": 15, "hp": 40, "max_hp": 40},
                  {"species": "CHARMELEON", "nickname": "Ignis", "level": 26, "hp": 30, "max_hp": 75}]}
AFTER = copy.deepcopy(MART)
AFTER["bag"]["POTION"] = 2
AFTER["money"] = 166
SG = {"id": "defeat_misty", "goal_text": "Defeat Gym Leader Misty in battle."}

asked = []
def fake(answer='{"why":"Ignis is hurt and the policy reaches for a Potion I do not carry","buy":[{"item":"POTION","count":2}]}',
         reply_ok=True, detail=None, after=AFTER, shelf=SHELF, reads=2, prices=None):
    o = types.SimpleNamespace(sent=[], logged=[], model="stub")
    def send(op, **kw):
        o.sent.append((op, kw))
        return {"result": {"ok": reply_ok,
                           "detail": detail if detail is not None else
                           ("bought: POTION x2 in bag, 166 money left" if reply_ok
                            else "cannot afford POTION: it costs 300 and you have 100")}}
    o._send_safe = send
    o.settle = lambda: after
    o.log = lambda kind, **kw: o.logged.append((kind, kw))
    o._where = E.Executor._where
    o._clerk_here = E.Executor._clerk_here
    o._policy_unmet = E.Executor._policy_unmet
    o._policy_heal_line = types.MethodType(E.Executor._policy_heal_line, o)
    o.BUY_SYS = E.Executor.BUY_SYS
    o.BUY_MAX_ENTRIES = E.Executor.BUY_MAX_ENTRIES
    o.BAG_SLOTS = E.Executor.BAG_SLOTS
    o._shelves = {"CERULEAN_MART": list(shelf)} if shelf else {}
    o._shelf_reads = {"CERULEAN_MART": {"n": reads, "moved": False}} if shelf else {}
    o._cant_afford = dict(prices or {})
    o._ask_buy = types.MethodType(E.Executor._ask_buy, o)
    brock_probe.chat = lambda msgs, model, **kw: (asked.append(msgs) or answer)
    return o

# ---- the question --------------------------------------------------------------
o = fake(); asked.clear()
out = o._ask_buy(MART, SG)
ck("a counter with money in the wallet is ASKED about, once", len(asked) == 1, len(asked))
u = asked[0][-1]["content"]; sysm = asked[0][0]["content"]
ck("...with what this counter was seen to sell, and how often it was read",
   "WHAT IT WAS SEEN TO SELL: POKE_BALL, POTION, ANTIDOTE" in u and "read 2x" in u, u)
ck("...the money", "YOUR MONEY: 466" in u)
ck("...the bag and its slots", "YOUR BAG (5 of 20 kinds)" in u and "POKE_BALL x9" in u)
ck("...the party as the screen shows it", "Ignis L26 30/75 hp" in u)
ck("...what the battle policy reaches for and cannot find",
   "reaches for POTION in a fight and you are carrying none" in u, u)
ck("...the counter by its own name", "THE COUNTER: CERULEANMART_CLERK" in u)
ck("...what the run is in the middle of", SG["goal_text"] in u)
ck("...and that no round is spent either way", "No round is spent" in u)
ck("the harness recommends nothing in the question",
   not any(w in (u + sysm).lower() for w in ("you should", "buy now", "go buy", "you must", "you need")), u)
ck("saying no is offered as a real answer", "Saying no is a real answer" in sysm)
ck("the slot rule is stated as the game's, not as advice",
   "twenty slots" in sysm and "full bag refuses" in sysm)

# ---- yes: the deed follows, for no round ----------------------------------------
ck("a yes is carried out with a buy op naming the clerk",
   o.sent == [("buy", {"item": "POTION", "count": 2, "clerk": "CERULEANMART_CLERK"})], o.sent)
ck("...and the observation handed back is the one after the purchase", out is AFTER)
ck("...and the answer and its reason are on record",
   any(k == "buy_asked" and "POTION" in kw.get("buy", "") and "hurt" in kw.get("why", "")
       and kw.get("shelf", "").startswith("POKE_BALL") and kw.get("money") == 466
       and kw.get("bag_slots") == 5 and kw.get("dead") == "POTION" for k, kw in o.logged)
   and any(k == "buy_done" and kw.get("ok") and kw.get("item") == "POTION" for k, kw in o.logged), o.logged)

# the op's count is a TARGET (own N total): buying 2 more when 1 is held asks for 3
HELD1 = copy.deepcopy(MART); HELD1["bag"]["POTION"] = 1
o = fake(); asked.clear()
o._ask_buy(HELD1, SG)
ck("'buy 2' with 1 already held sends the op's target count of 3",
   o.sent and o.sent[0][1]["count"] == 3, o.sent)

# ---- no: nothing happens, and the answer stands for the visit ------------------
o = fake(answer='{"why":"Nine balls and a Potion in the PC is enough for the gym","buy":[]}'); asked.clear()
o._ask_buy(MART, SG)
ck("a no sends nothing", o.sent == [])
ck("...and is on record with its reason",
   any(k == "buy_asked" and kw.get("buy") == "[]" and "enough" in kw.get("why", "") for k, kw in o.logged))
o._ask_buy(MART, SG)
ck("the question is not put again the same visit", len(asked) == 1, len(asked))
OUTSIDE = {**MART, "map": {"id": "CERULEAN_CITY", "region": "4,4", "objects": []}}
o._ask_buy(OUTSIDE, SG); o._ask_buy(MART, SG)
ck("...until the party has left the room and come back", len(asked) == 2, len(asked))
o = fake(answer='{"why":"nothing needed","buy":null}'); asked.clear()
o._ask_buy(MART, SG)
ck("buy: null is a no", o.sent == [] and len(asked) == 1)

# ---- what is never asked ---------------------------------------------------------
o = fake(); asked.clear()
o._ask_buy({**MART, "map": {**MART["map"], "objects": [{"name": "PC", "reachable": True}]}}, SG)
ck("no clerk in the room: no question", asked == [] and o.sent == [])
o._ask_buy({**MART, "mode": "dialog"}, SG); ck("not in the overworld: no question", asked == [])
o._ask_buy({**MART, "map": {**MART["map"], "objects": [{"name": "CERULEANMART_CLERK", "reachable": False}]}}, SG)
ck("a clerk no walk reaches: no question", asked == [])
o._ask_buy({**MART, "money": 0}, SG); ck("an empty wallet: no question", asked == [])
NURSE = {**MART, "map": {**MART["map"], "objects": [{"name": "CERULEANPOKECENTER_NURSE", "reachable": True}]}}
o._ask_buy(NURSE, SG); ck("a nurse is not a clerk", asked == [])

# ---- an unreadable answer is a no -----------------------------------------------
o = fake(answer="sure, two potions"); asked.clear()
o._ask_buy(MART, SG)
ck("an answer that is not JSON buys nothing", o.sent == [] and len(asked) == 1)
ck("...and the record says it was unreadable",
   any(k == "buy_asked" and kw.get("readable") is False for k, kw in o.logged))

# ---- the answer is checked against the facts it was asked on -------------------
o = fake(answer='{"why":"a stronger potion","buy":[{"item":"SUPER_POTION","count":2}]}'); asked.clear()
o._ask_buy(MART, SG)
ck("an item this counter's shelf does not list is refused without an op",
   o.sent == [] and any(k == "buy_refused" and "SUPER_POTION: not on this counter's shelf" in kw.get("what", "")
                        for k, kw in o.logged), o.logged)
o = fake(answer='{"why":"balls","buy":[{"item":"POKE_BALL","count":5}]}',
         prices={"POKE_BALL": 200}); asked.clear()
o._ask_buy(MART, SG)
ck("a count the wallet cannot cover at a price already told is trimmed, and the trim is said",
   o.sent == [("buy", {"item": "POKE_BALL", "count": 9 + 2, "clerk": "CERULEANMART_CLERK"})]
   and any(k == "buy_done" and "trimmed from 5" in kw.get("trimmed", "") for k, kw in o.logged), (o.sent, o.logged))
o = fake(answer='{"why":"a repel","buy":[{"item":"REPEL","count":1}]}',
         prices={"REPEL": 500}); asked.clear()
o._ask_buy(MART, SG)
ck("a price already told that the wallet is short of is refused without an op",
   o.sent == [] and any(k == "buy_refused" and "REPEL: costs 500 and you have 466" in kw.get("what", "")
                        for k, kw in o.logged), o.logged)
FULL = copy.deepcopy(MART)
FULL["bag"] = {f"TM_{i:02d}": 1 for i in range(19)}; FULL["bag"]["POKE_BALL"] = 3
o = fake(answer='{"why":"potions and balls","buy":[{"item":"POTION","count":2},{"item":"POKE_BALL","count":2}]}'); asked.clear()
o._ask_buy(FULL, SG)
ck("a full bag refuses a NEW kind and still buys one it holds",
   [s[1]["item"] for s in o.sent] == ["POKE_BALL"]
   and any(k == "buy_refused" and "POTION: the bag is full" in kw.get("what", "") for k, kw in o.logged), (o.sent, o.logged))
ck("...and the question said how full it was", "YOUR BAG (20 of 20 kinds)" in asked[0][-1]["content"])
o = fake(answer='{"why":"stock up","buy":[{"item":"POTION","count":1},{"item":"ANTIDOTE","count":1},{"item":"REPEL","count":1},{"item":"POKE_BALL","count":1}]}'); asked.clear()
o._ask_buy(MART, SG)
ck("the list is capped at three entries", len(o.sent) == 3, o.sent)
o = fake(answer='{"why":"a potion","buy":[{"item":"potion","count":"2"}]}'); asked.clear()
o._ask_buy(MART, SG)
ck("lower case and a quoted count are read", o.sent and o.sent[0][1] == {"item": "POTION", "count": 2, "clerk": "CERULEANMART_CLERK"}, o.sent)

# ---- the counter's own refusal ends the list and teaches a price -----------------
o = fake(answer='{"why":"stock up","buy":[{"item":"POTION","count":5},{"item":"ANTIDOTE","count":2}]}',
         reply_ok=False, after=MART); asked.clear()
o._ask_buy(MART, SG)
ck("the counter's refusal stops the list", len(o.sent) == 1, o.sent)
ck("...is reported verbatim", any(k == "buy_refused" and "cannot afford POTION: it costs 300" in kw.get("what", "")
                                  for k, kw in o.logged), o.logged)
ck("...and its price is kept, as a round would keep it", o._cant_afford.get("POTION") == 300, o._cant_afford)

# ---- a shelf never read is said, not guessed --------------------------------------
o = fake(shelf=None); asked.clear()
o._ask_buy(MART, SG)
ck("a counter whose list was never read says so",
   "never read this counter's list" in asked[0][-1]["content"] and "WAS SEEN TO SELL" not in asked[0][-1]["content"])
ck("...and a buy there is sent for the counter to answer", len(o.sent) == 1)

# ---- two counters on one floor -----------------------------------------------------
TWO = copy.deepcopy(MART)
TWO["map"]["objects"].append({"name": "CELADONMART5F_CLERK2", "reachable": True, "x": 5, "y": 3})
o = fake(answer='{"why":"vitamins","buy":[{"item":"POTION","count":1,"clerk":"CELADONMART5F_CLERK2"}]}'); asked.clear()
o._ask_buy(TWO, SG)
ck("with two counters the entry may name which, and the question says so",
   o.sent and o.sent[0][1]["clerk"] == "CELADONMART5F_CLERK2" and "More than one counter" in asked[0][-1]["content"], o.sent)
o = fake(answer='{"why":"x","buy":[{"item":"POTION","count":1,"clerk":"NOBODY"}]}'); asked.clear()
o._ask_buy(TWO, SG)
ck("a clerk name that is not on the floor falls back to the first", o.sent and o.sent[0][1]["clerk"] == "CERULEANMART_CLERK")

# ---- it sits at the round boundary beside the heal question -----------------------
src = (ROOT / "planner" / "executor.py").read_text()
i_stow = src.index("start = self._stow_at_pc(start, sg) or start")
i_heal = src.index("start = self._ask_heal(start, sg) or start")
i_buy = src.index("start = self._ask_buy(start, sg) or start")
i_teach = src.index("start = self._ask_teach(start, sg) or start")
i_stone = src.index("start = self._ask_stone(start, sg) or start")
ck("it runs at the round boundary, after the heal question and before the TM one",
   i_stow < i_heal < i_buy < i_teach < i_stone)
ck("the page line and the question read the policy's unmet item from ONE computation",
   src.count("Executor._policy_unmet(obs)") == 1 and "dead, _held = self._policy_unmet(obs)" in src)
ck("nothing buys without an answer", "_buy_here" not in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:400])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
