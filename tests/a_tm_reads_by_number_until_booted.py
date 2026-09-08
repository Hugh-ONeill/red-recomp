#!/usr/bin/env python3
"""A TM reads by its number until booted, unless a person handed it over.

The engine's item ids name the move (TM_RAZOR_WIND); the game's screen says
"RED found TM02!", the bag shows TM02, and the move is shown only when the
machine is booted. A machine a PERSON hands over is different: they name the
move and say what it does, as every HM giver does (user, 2026-09-07). So the
bag line, the gains line and the shop shelves call a TM by its number unless
the executor's gift record holds it; ops accept the number; the shim's boot
reply names the move the way the game does.
"""
import sys, types
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E   # noqa: E402
src = (ROOT / "planner" / "executor.py").read_text()
sh = (ROOT / "harness" / "shim.lua").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ck("the number table is the engine's own", E.MACHINE_NUMBERS.get("TM_RAZOR_WIND") == "TM02" and E.MACHINE_NUMBERS.get("HM_CUT") == "HM01" and len(E.MACHINE_NUMBERS) == 55)
fake = types.SimpleNamespace(_item_from={"TM_BUBBLEBEAM": {"who": "CERULEANGYM_MISTY"}})
ck("a found TM reads by number", E.Executor._disp_item(fake, "TM_RAZOR_WIND") == "TM02")
ck("a gift TM keeps the move a person named", E.Executor._disp_item(fake, "TM_BUBBLEBEAM") == "TM_BUBBLEBEAM")
ck("an HM keeps its id (always handed over)", E.Executor._disp_item(fake, "HM_CUT") == "HM_CUT")
ck("other items are untouched", E.Executor._disp_item(fake, "POTION") == "POTION")
ck("ops accept the number, spaced or not, any case",
   E.canon_item("TM02") == "TM_RAZOR_WIND" and E.canon_item("tm 02") == "TM_RAZOR_WIND" and E.canon_item("POTION") == "POTION" and E.canon_item("TM_RAZOR_WIND") == "TM_RAZOR_WIND")
ck("the bag, the gains and the shelves print through the display rule",
   'f"{self._disp_item(k)} x{v}{self._gift_note(k)}"' in src and 'f"{self._disp_item(k)} {d:+d} (now' in src
   and '", ".join(self._disp_item(x) for x in _it[:10])' in src)
ck("the op runner canonicalises a step's item first", 'step["item"] = canon_item(step["item"])' in src)
ck("the shim's boot reply names the move the way the game does", 'return true, "booted up " .. _nm .. " (" .. c.item .. ") — it contained "' in sh)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:200])
sys.exit(1 if bad else 0)
