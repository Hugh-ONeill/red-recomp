"""The meter reads clock time beside rounds: per run, per leg, per stage.

Rounds are the meter's unit and they hide the clock: a round that waits on
a 31B model to author is not a round that presses A.  Every journal row
carries dt, seconds since ITS executor booted, and a boot is an attempt --
so an attempt's span is its largest dt and a leg's executing time is the
sum over its attempts.  Rows written since 2026-09-07 also carry t, the
wall clock, which closes the gaps between attempts (the authoring, the
re-authoring, the ladder).  Older journals have only dt and the meter says
so (user, 2026-09-07: "maybe we should track clock time as well while were
at it").
"""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import arc

def row(kind, dt, t=None, **kw):
    r = {"dt": dt, "kind": kind, **kw}
    if t is not None:
        r["t"] = t
    return json.dumps(r) + "\n"

tmp = Path(tempfile.mkdtemp(dir="/tmp/claude-1000/-home-wiz/"
                            "b5fe8565-91da-4233-b62f-8b773e98e750/scratchpad"))
mem1 = "\nWHERE YOU STAND: PALLET_TOWN|10,0 — this map"
mem2 = "\nWHERE YOU STAND: MT_MOON_1F|3,5 — indoors"

# two attempts with the wall clock: 100s and 60s inside, 40s of authoring between
j = tmp / "executor_log.jsonl"
j.write_text(
    row("plan_start", 0.0, 1000.0, goal="Obtain a starter Pokemon")
    + row("escalate_context", 10.0, 1010.0, memory=mem1)
    + row("escalate_context", 100.0, 1100.0, memory=mem1)
    + row("plan_start", 0.0, 1140.0, goal="Reach Pewter City")
    + row("escalate_context", 20.0, 1160.0, memory=mem1)
    + row("escalate_context", 60.0, 1200.0, memory=mem2)
)
r = arc.scan(str(j))
ck("an attempt's span is its largest dt", r["exec_by_leg"] == [100.0, 60.0])
ck("the second start is charged the authoring gap before it",
   r["wall_by_leg"] == [100.0, 100.0])
ck("the run's clock is first row to last", r["wall_total"] == 200.0)
ck("time between rows goes to where the party stood at the earlier one",
   abs(r["stage_secs"].get("OPENING", 0) - 150.0) < 1e-6
   and "MT_MOON" not in r["stage_secs"])
ck("the journal is known to carry the wall clock", r["has_t"])

# an older journal: dt only
j2 = tmp / "executor_log.old.jsonl"
j2.write_text(row("plan_start", 0.0, goal="A") + row("escalate_context", 30.0, memory=mem1)
              + row("plan_start", 0.0, goal="B") + row("escalate_context", 45.5, memory=mem1))
r2 = arc.scan(str(j2))
ck("without the wall clock, the attempts' spans are still summed",
   r2["exec_by_leg"] == [30.0, 45.5] and abs(r2["exec_total"] - 75.5) < 1e-6)
ck("...and the run's wall clock is unknown, not zero", r2["wall_total"] is None
   and not r2["has_t"])
ck("hms reads", arc.hms(75.5) == "1m15s" and arc.hms(3725) == "1h02m"
   and arc.hms(None) == "--")

src = Path("planner/executor.py").read_text()
ck("the executor stamps the wall clock on every row",
   '"t": round(time.time(), 1), "kind": kind' in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
