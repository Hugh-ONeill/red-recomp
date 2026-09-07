"""Every completed leg leaves a checkpoint, every attempt names its harness,
and a checkpoint can be replayed on the harness as it stands now.

Fixes land at the next boot, so one run's journal is several harnesses in
a row, and a run measured whole says nothing clean about any one of them
(user, 2026-09-07: "is there a way to reset its progress at boundaries so
we can get clean splits for the fixed runs?").  Three pieces: the
plan_start row carries the git revision the attempt ran on, so the meter
can split a run where the harness changed; after a completed leg's save
the executor copies the save, the memory, the footprint, the outline and
the chain's state files into run/saves/<leg>.<time>/ with a meta.json; and
replay_from.sh restores one and points the chain at the leg after it.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E
import arc

# the revision
rev = E.harness_rev()
ck("the harness revision is a short git hash, marked + when the tree differs",
   len(rev.rstrip("+")) >= 7 and all(c in "0123456789abcdef" for c in rev.rstrip("+")))
src = Path("planner/executor.py").read_text()
ck("the plan_start row carries it", "rev=harness_rev())" in src
   and 'self.log("plan_start", goal=plan.get("goal"), escalate=self.can_escalate,' in src)
ck("the checkpoint is taken after the saves, before the verdict",
   src.index("checkpoint_leg(ex.plan_path, complete=") > src.index("(after a failed plan, to keep what it earned)")
   and src.index("checkpoint_leg(ex.plan_path, complete=") < src.index('_verdict = ("ALL PLANS COMPLETE"'))

# the checkpoint, on a scratch tree
tmp = Path(tempfile.mkdtemp(dir="/tmp/claude-1000/-home-wiz/"
                            "b5fe8565-91da-4233-b62f-8b773e98e750/scratchpad"))
(tmp / "run").mkdir(); (tmp / "plans").mkdir(); (tmp / "saves").mkdir()
(tmp / "saves" / "slot1.lua").write_text("return {}")
(tmp / "run" / "explored.json").write_text("{}")
(tmp / "run" / "seen.json").write_text("return {}")
(tmp / "plans" / "outline.txt").write_text("Obtain a starter Pokemon\nReach Pewter City\n")
(tmp / "run" / "outline_skips").write_text("x\n")
d = E.checkpoint_leg(tmp / "plans" / "leg_06_reach_pewter_city.json", root=tmp,
                     save_path=tmp / "saves" / "slot1.lua", out_dir=tmp / "run" / "saves")
ck("a checkpoint directory is made under run/saves, named for the leg",
   d is not None and d.parent == tmp / "run" / "saves" and d.name.startswith("leg_06_reach_pewter_city."))
meta = json.loads((d / "meta.json").read_text()) if d else {}
ck("meta.json names the leg, the plan and the harness",
   meta.get("leg") == 6 and meta.get("plan") == "leg_06_reach_pewter_city" and meta.get("rev") == rev)
ck("the save, the memory, the footprint, the outline and the state files are copied",
   d is not None and all((d / f).exists() for f in ("slot1.lua", "explored.json", "seen.json", "outline.txt", "outline_skips")))
ck("a file that did not exist is simply not there", d is not None and not (d / "seen_walk.json").exists())
d2 = E.checkpoint_leg(tmp / "plans" / "leg_08_x.json", root=tmp, save_path=tmp / "saves" / "slot1.lua",
                      out_dir=tmp / "run" / "saves", complete=False)
ck("a checkpoint after a failed attempt says the leg was not completed",
   d2 is not None and json.loads((d2 / "meta.json").read_text()).get("complete") is False)
ck("...and one after a completed leg says it was", meta.get("complete") is True)
ck("the checkpoint is taken at every attempt's end, not only after a completed plan",
   "checkpoint_leg(ex.plan_path, complete=bool(ok), carried=list(_carried))" in src)
ck("...and complete means the plan completed: a carried middle hop is recorded beside the flag, not folded into it "
   "(run 16's leg-13 checkpoint said incomplete one second after plan_complete, 2026-09-07)",
   '"carried": list(carried or ()),' in src and "complete=bool(ok and not _carried)" not in src)
ck("a plan that is not a leg makes no checkpoint",
   E.checkpoint_leg(tmp / "plans" / "brock.json", root=tmp, save_path=tmp / "saves" / "slot1.lua",
                    out_dir=tmp / "run" / "saves") is None)

# the meter reads the revision per start
j = tmp / "executor_log.jsonl"
j.write_text(json.dumps({"dt": 0.0, "kind": "plan_start", "goal": "A", "rev": "abc1234"}) + "\n"
             + json.dumps({"dt": 5.0, "kind": "escalate_context", "memory": "\nWHERE YOU STAND: PALLET_TOWN|10,0 — x"}) + "\n"
             + json.dumps({"dt": 0.0, "kind": "plan_start", "goal": "B", "rev": "def5678+"}) + "\n")
r = arc.scan(str(j))
ck("the meter keeps each start's revision", r["revs"] == ["abc1234", "def5678+"])

# the replay script parses and refuses without a checkpoint
ck("replay_from.sh parses", subprocess.run(["bash", "-n", "replay_from.sh"]).returncode == 0)
p = subprocess.run(["./replay_from.sh", str(tmp / "nowhere")], capture_output=True, text=True)
ck("...and refuses a path with no meta.json", p.returncode == 2 and "meta.json" in p.stderr)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
