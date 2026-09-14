#!/usr/bin/env python3
"""A leg baseline the chain took while the game was down is retaken by the
executor on its first observation, and an empty one is said, not silent.

The chain snaps run/leg_start.json the moment a leg begins, from the last
observation on disk. After a replay there is none (replay_from clears
obs.json and last_state.json), so the snapshot was `{}`, every diff
against it printed nothing, and check-done never heard that
EVENT_TRADED_SPEAROW_FOR_FARFETCHD had fired: it fell through to its
place guard and refused a completed trade leg (2026-09-14).
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import executor as E                                      # noqa: E402
from pinned_world import pinned                           # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

OBS = {"mode": "overworld", "map": {"id": "VERMILION_CITY", "region": "1,1"},
       "flags": ["EVENT_GOT_STARTER", "EVENT_BEAT_BROCK"], "bag": {"POKE_BALL": 4},
       "badges": ["BOULDERBADGE"], "party": [{"species": "CHARMELEON", "level": 29}]}

with pinned(obs=OBS):
    Path("run/leg_start.json").write_text("{}")
    ck("an empty baseline is retaken from the observation", E._backfill_leg_baseline() is True)
    got = json.loads(Path("run/leg_start.json").read_text())
    ck("...and holds the flags, bag, badges and party as they stand",
       got.get("flags") == ["EVENT_BEAT_BROCK", "EVENT_GOT_STARTER"] and got.get("bag") == {"POKE_BALL": 4}
       and got.get("badges") == ["BOULDERBADGE"] and got.get("party") == [["CHARMELEON", 29]], got)
    Path("run/leg_start.json").unlink()
    ck("a missing baseline is taken too", E._backfill_leg_baseline() is True and Path("run/leg_start.json").exists())
    real = {"flags": ["EVENT_GOT_STARTER"], "bag": {}, "badges": [], "party": [["CHARMANDER", 5]], "map": "PALLET_TOWN", "areas": [], "seen": {}}
    Path("run/leg_start.json").write_text(json.dumps(real))
    ck("a real baseline is left exactly as the chain took it",
       E._backfill_leg_baseline() is False and json.loads(Path("run/leg_start.json").read_text()) == real)
    # the diff against an empty baseline says so
    Path("run/leg_start.json").write_text("{}")
    out = subprocess.run([sys.executable, str(ROOT / "planner" / "leg_delta.py"), "diff", "run/leg_start.json"],
                         capture_output=True, text=True)
    ck("diff against an empty baseline says the baseline was not taken",
       "no baseline was taken when this leg began" in out.stdout and out.returncode == 0, out.stdout + out.stderr)
    # and against a real one it still reports the gains
    Path("run/leg_start.json").write_text(json.dumps(real))
    out = subprocess.run([sys.executable, str(ROOT / "planner" / "leg_delta.py"), "diff", "run/leg_start.json"],
                         capture_output=True, text=True)
    ck("...while a real baseline still yields the gains",
       "events that fired: EVENT_BEAT_BROCK" in out.stdout and "badges earned: BOULDERBADGE" in out.stdout, out.stdout)

src = (ROOT / "planner" / "executor.py").read_text()
i_seed = src.index("    ex.seed_regions()          # the bridge is up")
i_fill = src.index("    _backfill_leg_baseline()")
ck("the executor retakes it right after the bridge is up, before any plan runs",
   i_seed < i_fill < src.index("for plan_path in args.plans:", i_seed))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
