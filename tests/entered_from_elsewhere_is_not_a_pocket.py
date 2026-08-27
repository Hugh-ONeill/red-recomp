#!/usr/bin/env python3
"""A region you walked into from a third place is not a pocket, and a
seam whose every tried cell lands in the same part is not tried again.

Route 19's water is entered by surfing off Route 19's own land, so its
one RECORDED way out was west to Route 20. The pocket rule looked only
at ways out, called it a dead end, and every crossing into it was retried
at three more cells of the seam — all landing in the same water. Watched
live 2026-08-27 ("got itself confused and used a lot of conflicting
crosses to go from rt 20 to 19 and back").
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E          # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

def ex_with(explored):
    ex = E.Executor.__new__(E.Executor)
    ex.explored = explored
    return ex

# the real shape from the atlas
atlas = {
    "ROUTE_19|6,0":  {"walk:ROUTE_19|13,0": {"to": "ROUTE_19|13,0", "n": 1, "intra": True},
                      "north": {"to": "FUCHSIA_CITY|0,0", "n": 2}},
    "ROUTE_19|13,0": {"west": {"to": "ROUTE_20|52,2", "n": 5},
                      "west#skip1": {"to": "ROUTE_20|44,2", "n": 3}},
    "ROUTE_20|52,2": {"east": {"to": "ROUTE_19|13,0", "n": 2},
                      "48,5": {"to": "SEAFOAM_ISLANDS_1F|3,2", "n": 1}},
    "ROUTE_20|44,2": {"east": {"to": "ROUTE_19|13,0", "n": 7},
                      "east#skip1": {"to": "ROUTE_19|13,0", "n": 3}},
    # the original pocket: Route 14's nook, entered only from Route 13
    "ROUTE_13|50,0": {"west": {"to": "ROUTE_14|16,6", "n": 3}},
    "ROUTE_14|16,6": {"east": {"to": "ROUTE_13|50,0", "n": 3}},
    "ROUTE_14|5,4":  {"west": {"to": "ROUTE_15|15,4", "n": 1}},
}
ex = ex_with(atlas)
ck("Route 19's water, entered off Route 19's own land, is not a pocket",
   not ex._is_pocket("ROUTE_19|13,0", "ROUTE_20|52,2"))
ck("...from either part of Route 20", not ex._is_pocket("ROUTE_19|13,0", "ROUTE_20|44,2"))
ck("Route 14's nook, entered only from Route 13 and leading only back, IS a pocket",
   ex._is_pocket("ROUTE_14|16,6", "ROUTE_13|50,0"))
ck("a region with no recorded way out is not called a pocket",
   not ex._is_pocket("ROUTE_15|15,4", "ROUTE_14|5,4"))
ck("Route 20's east seam has been tried at another cell and always landed in the same water",
   ex._seam_row_uniform("ROUTE_20", "east"))
ck("Route 19's west seam lands in two parts: not uniform",
   not ex._seam_row_uniform("ROUTE_19", "west"))
ck("a seam never tried at another cell is not called uniform",
   not ex._seam_row_uniform("ROUTE_13", "west"))

src = (ROOT / "planner/executor.py").read_text()
ck("the cross dispatch asks the helpers, not the bare ways-out set",
   "elif self._is_pocket(_lands, _h0):" in src and 'self._seam_row_uniform(_h0.split("|")[0],' in src)
ck("...and says when the other cell landed in the same part anyway",
   "same part anyway" in src)
ck("...and says when every crossed cell of an edge lands in one part",
   "crossed lands in {_lands}" in src)
ck("the uncork declines a region entered from elsewhere",
   '"entered from elsewhere: not a pocket"' in src)
ck("...and a seam already tried at every cell",
   '"every cell of that seam already tried lands here"' in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
