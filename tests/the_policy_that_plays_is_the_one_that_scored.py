#!/usr/bin/env python3
"""The battle policy that plays is the one that SCORED best, not the one
whose filename sorts last.

fresh_run.sh picked the active spec with `ls plans/policy_model_v*.json |
sort -V | tail -1`. That is a version number, which is when a file was
written, not whether it won anything. So run 16 fought its entire game on
v6 — "Gen1_Aggressive_Sustain", whose own provenance records three gauntlet
trials that cleared ZERO rooms and blacked out three times out of three —
while v1 (6/6 on the level-five rival, three badges, no blackouts) and v3
(eight Elite Four rooms, no blackouts) sat in the same directory. The
score that should have chosen was written into every file at the moment it
was judged, and nothing ever read it (2026-09-12).

AND THE TWO ARENAS ARE NOT ONE SCALE. `rooms` exists only for the Elite
Four gauntlet and `badge`/`rival_wins` only for the Brock arena, so a
single ranking hands every gauntlet spec a win by default. They are ranked
apart and the STAGE chooses, which is the same reason the specs read the
way they do: v1 heals with POTION and cures with ANTIDOTE, which a Kanto
mart stocks, and v6 reaches for HYPER_POTION and MAX_REVIVE, which no
early party has ever seen.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import pick_policy as P                                    # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))


def spec(tmp, name, **ev):
    p = tmp / f"policy_model_{name}.json"
    p.write_text(json.dumps({"name": name, "provenance": {"eval": ev}}))
    return p


import tempfile                                            # noqa: E402
tmp = Path(tempfile.mkdtemp())
# run 16's own six, by their real recorded scores
v1 = spec(tmp, "v1", rival_wins=6, rival_trials=6, badge=3, pewter=3,
          blackouts=0, dmg_gap=122.0)
v2 = spec(tmp, "v2", rooms=1, gauntlet_trials=3, blackouts=0, dmg_gap=0.0)
v3 = spec(tmp, "v3", rooms=8, gauntlet_trials=3, blackouts=0, dmg_gap=307.0)
v4 = spec(tmp, "v4", rooms=0, gauntlet_trials=3, blackouts=3)
v5 = spec(tmp, "v5", rooms=1, gauntlet_trials=3, blackouts=3)
v6 = spec(tmp, "v6", rooms=0, gauntlet_trials=3, blackouts=3)
ALL = [v1, v2, v3, v4, v5, v6]

win, rows = P.rank(ALL)
ck("the newest file does not win for being newest", win != v6)
ck("the one that blacked out in every trial is refused outright",
   all(not ok for p, _, ok, _, _ in rows if p in (v4, v5, v6)))
ck("...and says so in its own terms",
   any("blacked out in all 3" in why for p, _, _, why, _ in rows if p == v6))
ck("the best gauntlet result wins when no stage is asked", win == v3)

# the arena split
ck("a spec that fought the rival is a Brock spec",
   P.arena_of({"rival_trials": 6, "badge": 3}) == "brock")
ck("a spec measured in rooms is a gauntlet spec",
   P.arena_of({"rooms": 8}) == "e4")
ck("a recorded arena beats any inference",
   P.arena_of({"rooms": 8, "arena": "brock"}) == "brock")

# the stage
for b in (0, 3, 7):
    ck(f"{b} badges gets the Kanto-scored spec", P.rank(ALL, badges=b)[0] == v1)
ck("eight badges gets the gauntlet-scored spec",
   P.rank(ALL, badges=8)[0] == v3)
ck("a stage with no spec of its own falls back to the best sound one",
   P.rank([v3, v4], badges=0)[0] == v3)
ck("nothing sound at all picks nothing rather than something broken",
   P.rank([v4, v5, v6])[0] is None)

# the wiring
FR = (ROOT / "fresh_run.sh").read_text()
# the CODE, not the comment that records what the code used to do — the
# incident report above is allowed to quote the bug it describes
FR_CODE = "\n".join(l for l in FR.splitlines()
                    if not l.lstrip().startswith("#"))
ck("fresh_run no longer picks by filename order",
   "sort -V | tail -1" not in FR_CODE)
ck("...it asks pick_policy, with the badges the run holds",
   "pick_policy.py" in FR and '--badges "$_badges"' in FR)
ck("...and the ranking goes to the log beside the pick", "--why" in FR)
ck("RED_POLICY still overrides everything", 'RED_POLICY:-' in FR)
ck("fresh_run.sh is still valid shell",
   subprocess.run(["bash", "-n", str(ROOT / "fresh_run.sh")]).returncode == 0)

PA = (ROOT / "planner" / "policy_author.py").read_text()
ck("a spec written from now on records the arena that judged it",
   "dict(best_r, arena=gym.arena," in PA)
# A SCORE IS UNREADABLE WITHOUT THE PARTY THAT PRODUCED IT. v3's eight
# rooms with no healing rules at all read as a finding about the spec
# until you see the CHARIZARD L71 that swept them against a league topping
# out in the low sixties (user, 2026-09-12: "we must have given it
# overlevelled mons if it was able to solve it without item usage").
ck("...and the party it was scored against",
   "arena_party=getattr(gym" in PA and "self.arena_party = list(party)" in PA)
ck("the ranking prints that party when the file has it",
   "scored on: " in (ROOT / "planner" / "pick_policy.py").read_text())

# ...and on the real files, which is the case that bit
real = list((ROOT / "plans").glob("policy_model_v*.json"))
if real:
    rwin, _ = P.rank(real, badges=8)
    ck("on the real files, the league pick is not the blacked-out one",
       rwin and rwin.name != "policy_model_v6.json")
    ck("...and an early run gets the spec whose items a Kanto mart sells",
       (P.rank(real, badges=0)[0] or Path("x")).name == "policy_model_v1.json")

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
