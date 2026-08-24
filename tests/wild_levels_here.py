"""What level the wilds here have actually been.

The species tally says whether the thing you want lives on a map; it cannot
say whether fighting there is worth a round. A level-43 party walking back
to ROUTE_22 to grind on L2-L6 wilds spends a whole leg for nothing — and the
run had already fought them there, 2125 battles logged with the foe's level
in every one, with no page able to say so (user, 2026-08-24: "uhoh, its
going to try to grind in rt 22").

The note states two numbers the run owns and draws no conclusion from them.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "planner"))
from executor import _wild_level_note

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


class Ex:
    def __init__(self, book):
        self._wild_lv = book


party = {"party": [{"level": 43}, {"level": 26}, {"level": 63}]}

note = _wild_level_note(Ex({"ROUTE_22": {"lo": 2, "hi": 6, "n": 14}}),
                        "ROUTE_22", party)
ck("names the range fought there", "L2-L6" in note)
ck("names how many battles", "14 battle(s)" in note)
ck("names the party's own spread", "L26-L63" in note)
ck("draws no conclusion", not any(w in note.lower() for w in
   ("waste", "too low", "should", "worth", "pointless", "instead")))

one = _wild_level_note(Ex({"M": {"lo": 5, "hi": 5, "n": 3}}), "M", party)
ck("a single level reads as one number", "L5 across" in one)

ck("a map never fought on says nothing",
   _wild_level_note(Ex({}), "ROUTE_1", party) == "")
ck("a partial record says nothing",
   _wild_level_note(Ex({"M": {"lo": 3}}), "M", party) == "")
ck("no party is not an error",
   "across 2 battle(s)" in _wild_level_note(
       Ex({"M": {"lo": 3, "hi": 4, "n": 2}}), "M", {}))

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
