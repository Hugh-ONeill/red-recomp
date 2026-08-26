"""Nothing quotes the printed map unless it is in the bag (2026-08-26).

TOWN_MAP is an item in this game (Daisy, in Blue's house). Every printed-map
channel is gated on holding it — _atlas_text falls back to walked
destinations, the whole-map adjacency block is withheld, author.py withholds
its two blocks, the itinerary line says "Your own walking" — and _far_note
was missed. This save carries no TOWN_MAP and was reading "the printed map
draws no road between ROUTE_7 and FUCHSIA_CITY" every round (user: "what
language concerning an atlas does it get without the town map?").

The NUMBER was already honest: static_cost gates MAP_EDGES behind
PRINTED_MAP_HELD, so with no map it counts only links this run walked. It was
the sentence that credited an artifact the player does not own."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()

# --- the gate itself ---
ck("holding the map is read from the bag",
   '"TOWN_MAP" in ((obs or {}).get("bag") or {})' in src)
ck("the hop count already gates the printed adjacency",
   "if PRINTED_MAP_HELD else set()" in src)

# --- _far_note now asks ---
i = src.find("AND THE MAP MUST BE IN THE BAG BEFORE IT CAN BE QUOTED")
ck("the distance line asks whether the map is held", i > 0)
blk = src[i:i + 3400]
ck("...before saying 'on the printed map'",
   '"on the printed map " if _held' in blk)
ck("...and says whose knowledge it is otherwise",
   "by your own walking, and by nothing else" in blk
   and "carry no TOWN MAP" in blk)
ck("the no-route case is gated too",
   'so it cannot say " if _held else' in blk.replace("\n", " ")
   or ('if _held else' in blk and "nothing you have walked joins" in blk))
ck("...and it does not invent a distance either way",
   "there is no distance to give" in blk)

# --- every printed-map phrase in a MODEL-FACING string is gated ---
# via ast so DOCSTRINGS (which quote the old bad wording on purpose) and
# comments are excluded; only strings the code can actually emit count
import ast as _ast
tree = _ast.parse(src)
_doc = set()
for node in _ast.walk(tree):
    if isinstance(node, (_ast.Module, _ast.FunctionDef, _ast.AsyncFunctionDef,
                         _ast.ClassDef)) and node.body:
        first = node.body[0]
        if (isinstance(first, _ast.Expr)
                and isinstance(first.value, _ast.Constant)
                and isinstance(first.value.value, str)):
            _doc.add(id(first.value))
lines = src.splitlines()
ungated = []
for node in _ast.walk(tree):
    if not (isinstance(node, _ast.Constant) and isinstance(node.value, str)):
        continue
    if id(node) in _doc or "printed map" not in node.value:
        continue
    # a COUNTERFACTUAL mention leaks no layout: "crossing any other way is
    # not something this map can do, however the printed map is laid out",
    # "anywhere else is refused, however near it is on the printed map".
    # Those name the artifact only to say it does not decide anything.
    if "however" in node.value.lower():
        continue
    ln = node.lineno
    window = "\n".join(lines[max(0, ln - 40):ln + 2])
    if "_holding_town_map" not in window and "_held" not in window:
        ungated.append((ln, node.value[:60]))
ck(f"no ungated 'printed map' sentence remains ({ungated[:2]})", not ungated)

ck("the other channels are still gated",
   src.count("_holding_town_map") >= 7)

import ast
try:
    ast.parse(src); ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
