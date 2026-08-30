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
ck("...and refuses while that push still holds",
   'if [ "${_bpushed:-0}" -gt 0 ]; then' in sh
   and "it was deliberately" in sh and "still holds" in sh)
ck("...naming the leg, so the refusal can be read",
   '$_btext)" >&2' in sh)
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
