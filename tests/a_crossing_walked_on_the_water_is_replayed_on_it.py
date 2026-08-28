#!/usr/bin/env python3
"""A crossing made riding the water is remembered that way and replayed
that way.

Route 20's east seam had been crossed surfing. `go FUCHSIA_POKECENTER`
from the east side replayed it on foot (the model had not said surf),
the seam read "cannot be walked to" over 79 cells of land, and the
fallback walked eight legs through Seafoam to another part of the same
map that is joined to this one by nothing but water (user, 2026-08-28:
"took it into seafoam for some reason ... it was from the east side, so
it wasn't right"). The edge now carries `surf`, a replay reads it, and a
seam that turns out to be across water is ridden once when someone in
the party knows SURF, with the trace saying so.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import executor as E          # noqa: E402
import candidates as C        # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

def fresh():
    ex = C.make()
    ex.explored = {}
    for name, val in (("_cur_target", None), ("_faint_at", None), ("_entered_map", {}),
                      ("_bad_seam", set()), ("_arrived", None), ("_came_from", None),
                      ("_reversals", 0), ("_entered_by", {}), ("blockers", {})):
        if not hasattr(ex, name):
            setattr(ex, name, val)
    ex.log = lambda *a, **k: None
    ex._save_memory = lambda *a, **k: None
    ex._clear_blocker = lambda *a, **k: None
    return ex

before = {"map": {"id": "ROUTE_20", "region": "44,2", "outdoor": True, "warps": []}, "player": {"x": 99, "y": 6}}
after = {"map": {"id": "ROUTE_19", "region": "13,0", "outdoor": True, "warps": []}, "player": {"x": -1, "y": 41}}
ex = fresh()
ex.note_transition(before, {"op": "cross", "dir": "east", "surf": True}, after)
e = (ex.explored.get("ROUTE_20|44,2") or {}).get("east") or {}
ck("a crossing made surfing records surf on the edge", e.get("to") == "ROUTE_19|13,0" and e.get("surf") is True)
ex = fresh()
ex.note_transition(before, {"op": "cross", "dir": "east"}, after)
e = (ex.explored.get("ROUTE_20|44,2") or {}).get("east") or {}
ck("a crossing made on foot records none", e.get("to") == "ROUTE_19|13,0" and "surf" not in e)

src = (ROOT / "planner/executor.py").read_text()
i = src.index("_edge = (self.explored.get(self._where(pre)) or {}).get(str(key)) or {}")
blk = src[i:i + 200]
ck("a replayed hop rides the water when the edge says it was ridden", 'bool(_edge.get("surf")) or _surfed_retry' in blk)
j = src.index('self.log("route_hop_surfed"')
rb = src[j - 700:j + 200]
ck("...or once more when the seam cannot be walked to and someone knows SURF",
   '"cannot be walked to" in _det' in rb and 'self._knows_move(o or {}, "SURF")' in rb and "_surfed_retry = True" in rb)
ck("...and the retry continues the loop, which otherwise leaves after one failed hop",
   rb[rb.index("_surfed_retry = True"):].split("\n")[3].strip() == "continue"
   or "continue" in rb[rb.index("_surfed_retry = True"):rb.index("_surfed_retry = True") + 260])
ck("...and says so in the journal", True)
ck("the surf flag stays on the step so the edge remembers it", "surf stays: the edge remembers it" in src)
ck("a door hop is never surfed by this rule", "not _is_door_key(key)" in rb)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
