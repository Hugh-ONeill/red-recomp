#!/usr/bin/env python3
"""sweep(until=X): a synonym folds to its kind, and a word that names no
kind is said in the result rather than silently meaning "nothing".

The observation lists a floor's doorways under map.warps, so
{"op":"sweep","until":"warp"} is the model asking, in the page's own
word, to stop at a doorway. The sweep keyed `wants` by the raw string and
tested wants[t.kind] against what came into view (door, person, item,
sign, hole, way), so "warp" matched nothing and the sweep stopped for
nothing: 165 steps past six doorways, 935 cells newly on screen, ended by
a wild battle beside Cerulean's south seam (2026-09-14, user: "whats would
make it stop exactly? ... it passed plenty of doors"). A whole-floor sweep
is a fine thing to ask for -- it is what "map_change" does -- but it is a
different op from the one asked for, and the model was not told.

Now: synonyms fold ("warp", "doorway", "exit" -> door; "people", "npc" ->
person; "nothing", "none", "all" -> map_change), an unknown word is
reported in the result, and the vocabulary says what "map_change" really
is: the whole floor from all ground you can reach, in one round.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "harness" / "shim.lua").read_text()
ex = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

i0 = sh.index("function OPS.sweep(G, c)")
body = sh[i0:sh.index("\nfunction ", i0 + 10)]          # the whole of OPS.sweep
ck("the sweep folds synonyms before matching", "UNTIL_ALIAS" in body and "wants = folded" in body)
alias = body.split("local UNTIL_ALIAS = {", 1)[1].split("}", 1)[0]
ck('"warp" means door', re.search(r'\bwarp = "door"', alias))
ck('...and so do "warps", "doorway", "exit"',
   all(re.search(rf'\b{w} = "door"', alias) for w in ("warps", "doorway", "doorways", "exit")))
ck('"people" and "npc" mean person', re.search(r'\bpeople = "person"', alias) and re.search(r'\bnpc = "person"', alias))
ck('"nothing", "none", "all" mean map_change: stop for nothing but the map changing',
   all(re.search(rf'\b{w} = "map_change"', alias) for w in ("nothing", "none", "all")))
known = body.split("local UNTIL_KNOWN = {", 1)[1].split("}", 1)[0]
ck("the known kinds are the ones the sweep can produce",
   all(f"{k} = true" in known for k in ("door", "person", "trainer", "item", "sign", "hole", "way", "map_change")))
ck("an unknown word is collected, not dropped", "until_unknown[#until_unknown + 1] = k" in body)
ck("...and said in the result, with the words that would have worked",
   "names nothing that comes into " in body
   and "view (door, person, item, sign, hole; or map_change" in body
   and "so this sweep stopped for nothing" in body)
ck("the note is written into the same detail the trace carries",
   body.index("detail = detail .. (\" -- NOTE: until=") > body.index("local detail = (\"swept %d step(s)"))
ck("the fold happens before the default is chosen",
   body.index("wants = folded") < body.index("if next(wants) == nil then wants.anything_new = true end"))

ck("the vocabulary keeps its kinds", '"until":"door"|"person"|"item"|"sign"|"hole"|"map_change"' in ex)
ck('...says "warp" is taken as "door"', '"warp" is taken as "door"' in ex)
ck('...and says what "map_change" really is: the whole floor in one round',
   # reworded 2026-09-14, when the sweep began saying it cannot change the
   # map by walking at all (it skips every warp tile)
   "A SWEEP NEVER STEPS ONTO A DOORWAY, so it cannot change the map by" in ex
   and "this floor seen out to every cell a walk reaches, in ONE" in ex)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
