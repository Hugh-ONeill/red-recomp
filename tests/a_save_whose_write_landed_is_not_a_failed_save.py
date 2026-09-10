#!/usr/bin/env python3
"""The save file is the ground truth, so the watcher asks it.

The shim reports two kinds of save trouble.  "a box was up and would not
close: text: RED saved the game!" quotes the save's OWN confirmation, and
that one has been demoted since 2026-09-09.  "save file never changed
(top=overworld)" is decided by a poll that can end before the 120-frame
"Now saving..." hold reaches its write: run 16's 14:07 pair had the file
written at 14:07:13 and the op saying never-changed at 14:07:15, two
seconds after its own write.

The shim was fixed for that on 2026-09-10, but a shim fix lands at the
next game BOOT and the run had hours left in the process it was in.  The
file settles it either way, so this asks the file.

A save that really did not happen still reports at warn, because the
ratchet save is what a dead game boots from.  Synthetic: no game.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import notable                                         # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))


class _F:
    def __init__(self, mtime): self._m = mtime
    def stat(self): return type("S", (), {"st_mtime": self._m})()


def sev_of(detail, wrote_at, now):
    _files = [_F(wrote_at)] if wrote_at else []
    notable.SAVE_FILES = lambda: _files
    w = notable.Watcher({})
    w.record({"kind": "subgoal_save_failed", "subgoal": "reach_mansion_3f",
              "detail": detail, "t": now})
    return [(o["sev"], o["kind"], o["what"]) for o in w.out]


NOW = time.time()
NEVER = "save file never changed (top=overworld)"
BOX = "not in overworld (a box was up and would not close: text: RED saved the game!)"

out = sev_of(NEVER, NOW - 2, NOW)
ck("a write two seconds late is not a failure", out and out[0][0] == "info", out)
ck("...and it is still reported, in the shim's own words",
   out and out[0][1] == "save_failed" and NEVER in out[0][2], out)

ck("a write half a minute either side still counts",
   sev_of(NEVER, NOW + 25, NOW)[0][0] == "info")
ck("a save file that has not moved in an hour is a real failure",
   sev_of(NEVER, NOW - 3600, NOW)[0][0] == "warn")
ck("...and so is one with no save file at all",
   sev_of(NEVER, None, NOW)[0][0] == "warn")

ck("the box that quotes the save's own confirmation stays demoted",
   sev_of(BOX, NOW - 3600, NOW)[0][0] == "info")

# a detail we have never seen before is not quietly excused by the clock
ck("an unrecognised save failure is not excused by a recent write",
   sev_of("the menu never opened", NOW - 1, NOW)[0][0] == "warn")

# the real reader survives a directory that is not there
import importlib                                       # noqa: E402
importlib.reload(notable)
notable._SAVE_DIR = Path("/nonexistent/nowhere/saves")
ck("a missing save directory reads as empty, not as an exception",
   notable.SAVE_FILES() == [])

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d) + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
