"""How much more experience is needed for the next level.

`exp` was published and the number it is measured against never was, so a
grind could be reported as "earned 412 exp" with nothing to weigh it
against — 412 is most of a level at L15 and a rounding error at L45, and
that difference is the whole decision (user, 2026-08-24: "can we say how
much exp is needed for a lvl up so it has some kind of comparison to
measure against"). The engine's own curve (src/pokemon/Growth.lua) answers
it; the shim publishes exp_next_level per party member.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "planner"))
from executor import _exp_needed_note

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


party = {"party": [
    {"species": "TENTACOOL", "level": 19, "exp_next_level": 180},
    {"species": "NIDOQUEEN", "level": 45, "exp_next_level": 4858}]}
note = _exp_needed_note(party)

ck("names each member and what it needs",
   "TENTACOOL L19 needs 180" in note and "NIDOQUEEN L45 needs 4858" in note)
ck("totals the party", "the party together, 5038" in note)
ck("draws no conclusion", not any(w in note.lower() for w in
   ("should", "worth", "instead", "too slow", "better")))

ck("a party with no curve data says nothing",
   _exp_needed_note({"party": [{"species": "X", "level": 5}]}) == "")
ck("no party at all says nothing", _exp_needed_note({}) == "")
ck("a partial party still reports the members it knows",
   "A L5 needs 10" in _exp_needed_note({"party": [
       {"species": "A", "level": 5, "exp_next_level": 10},
       {"species": "B", "level": 6}]}))

# the shim must actually publish the field
shim = (pathlib.Path("/home/wiz/Developer/red-recomp/harness/shim.lua")
        .read_text())
ck("the shim publishes exp_next_level", "m.exp_next_level" in shim)
ck("...from the engine's own curve", "Growth.expForLevel" in shim)
ck("...and leaves no debug field behind", "_dbg" not in shim)

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
