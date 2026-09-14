#!/usr/bin/env python3
"""A refusal heard while walking had nobody to be filed under.

Viridian's sleeping old man is the wall across the north exit; he stands
aside only once Oak's parcel is delivered. The sweep, drawn north by unseen
ground, walked into him and came back:

    sweep(until=door): ... stopped: interrupted (battle or script)
      — it said: "You can't go through here! This is private property!"

Three times in nine escalations. The hints ledger files a heard line under
whoever said it, and this line had no speaker attached — a walk names no
object the way an interact does — so Viridian got no hints entry at all,
and his row on the page went on reading

    VIRIDIANCITY_OLD_MAN_SLEEPY (npc at 18,9) — never spoken to

which reads as an opportunity, not a wall (2026-09-13, user: "sweep is
directing it to the old man").

CHECKED BEFORE CHANGING, because two plausible fixes were wrong. Recording
him as a BLOCKER would have changed nothing: the explore picker does not
consult blockers at all — zero references in its whole body — they only
feed a page line. And there was no existing join to extend, because the
line never reached the hints ledger in the first place. What was actually
missing was the speaker's name, and the shim knows it: the player's
position is known at the moment the walk stops and a talker is beside them.

Nothing here says the way is shut for good. It says who spoke and what
they said, which is the run's own record; the old man moves when the
parcel is delivered, and that is the leg the run is already on.
"""
from __future__ import annotations
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

SH = (ROOT / "harness" / "shim.lua").read_text()
EX = (ROOT / "planner" / "executor.py").read_text()

# anchored on the comment, since `if G.stack:top() ~= ow then` appears
# in several ops and the first one is not this
blk = SH.split('-- WHO STOPPED YOU.', 1)[1][:1600]
ck("the interrupt looks for whoever is beside the player",
   "for _, npc in ipairs((ow and ow.npcs) or {}) do" in blk)
ck("...the way they are FACING first",
   '_p.facing == "left"' in blk and "_p.cellX + _dx, _p.cellY + _dy" in blk)
ck("...then the four neighbours",
   "_p.cellX, _p.cellY - 1" in blk and "_p.cellX + 1, _p.cellY" in blk)
ck("the name goes into the reason the op reports",
   '"interrupted (battle or script)"' in blk
   and '(_who and (" by " .. _who) or "")' in blk)
ck("nobody beside you leaves it unnamed rather than guessing",
   "local _p, _who = ow.player, nil" in blk)

ck("the planner takes the name from the shim's own words",
   r'r"interrupted \(battle or script\) by ([A-Z][A-Z0-9_]+)"' in EX
   or "interrupted \\(battle or script\\) by ([A-Z][A-Z0-9_]+)" in EX)
ck("...off the result the op actually returned",
   '((obs or {}).get("result") or {}).get("detail")' in EX)
ck("...and only when the op named nobody itself",
   "if _stopped and not step.get(\"name\"):" in EX)
ck("an op that DID name a thing still files under that",
   'who = step.get("name") or op' in EX)
ck("a sweep that pressed something still files under the presser",
   "who = self._last_press_name      # the sweep's presser" in EX)

# the pattern only matches a real object id
_pat = re.compile(r"interrupted \(battle or script\) by ([A-Z][A-Z0-9_]+)")
ck("the pattern reads a real id out of a real detail",
   (_pat.search("ok (moved, swept 2 step(s)) — stopped: interrupted "
                "(battle or script) by VIRIDIANCITY_OLD_MAN_SLEEPY")
    or [None]) and _pat.search(
        "stopped: interrupted (battle or script) by "
        "VIRIDIANCITY_OLD_MAN_SLEEPY").group(1)
   == "VIRIDIANCITY_OLD_MAN_SLEEPY")
ck("...and finds nothing in the unnamed form, as before",
   _pat.search("stopped: interrupted (battle or script)") is None)

ck("the shim still compiles",
   subprocess.run(["luac", "-p", str(ROOT / "harness" / "shim.lua")]).returncode == 0)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
