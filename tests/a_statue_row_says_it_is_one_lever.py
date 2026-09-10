"""The Mansion's statues are ONE lever, and the ROW has to say so.

The header has said "THEY ALL SHARE ONE SETTING" since 2026-08-24.  The
rows underneath went on keeping a separate book per tile -- pressed 2x
here, pressed 1x on the floor below, never pressed on the floor above --
and a row is where the choice is actually made.  Read together those are
four levers, three with tries left, and run 16 played them exactly that
way: up to press one, down to press another, each press undoing the last
(user, 2026-09-10: "the thing the model has to understand about the
switches is that they are a connected global toggle, so we should watch
out for whatever kind of language we have that could imply otherwise").

Three sentences said the wrong thing and all three are here: the row's
"it can be pressed again" (true of a trash can, the opposite move on a
lever), the re-offer that called a statue somebody worth another word,
and the remote lists that sold an unreachable statue on another floor as
a thing never touched with a way in still to find.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E, ledger

HERE = "POKEMON_MANSION_2F|6,1"
NEAR = "SWITCH_POKEMON_MANSION_2F_2_11"
FAR = "SWITCH_POKEMON_MANSION_2F_10_5"
CAN = "TRASH_CAN_POKEMON_MANSION_2F_4_4"


def fresh(tried=(), again=()):
    ex = E.Executor.__new__(E.Executor)
    ex.explored = {HERE: {}}
    ex.visits = {HERE: 3}
    ex._where = lambda o: HERE
    ex._taken_here = lambda here: {}
    ex._spent_exits = lambda here: {}
    ex._sealed = lambda here: set()
    ex._walked_dest = lambda mid, key: None
    ex.dead_for = lambda t, r: 0
    ex._untaken = lambda m, t: set(tried)
    ex._worth_another_word = lambda here, obs, backfill=True: list(again)
    ex._tried_objs = {HERE: set(tried)}
    return ex


def obs_of(on=True):
    return {"mode": "overworld", "player": {"x": 6, "y": 1},
            "party": [],
            "map": {"id": "POKEMON_MANSION_2F", "region": "6,1",
                    "warps": [], "connections": {},
                    "switch_statues": [{"x": 2, "y": 11, "reachable": True},
                                       {"x": 10, "y": 5, "reachable": False}],
                    "switches_on": on,
                    "objects": [
                        {"x": 2, "y": 11, "kind": "fixture", "name": NEAR,
                         "reachable": True,
                         "toggle": "PRESSED" if on else "UNPRESSED"},
                        {"x": 10, "y": 5, "kind": "fixture", "name": FAR,
                         "reachable": False,
                         "toggle": "PRESSED" if on else "UNPRESSED"},
                        {"x": 4, "y": 4, "kind": "fixture", "name": CAN,
                         "reachable": True},
                    ]}}


def rows(ex, obs):
    cands = None
    for _ in range(80):
        try:
            cands = ledger.build(ex, obs)
            break
        except AttributeError as e:
            setattr(ex, str(e).split("'")[-2], {})
    text = ledger.render(cands, ex, obs)
    return cands, {ln.split(". ", 1)[-1].split(" ")[0]: ln
                   for ln in text.splitlines() if " — " in ln}, text


# ---- the row of a statue that HAS been pressed --------------------------
ex = fresh(tried=(NEAR, CAN))
cands, byname, text = rows(ex, obs_of(True))
def row_of(txt, name, at):
    return next(ln for ln in txt.splitlines()
                if name in ln and f"(fixture at {at})" in ln)


near = row_of(text, NEAR, "2,11")

ck("the row says the statues share one lever",
   "ONE HANDLE OF A LEVER" in near and "BUILDING SHARES" in near)
ck("...and which way that lever is set right now",
   "set to PRESSED right now" in near)
ck("...and that a second press undoes the first",
   "puts the first one back" in near)
ck("...and that a never-pressed statue is not an untried thing",
   "never pressed is not an untried thing" in near)
ck("the trash-can wording is gone from the statue",
   "it can be pressed again" not in near)

# the setting is read from the world, not assumed
_, _, text_off = rows(fresh(tried=(NEAR, CAN)), obs_of(False))
ck("an unpressed lever reads as unpressed",
   "set to UNPRESSED right now" in
   row_of(text_off, NEAR, "2,11"))

# ---- ...and the row of one no walk reaches ------------------------------
far = row_of(text, FAR, "10,5")
ck("an unreachable statue still says it cannot be walked to",
   "cannot walk to it" in far or "no walk" in far.lower())
ck("...and carries the same lever fact, so the way in is not the prize",
   "ONE HANDLE OF A LEVER" in far)

# ---- a trash can is still a thing you can press again -------------------
can = row_of(text, CAN, "4,4")
ck("a trash can keeps 'it can be pressed again'",
   "it can be pressed again" in can)
ck("...and says nothing about a lever", "LEVER" not in can)

# ---- a lever is never 'worth another word' -----------------------------
ex2 = fresh(tried=(NEAR, CAN), again=(NEAR, CAN))
cands2, _, text2 = rows(ex2, obs_of(True))
by = {c.key: c for c in cands2}
ck("a statue pressed when the world was different is not re-offered",
   by[NEAR].status != "worth_a_word")
ck("...while a trash can still is", by[CAN].status == "worth_a_word")

# ---- the remote lists drop handles of a lever already thrown -----------
ex3 = E.Executor.__new__(E.Executor)
ex3._tried_objs = {}
ck("nothing thrown yet, so a far statue is still a thing left undone",
   not ex3._lever_already_thrown(FAR, "POKEMON_MANSION_3F|5,8"))
ex3._tried_objs = {"POKEMON_MANSION_1F|1,1": {"SWITCH_POKEMON_MANSION_1F_2_5"}}
ck("one press anywhere in the building throws it for every floor",
   ex3._lever_already_thrown(FAR, "POKEMON_MANSION_3F|5,8"))
ck("...and says nothing about another building",
   not ex3._lever_already_thrown("SWITCH_SILPH_CO_5F_1_1", "SILPH_CO_5F|1,1"))
ck("...and nothing about things that are not levers",
   not ex3._lever_already_thrown("POKEMONMANSION3F_DIARY",
                                 "POKEMON_MANSION_3F|5,8"))

# ---- _worth_another_word itself keeps levers out ------------------------
ex4 = E.Executor.__new__(E.Executor)
ex4._touch_mark = {HERE: {NEAR: {"then": "old", "n": 0},
                          CAN: {"then": "old", "n": 0}}}
ex4._tried_objs = {HERE: {NEAR, CAN}}
ex4._world_mark = lambda o: "new"
ck("the re-offer list drops the statue and keeps the can",
   ex4._worth_another_word(HERE, {}, backfill=False) == [CAN])
ck("...and the backfilling form agrees",
   ex4._worth_another_word(HERE, {}, backfill=True) == [CAN])

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
if bad:
    print("\nNEAR:", near[:600])
    print("\nFAR:", far[:600])
    print("\nCAN:", can[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
