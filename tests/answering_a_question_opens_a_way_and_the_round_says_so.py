#!/usr/bin/env python3
"""A right answer opens a door, and the round has to name it.

Pressing a Mansion statue earns "AND THAT OPENED A WAY: (25,14) can now be
walked to from where you stand; it could not before".  That sentence is
built by diffing every warp's reachable flag between the observation
BEFORE the op and the one after, and it needs both on the same map.

An observation taken with a question box up reads map.id None.  Cinnabar's
gym quiz is answered with a menu op while exactly that box is open, so the
before-view had no map, the diff could not run, and the round said nothing
about the door the right answer had just opened.  The run guessed (17,17),
which is the gym's exit, and warped itself back out onto the island
(2026-09-10, user: "something shunted it out").

The fix is the last view that DID have a map, kept from the top of the op
loop.  Source-anchored, because the sentence lives inside the op runner.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "planner" / "executor.py").read_text()

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ck("the op loop remembers the last view that had a map",
   "self._last_mapped_obs = pre_obs" in SRC
   and '_pre_mapped = getattr(self, "_last_mapped_obs", None) or pre_obs' in SRC)

blk = SRC.split("A THING TAKEN OUT OF A CORRIDOR OPENS IT", 1)[1][:2200]
ck("the opened-a-way diff still prefers the op's own before-view",
   '_pm = ((pre_obs or {}).get("map") or {})' in blk)
ck("...and falls back to the last mapped one when there is no map",
   'if not _pm.get("id"):' in blk
   and '_pm = ((_pre_mapped or {}).get("map") or {})' in blk)
ck("...and still refuses to diff across two different maps",
   '_pm.get("id") == _nm.get("id")' in blk)
ck("...and still says which way opened",
   "AND THAT OPENED A WAY" in blk and "could not before" in blk)

# the remembering happens BEFORE the op runs, or it would hold the after-view
_i_keep = SRC.index("self._last_mapped_obs = pre_obs")
_i_send = SRC.index("before = self._snapshot(obs)")
ck("the last mapped view is kept before the op is sent", _i_keep < _i_send)

# and a mapless before-view is what it is for
ck("the reason is written where the next reader will look",
   "question box up" in SRC and "map.id None" in SRC)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
