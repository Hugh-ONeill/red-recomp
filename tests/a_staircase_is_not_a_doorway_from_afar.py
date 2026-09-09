#!/usr/bin/env python3
"""The block that lists floors with ways never taken says what each way is
DRAWN as, so a staircase read from another floor is not a plain door.

Run 16, 2026-09-08: standing in the Celadon lift, the page said
"CELADON_MART_5F has 3 doorway(s): 2 never taken and on ground you have
stood on (12,1, 16,1) — plain untried doors". (12,1) is the staircase UP to
the roof, where the vending machines are. The model went up, found "no
obvious way to the roof", and concluded the roof must be a floor the
LIFT_KEY unlocks on the lift panel (user: "previously the sweep listed the
two staircases as doorways, maybe thats why it thought there was no obvious
way to the roof from the top floor"). The shim has read the tile under every
warp since the Silph pads (warp_look), and the LOCAL ledger already says
"stairs up (12,1)"; the remote block had no look to read. Now the run
remembers each map's warp drawings and the remote rows carry them.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
from executor import Executor                                  # noqa: E402

ex = (ROOT / "planner" / "executor.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


class _E(Executor):
    def __init__(self):
        self.warp_looks = {}


e = _E()
obs = {"map": {"id": "CELADON_MART_5F", "warps": [
    {"x": 12, "y": 1, "look": "stairs_up", "dest": "CELADON_MART_ROOF"},
    {"x": 16, "y": 1, "look": "stairs_down", "dest": "CELADON_MART_4F"},
    {"x": 1, "y": 1, "look": "lift", "dest": "CELADON_MART_ELEVATOR"},
    {"x": 5, "y": 5, "look": "door", "dest": "SOMEWHERE"}]}}
e._note_warp_looks(obs)
ck("the looks are remembered per map", e.warp_looks.get("CELADON_MART_5F", {}).get("12,1") == "stairs_up")
ck("...a plain door is not stored (it is the default word anyway)", "5,5" not in e.warp_looks.get("CELADON_MART_5F", {}))
ck("a staircase up reads as stairs UP", e._look_word("CELADON_MART_5F", "12,1") == "stairs UP")
ck("a staircase down reads as stairs DOWN", e._look_word("CELADON_MART_5F", "16,1") == "stairs DOWN")
ck("the lift door reads as the lift door", e._look_word("CELADON_MART_5F", "1,1") == "the lift door")
ck("an unknown cell reads as nothing", e._look_word("CELADON_MART_5F", "9,9") == "" and e._look_word("NOWHERE", "1,1") == "")
ck("a list of cells carries each drawing", e._keys_with_looks("CELADON_MART_5F", ["12,1", "16,1", "5,5"]) == "12,1 (stairs UP), 16,1 (stairs DOWN), 5,5")
ck("the remote untaken row carries the looks", 'f"({self._keys_with_looks(_m, _open[:4])}) — "' in ex)
ck("...and no longer calls them plain untried doors", 'f"plain untried doors, {_legs}")' not in ex and 'f"untried, {_legs}")' in ex)
ck("the barred and far rows carry them too", "self._keys_with_looks(_m, _barred[:4])" in ex and "self._keys_with_looks(_m, _far[:4])" in ex)
ck("the looks are noted on every op's observation", "self._note_warp_looks(obs)" in ex)
ck("...and survive a reboot", '"warp_looks": getattr(self, "warp_looks", {}),' in ex and 'self.warp_looks = data.get("warp_looks", {}) or {}' in ex)
sys.exit(1 if fails else 0)
