#!/usr/bin/env python3
"""A machine in the bag says who in the party its own screen marks ABLE, and
a refusal to teach says it for the whole party at once.

Run 16 (2026-09-08), the Fly leg: the run used HM_FLY on Charizard, then
Eevee, then Nidorina, then Gloom, a round each, to learn that none of them
can take it — a fact the ITEM screen shows for every member the moment the
machine is picked (user: "the usage screen shows ABLE and NOT ABLE for the
whole party"). The shim now exports, for every TM and HM in the bag, the
party members ABLE and NOT ABLE; the page's bag line carries it; the
NOT COMPATIBLE refusal names everyone.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
import executor as E   # noqa: E402

fails = []


def ck(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"\n      {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


ex = E.Executor.__new__(E.Executor)
obs = {"machines": {"HM_FLY": {"move": "FLY", "able": [], "not_able": ["NIDORINA", "GLOOM", "CHARIZARD", "EEVEE"]},
                    "HM_CUT": {"move": "CUT", "able": ["GLOOM", "CHARIZARD"], "not_able": ["NIDORINA", "EEVEE"]}}}
ck("a machine nobody can take says so", ex._able_note("HM_FLY", obs) == " [NOT ABLE: anyone in this party]", ex._able_note("HM_FLY", obs))
ck("a machine some can take names them", ex._able_note("HM_CUT", obs) == " [ABLE: GLOOM, CHARIZARD]", ex._able_note("HM_CUT", obs))
ck("an ordinary item says nothing", ex._able_note("POTION", obs) == "")
ck("no machines in the observation, nothing said", ex._able_note("HM_FLY", {}) == "")

src = (ROOT / "planner" / "executor.py").read_text()
ck("the bag line carries it", '{self._gift_note(k)}{self._able_note(k, obs)}' in src)

sh = (ROOT / "harness" / "shim.lua").read_text()
ck("the shim exports ABLE / NOT ABLE per machine in the bag",
   "o.machines[k] = { move = mv, able = able, not_able = notable }" in sh)
ck("...read off the party and the species' machine list", 'for _, mvn in ipairs((pdef and pdef.tmhm) or {}) do' in sh)
i = sh.index("is NOT COMPATIBLE with")
ck("the refusal shows the whole party screen",
   "The machine's party screen shows ABLE / NOT \"\n          .. \"ABLE for the whole party at once: ABLE — " in sh[i - 200:i + 1200])
ck("...and says when nobody in the party can take it", "Nobody in this party can take it as they stand." in sh[i:i + 1500])
sys.exit(1 if fails else 0)
