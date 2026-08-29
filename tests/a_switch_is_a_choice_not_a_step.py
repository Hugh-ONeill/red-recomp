#!/usr/bin/env python3
"""A press by coordinates is a press of the thing on that cell; explore
never presses a switch statue on its own; a door's switch settings are
per part of the floor and never stamped from a seen-ground downgrade.

Mansion 2F, 2026-08-28: the model pressed the switch as interact(x=2,y=11),
the touch was filed under no name, the ledger kept calling
SWITCH_POKEMON_MANSION_2F_2_11 "never pressed", and explore pressed it
again "first" — toggling the walls back every time the model set them.
The stairs at (6,1) then read "unreachable, looked at only PRESSED".
The "no walk reached it in this setting" stamp also fired on doorways the
footprint had merely not seen a path to, pooled per map.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E          # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
obs = {"map": {"id": "POKEMON_MANSION_2F", "region": "10,1",
               "objects": [{"name": "SWITCH_POKEMON_MANSION_2F_2_11", "kind": "fixture", "x": 2, "y": 11},
                           {"name": "POKEMONMANSION2F_SUPER_NERD", "kind": "npc", "x": 3, "y": 17}]}}
ck("the thing on a cell is named", E.Executor._name_at(obs, 2, 11) == "SWITCH_POKEMON_MANSION_2F_2_11")
ck("...and an empty cell is not", E.Executor._name_at(obs, 5, 5) is None)
ck("...and bad coordinates are not an error", E.Executor._name_at(obs, "x", None) is None)
src = (ROOT / "planner/executor.py").read_text()
i = src.index('if op == "interact":')
blk = src[i:i + 1400]
ck("an interact by coordinates is filed under the thing's name",
   "_nm_xy = self._name_at(obs, step.get(\"x\"), step.get(\"y\"))" in blk and "step = dict(step, name=_nm_xy)" in blk)
ck("...and the journal says so", 'self.log("touch_by_coords"' in blk)
j = src.index("things = sorted((c for c in cands")
ck("explore never presses a switch statue first", '"SWITCH" not in str(c.key).upper()' in src[j:j + 2400])
k = src.index("_ss = self.shut_settings.setdefault(here, {})")
ck("shut settings are keyed by region", k > 0 and "_rs = self.reach_settings.setdefault(here, {})" in src)
ck("...and never stamped from a seen-ground downgrade", '"you have seen" in str(_w.get("why") or "")' in src[k:k + 500])
led = (ROOT / "planner/ledger.py").read_text()
ck("the ledger reads the region entry first, then the old map entry",
   "(_ss_all.get(here) or {}).get(c.key)" in led and "(_rs.get(_here) or {}).get(str(name))" in led)
# the name lookup reads only names that exist in that scope (an UnboundLocalError on
# pre_obs killed every attempt of leg 40 at its first coordinate press, 2026-08-28)
import ast
tree = ast.parse(src)
fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_run_traced")
assigned = {t.id for n in ast.walk(fn) for t in getattr(n, "targets", []) if isinstance(t, ast.Name)}
assigned |= {a.arg for a in fn.args.args}
used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
ck("_run_traced does not read a pre_obs it never binds", "pre_obs" not in used or "pre_obs" in assigned)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
