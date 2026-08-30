"""The campaign fell back to the very plan the author had just refused.

When a re-author produces nothing, keeping the last plan is the right answer
for a flaky model call. It is the wrong answer when every rewrite was
rejected BECAUSE the plan cannot finish: leg 19's author cycled Vermilion and
Cerulean for five rounds, each refused with "FRESH_WATER is not on its
shelf", and the fallback handed that same plan straight back to the executor
to run for three more attempts (2026-08-30).

So the fallback asks first. A plan the validator will not pass is not a
fallback, it is the problem.
"""
import subprocess, sys, json, tempfile, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

for f in ("campaign.sh", "campaign.run.sh"):
    sh = (ROOT / f).read_text()
    ck(f"{f} asks before falling back",
       'if python planner/author.py --validate "plans/$failed_plan" \\'
       in sh)
    ck(f"{f} still keeps a good plan when the re-author is flaky",
       'rewritten="plans/$failed_plan"' in sh)
    ck(f"{f} says what happened and stops rather than running it",
       "does not validate" in sh and "exit 6" in sh)
    ck(f"{f} prints the problems it found",
       sh.count('planner/author.py --validate "plans/$failed_plan"') == 2)

# --- the flag itself ---
with tempfile.TemporaryDirectory() as d:
    os.chdir(d)
    Path("run").mkdir()
    Path("run/explored.json").write_text(json.dumps({
        "explored": {"VERMILION_CITY|18,0": {}},
        "shelves": {"VERMILION_MART": ["POKE_BALL", "REPEL"]},
        "shelf_reads": {"VERMILION_MART": {"n": 3, "moved": False}}}))
    def val(plan):
        Path("p.json").write_text(json.dumps(plan))
        return subprocess.run(
            [sys.executable, str(ROOT / "planner/author.py"),
             "--validate", "p.json"], capture_output=True, text=True)
    good = {"goal": "g", "subgoals": [
        {"id": "a", "goal_text": "Walk to Vermilion",
         "done_when": {"map": "VERMILION_CITY"}}]}
    r = val(good)
    ck("a plan that validates exits 0", r.returncode == 0, r.stdout + r.stderr)
    bad = {"goal": "g", "subgoals": [
        {"id": "a", "goal_text": "Enter the mart",
         "done_when": {"map": "VERMILION_MART"}},
        {"id": "b", "goal_text": "Buy Fresh Water",
         "done_when": {"has_item": {"FRESH_WATER": 1}}}]}
    r = val(bad)
    ck("a plan that does not exits 3", r.returncode == 3, r.stdout + r.stderr)
    ck("...and prints why", "FRESH_WATER is not on it" in r.stdout, r.stdout)
    r = subprocess.run([sys.executable, str(ROOT / "planner/author.py"),
                        "--validate", "no_such_file.json"],
                       capture_output=True, text=True)
    ck("a missing plan is not a fallback either", r.returncode == 3)
    # --goal is required of every other mode, and of none of this one
    r = subprocess.run([sys.executable, str(ROOT / "planner/author.py"),
                        "--dry-tail"], capture_output=True, text=True)
    ck("every other mode still requires a goal",
       r.returncode != 0 and "--goal is required" in (r.stdout + r.stderr))

bad_c = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:200])
sys.exit(1 if bad_c else 0)
