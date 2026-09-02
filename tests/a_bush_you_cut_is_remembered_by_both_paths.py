"""A bush you already cut is remembered, whichever way the op was run.

A cut bush grows back on reload in this recomp, faithfully, so cutting it
again reopens ground the first cut already opened. The ledger knows: a bush
in the cut record ranks "recut" rather than "cuttable" and drops out of
explore's first line. The record was never written, so that demotion has
never once engaged in the life of the project.

It failed twice for different reasons. First the test demanded "hacked away"
in the note while the success branch wrote ": ok (changes)" (fixed
2026-08-22). Then it went on failing, because an aimed field move is served by
an EARLIER handler in _run_traced which appends its own trace and continues —
so the record at the bottom of the loop was unreachable for precisely the op
it was written for.

Measured 2026-09-02, when the user said it plainly ("its literally only just
cutting the same trees over and over thinking its doing something novel"):
196 successful cuts across seven bushes, every one reported "hacked away",
and the record still empty. One Cerulean bush had been cut 34 times and was
still offered as item 1, "a way on".

This is the test the TODO asked for after the third drift bug of that week:
send one op through both dispatch sites and assert the same side effects."""
import sys
from pathlib import Path
sys.path.insert(0, "planner")
import executor as E

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

OBS = {"map": {"id": "CERULEAN_CITY"}}


def fake():
    ex = object.__new__(E.Executor)
    ex._cut_bushes = {}
    ex._save_memory = lambda: None
    return ex


ex = fake()
ex._note_cut(OBS, {"op": "field_move", "move": "CUT", "x": 19, "y": 28})
ck("a cut is remembered against its map",
   ex._cut_bushes.get("CERULEAN_CITY") == ["19,28"])

ex._note_cut(OBS, {"op": "field_move", "move": "CUT", "x": 19, "y": 28})
ck("...once, however many times it is cut again",
   ex._cut_bushes["CERULEAN_CITY"] == ["19,28"])

ex._note_cut(OBS, {"op": "field_move", "move": "CUT", "x": 5, "y": 8})
ck("a second bush on the same map is its own entry",
   ex._cut_bushes["CERULEAN_CITY"] == ["19,28", "5,8"])

ex._note_cut({"map": {"id": "ROUTE_9"}},
             {"op": "field_move", "move": "CUT", "x": 5, "y": 8})
ck("the same coordinates on another map are another bush",
   ex._cut_bushes.get("ROUTE_9") == ["5,8"])

ex2 = fake()
ex2._note_cut(OBS, {"op": "field_move", "move": "STRENGTH", "x": 1, "y": 1})
ck("a field move that is not CUT records no bush", ex2._cut_bushes == {})
ex2._note_cut(OBS, {"op": "field_move", "move": "CUT"})
ck("a CUT with no tile records nothing", ex2._cut_bushes == {})
ex2._note_cut({"map": {}}, {"op": "field_move", "move": "CUT", "x": 1, "y": 1})
ck("no map to hang it on records nothing", ex2._cut_bushes == {})
ex2._note_cut(None, {"op": "field_move", "move": "CUT", "x": 1, "y": 1})
ck("no observation at all is not an error", ex2._cut_bushes == {})

# BOTH DISPATCH SITES MUST WRITE IT — that is the whole bug
src = Path("planner/executor.py").read_text()
early = src.find('if _res0.get("ok"):')
late = src.find('if op == "field_move" and r.get("ok"):')
ck("the aimed-field-move handler records before it continues",
   early > 0 and "_note_cut" in src[early:early + 900]
   and src[early:early + 900].index("_note_cut")
   < src[early:early + 900].index("continue"))
ck("the end-of-loop handler records too",
   late > 0 and "_note_cut" in src[late:late + 200])
ck("neither writes the record itself any more",
   src.count("self._cut_bushes.setdefault") == 1)
ck("and the one that does is the shared helper",
   "def _note_cut" in src
   and src.index("def _note_cut") < src.index("self._cut_bushes.setdefault"))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok  " if ok else "  FAIL") + "  " + n)
print(f"\n{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
