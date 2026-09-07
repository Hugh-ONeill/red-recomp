#!/usr/bin/env python3
"""A guessed flag in a named series is answered with every member, grouped
by the place its trainers stand in.

"Defeat all trainers on the S.S. Anne" (run 16, 2026-09-07) was authored
with four floor subgoals whose done_when flags were ALL of the
EVENT_BEAT_SS_ANNE_10_TRAINER_* series — the B1F cabins — because the hint
for the placeholder EVENT_BEAT_SS_ANNE_N_TRAINER_N listed the first six of
sixteen ids in sort order ("10" sorts before "5") and said "(and more)".
Every member is now printed verbatim, grouped by the map its trainers are
on, with how many of each group are already beaten.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok): checks.append((n, bool(ok)))

mem = [f"EVENT_BEAT_SS_ANNE_{s}_TRAINER_{i}" for s, n in ((10, 6), (5, 2), (8, 4), (9, 4)) for i in range(n)]
fired = {"EVENT_BEAT_SS_ANNE_10_TRAINER_3", "EVENT_BEAT_SS_ANNE_5_TRAINER_0", "EVENT_BEAT_SS_ANNE_5_TRAINER_1",
         "EVENT_BEAT_SS_ANNE_8_TRAINER_1", "EVENT_BEAT_SS_ANNE_8_TRAINER_2", "EVENT_BEAT_SS_ANNE_8_TRAINER_3"}
h = A._series_hint(mem, fired)
ck("every member is printed verbatim", all(m in h for m in mem))
ck("the count and the groups are said", "16 events" in h and "4 group(s)" in h)
ck("each group is tied to its place",
   all(w in h for w in ("SS_ANNE_B1F_ROOMS", "SS_ANNE_BOW", "SS_ANNE_1F_ROOMS", "SS_ANNE_2F_ROOMS")))
ck("what is already beaten is said per group",
   "the 2 trainer(s) of SS_ANNE_BOW (all already beaten)" in h
   and "the 4 trainer(s) of SS_ANNE_1F_ROOMS (3 of them already beaten)" in h
   and "the 6 trainer(s) of SS_ANNE_B1F_ROOMS (1 of them already beaten)" in h)
ck("...and no group is cut off", "(and more)" not in h)
ck("a single member keeps the 'ONLY event' wording",
   "ONLY event of that series" in A._series_hint(["EVENT_BEAT_ROUTE_4_TRAINER_0"]))
ck("a short single series keeps the plain list",
   A._series_hint(["EVENT_BEAT_ROUTE_3_TRAINER_0", "EVENT_BEAT_ROUTE_3_TRAINER_1"]).startswith(
       " Did you mean one of EVENT_BEAT_ROUTE_3_TRAINER_0, EVENT_BEAT_ROUTE_3_TRAINER_1?"))
ck("the table covers the engine's trainer events and only real maps",
   len(A.TRAINER_EVENT_MAP) >= 300 and set(A.TRAINER_EVENT_MAP.values()) <= set(A.ENGINE_MAPS))
ck("the validator uses the helper with the flags fired so far",
   "_hint = _series_hint(" in (ROOT / "planner" / "author.py").read_text())

# the matcher itself, on the guess that got no list at all
import re as _re
def members(v):
    segs = v.split("_")
    blank = [j for j, x in enumerate(segs) if len(x) == 1 and x.isalpha()]
    pat = _re.compile("^" + "_".join(r"[A-Z0-9]+" if j in blank else _re.escape(x) for j, x in enumerate(segs)) + "$")
    mem = sorted(f for f in A.ENGINE_FLAGS if pat.match(f) and f != v)
    if blank and not mem:
        pat2 = _re.compile("^" + "_".join(r"[A-Z0-9]+" if (j in blank or x.isdigit()) else _re.escape(x) for j, x in enumerate(segs)) + "$")
        mem = sorted(f for f in A.ENGINE_FLAGS if pat2.match(f) and f != v)
    return mem
ck("a blank beside an impossible number still yields the named series",
   len(members("EVENT_BEAT_SS_ANNE_N_TRAINER_14")) == 16
   and all("SS_ANNE" in m for m in members("EVENT_BEAT_SS_ANNE_N_TRAINER_14")))
ck("a number alone is never a blank (Route 4 stays Route 4)",
   all("ROUTE_4_" in m for m in members("EVENT_BEAT_ROUTE_4_TRAINER_N")))
src = (ROOT / "planner" / "author.py").read_text()
ck("the validator carries that fallback",
   'r"[A-Z0-9]+" if (j in _blank or x.isdigit())' in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
