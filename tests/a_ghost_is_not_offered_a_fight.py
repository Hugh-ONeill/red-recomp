#!/usr/bin/env python3
"""A ghost is not offered a fight, and the screen's refusal rides every ghost line.

The Pokemon Tower's ghosts turn every FIGHT into "X is too scared to move!"
The run pressed it — once as the harness's own probe, once as an
{"intent":"fight"} walk at the 6F stairs — and the screen's words were
relayed. Then the stairs note went on saying "a wild GHOST was in the way ...
say intent:fight and it will be fought instead", the flee notes said only
"a wild GHOST appeared, and you fled from it", and the model planned "finish
this battle by fighting" round after round (2026-09-03; user: "it doesnt seem
to get that it cant just fight the ghost").

Now the refusal the run has seen is remembered (ghost_said, persisted) and
put on every line that names a ghost, with whatever anyone in the building
said about ghosts ("The GHOSTs can be identified by the SILPH SCOPE", a
channeler on 3F — heard, not handed over), and a ghost in the way is never
offered intent:fight. What lifts it is not said.

Synthetic: no game, no model.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

e = object.__new__(E.Executor)
e._ghost_said = "PIDGEOTTO is too scared to move!"
e.hints = {"POKEMON_TOWER_3F|2,2": ["POKEMONTOWER3F_CHANNELER1: The GHOSTs can be identified by the SILPH SCOPE."],
           "CERULEAN_CITY|20,0": ["CERULEANCITY_SIGN: a GHOST story unrelated"]}
obs = {"map": {"id": "POKEMON_TOWER_6F"}}
w = e._ghost_words(obs)
ck("the screen's refusal is quoted", 'when FIGHT was pressed the screen said "PIDGEOTTO is too scared to move!"' in w, w)
ck("...and the building's own words about ghosts", "POKEMONTOWER3F_CHANNELER1" in w and "SILPH SCOPE" in w, w)
ck("...but not words from another building", "CERULEANCITY_SIGN" not in w)
ck("...and nothing about where the Scope is", "SILPH_CO" not in w and "Rocket" not in w)
e2 = object.__new__(E.Executor); e2._ghost_said = ""; e2.hints = {}
ck("with nothing seen or heard, nothing is added", e2._ghost_words(obs) == "")
e3 = object.__new__(E.Executor)
ck("an executor from before the ledger existed does not die of it", e3._ghost_words(obs) == "")

src = (ROOT / "planner" / "executor.py").read_text()
ck("a ghost in the way is not offered intent:fight",
   'if ghosted or str(wild_in_way).upper() == "GHOST":' in src
   and 'a GHOST was in the way, it was FLED and "\n                             "the way stayed shut" + _gw)' in src)
ck("...while a real wild in the way still is",
   'f"{{\\"op\\":\\"{op}\\",...,\\"intent\\":\\"fight\\"}} "' in src)
ck("the flee notes carry the words, once per note",
   "_w2 = self._ghost_words(obs)" in src and '_w2 = "" if (_w2 and _w2 == _gw) else _w2' in src)
ck("the refusal is remembered from whichever op met it",
   'if "too scared to move" in _dtxt and "the screen says: " in _dtxt:' in src
   and "self._ghost_said = said[:120]" in src)
ck("...and persisted", '"ghost_said": getattr(self, "_ghost_said", "")' in src
   and 'self._ghost_said = data.get("ghost_said", "") or ""' in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
sys.exit(1 if bad else 0)
