"""A journey the model NAMED is walked in one round, not one border a round.

2026-09-02, user watching the Lavender leg: "its mostly just getting stuck at
borders". Twenty-eight of forty escalation rounds ran a SINGLE op, almost
always a bare `cross`. Each round the model wrote a whole trip in its own
words ("travel to Cerulean City to systematically re-examine every NPC"),
emitted the first hop, and the round ended; the next round re-derived the same
trip one border along and bounced back (ROUTE_11 <-> ROUTE_12, VERMILION <->
ROUTE_6). It never arrived, so the NPC sweep it promised every round never
happened, and the escalation budget went on borders.

`go` walks a whole walked route in ONE round, and the harness already had the
sentence that says so — inside the truncation note, which only fires when a
macro is CUT. That fired twice in four hundred records, because the model was
not writing long macros to cut; it was writing one hop at a time. The advice
existed and could never reach the rounds that needed it.

What the harness owes it: on a round spent on a border, if the model's OWN
words named a place the run has already walked to, say that `go` does that
trip in one round. Only a place it named, only over ground already walked,
only when it is more than the one hop just taken. Naming a place it did not
name, or a route never walked, would be pointing."""
import sys
from pathlib import Path
sys.path.insert(0, "planner")
import executor as E

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

HERE = "ROUTE_11|58,8"
GRAPH = {
    "ROUTE_11|58,8": {}, "ROUTE_11|9,0": {}, "ROUTE_12|0,61": {},
    "CERULEAN_CITY|20,0": {}, "VERMILION_CITY|18,0": {}, "ROUTE_1|10,0": {},
}
# hops the WALKED graph needs, by destination region
HOPS = {"CERULEAN_CITY|20,0": 8, "VERMILION_CITY|18,0": 3,
        "ROUTE_12|0,61": 1, "ROUTE_11|9,0": 2}


def fake(here=HERE):
    ex = object.__new__(E.Executor)
    ex.explored = dict(GRAPH)
    ex.settle = lambda: {"map": {"id": here.split("|")[0]}}
    ex._where = lambda obs: here
    ex._route = lambda frm, to, avoid=None, ignore_blocked=False: (
        [None] * HOPS[to] if to in HOPS else None)
    return ex


CROSS = [{"op": "cross", "dir": "west"}]

said = fake()._go_would_have(
    CROSS, "I will travel to Cerulean City to re-examine every NPC.")
ck("a named place the run has walked to earns the go sentence", said)
ck("...it names that place", "Cerulean City" in said)
ck("...as a go op the model can copy", '{"op":"go","to":"CERULEAN_CITY"}' in said)
ck("...and says how many legs the walked ground covers", "8 legs" in said)
ck("...and says this round spent itself on one of them",
   "ONE of them" in said)

ck("a round that already used go says nothing",
   not fake()._go_would_have(
       CROSS + [{"op": "go", "to": "CERULEAN_CITY"}],
       "I will travel to Cerulean City."))
ck("a round that never crossed a border says nothing",
   not fake()._go_would_have(
       [{"op": "walk_to", "x": 1, "y": 2}], "I will travel to Cerulean City."))
ck("no plan text, nothing to echo", not fake()._go_would_have(CROSS, ""))

# THE POINTING GUARDS
ck("a place the model did NOT name is never offered",
   not fake()._go_would_have(CROSS, "I am blocked and will look around here."))
ck("a place the walked graph does not reach is never offered",
   not fake()._go_would_have(CROSS, "I will travel to Route 1."))
ck("...even though the run has walked ROUTE_1 (it is the ROUTE that is "
   "unreachable, not the name that is unknown)", "ROUTE_1|10,0" in GRAPH)
ck("one hop away is not a journey worth a sentence",
   not fake()._go_would_have(CROSS, "I will cross east to Route 12."))
ck("where you already stand is never offered",
   not fake()._go_would_have(CROSS, "I am on Route 11 and will look around."))

# "route 1" must not be found inside "route 12"
only12 = fake()._go_would_have(CROSS, "I will go to Route 12 and then onward.")
ck("a route id's digits are part of its name", not only12)
two = fake()._go_would_have(
    CROSS, "I will go to Vermilion City and then to Cerulean City.")
ck("naming two reachable places takes the longer walk", "Cerulean City" in two)

src = Path("planner/executor.py").read_text()
ck("it is wired where the truncation note could not reach",
   "_go_would_have(macro, self._plan_said)" in src
   and "That is the case the" in src)
ck("a failure in it never costs the round",
   "except Exception:\n                    _go_note = \"\"" in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok  " if ok else "  FAIL") + "  " + n)
print(f"\n{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
