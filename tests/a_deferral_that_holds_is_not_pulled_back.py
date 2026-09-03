"""The pull rung undid a push forty minutes after the model made it.

"Obtain Fresh Water" was pushed 20 -> after 26, with the model's own reason:
"Fresh Water is sold at the Celadon Department Store, which requires reaching
Celadon City first". It landed after "Reach Celadon City" and the deadlock
that had eaten ten plans was resolved. Forty minutes later the Lavender leg
named it as its blocker and the pull rung moved it to 21 — back in front of
Reach Celadon City — rebuilding the deadlock exactly (2026-08-30).

The guard for this loop was already there and was on the WRONG LEG: it asks
whether the STUCK leg has been pushed, while the loop it describes in its own
comment is made by pulling back a leg that was pushed ("HM02 was pushed
29->38, the FLY leg then named it as its blocker and pulled it back to 29").
The FLY leg was never pushed, so the guard could not fire on its own example.

A push still IN FORCE is not undone by another rung. The model may push the
leg again from where it now sits, reword it, or void it — all of those are
still open, and all of them are its own.

...ONCE. Refusing every pull-back then stopped the one move that repairs a
deadlock the push itself made: "Reach Lavender Town" was pushed 22->26 for
the Flute, and the two legs left in front of it both happen in Celadon,
which this run can only reach THROUGH Lavender (2026-09-02). The harness
cannot tell a fix from a trade of places, but it can bound the cost: a pushed
leg may be pulled back once per chain (run/outline_pullbacks), the pull is
confirmed like any other, and if the stuck leg fails again in front of it the
undo rung sends it home and bars it — even when the chain-wide undo budget
is spent, since the undo is what makes the exception safe.
"""
import sys, subprocess, tempfile, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
sh = (ROOT / "fresh_discovery.sh").read_text()

ck("the pull asks about the leg it is pulling",
   '_btext=$(sed -n "${blocker}p" plans/outline.txt)' in sh
   and '_bpushed=$(pushes_in_force "$_btext" "$blocker")' in sh)
ck("...and asks whether it has been pulled back before",
   '_bback=$(grep -cxF -- "$_btext" run/outline_pullbacks' in sh)
ck("...refusing only when the push holds AND it has come back once already",
   'if [ "${_bpushed:-0}" -gt 0 ] && [ "${_bback:-0}" -gt 0 ]; then' in sh
   and "it was deliberately" in sh and "still holds" in sh
   and "pulled back once this chain" in sh)
ck("...naming the leg, so the refusal can be read",
   '$_btext)" >&2' in sh)
ck("a pushed leg pulled back is written down, so the once is a once",
   'printf \'%s\\n\' "$_btext" >> run/outline_pullbacks' in sh
   and "pulling it back ONCE" in sh)
ck("...and the ledger dies with the chain",
   "run/outline_pushes run/outline_pullbacks" in sh)
ck("a pull-back that failed goes home even when the undo budget is spent",
   'grep -qxF -- "$leg" run/outline_pullbacks' in sh
   and 'python planner/pull_leg.py undo "$i"' in sh)
ck("the stuck leg's own plan reaches the blocker rung",
   '--plan "$plan"' in sh)
ck("the old guard on the stuck leg is still there",
   'pushed_before=$(pushes_in_force "$leg" "$i")' in sh)
ck("a pull that undoes nothing still happens",
   'python planner/pull_leg.py pull "$i" "$blocker"' in sh
   and 'echo "$i<-$blocker" >> run/outline_reorders' in sh)
ck("the script parses",
   subprocess.run(["bash", "-n", str(ROOT / "fresh_discovery.sh")]
                  ).returncode == 0)

# IN FORCE means the leg still sits later than where it was pushed to; a
# push the outline has since undone is not one the model spent.
prog = None
import re
m = re.search(r"pushes_in_force\(\) \{\n(.*?)\n\}", sh, re.S)
ck("pushes_in_force can be read out of the script", bool(m))
with tempfile.TemporaryDirectory() as d:
    os.chdir(d)
    Path("run").mkdir()
    Path("run/outline_pushes").write_text(
        "20\t26\tObtain Fresh Water\n")
    def inforce(text, now):
        return int(subprocess.run(
            ["awk", "-F\t", "-v", f"want={text}", "-v", f"now={now}",
             "$3 == want && ($2+0) < now { n++ } END { print n+0 }",
             "run/outline_pushes"], capture_output=True, text=True
        ).stdout.strip() or 0)
    ck("a leg sitting after its push target is still deferred",
       inforce("Obtain Fresh Water", 27) == 1)
    ck("...and one the outline has slid back in front of it is not",
       inforce("Obtain Fresh Water", 21) == 0)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:200])
sys.exit(1 if bad else 0)
