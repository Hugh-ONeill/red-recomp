"""A push the outline undid is not a push the model spent (2026-08-26).

`check_later` refuses a third deferral, and fresh_discovery.sh counted every
line in run/outline_pushes bearing the objective's text. But the outline
SHRINKS underneath a pushed leg — legs ahead of it are crossed off by
check-done and the look-ahead sweep, and it slides back toward the front:

    32  36  Obtain the Secret Key      pushed to after 36...
    34  37  Obtain the Secret Key      ...came up at 34, pushed to after 37...
                                       ...and came up at 36.

Two deferrals spent and it sits BEFORE both targets, so neither is in force.
The rung refused a third and the chain STOPPED on that leg — with the correct
answer, "put it after Reach Cinnabar Island, which is where the key actually
is", never asked for (user: "wouldnt the real exit be pushing it back to
cinnabar though?"). "Defeat the Silph Co. guards" shows the same shape four
times over.

Count a push only while it still HOLDS: the leg is now later than the position
it was pushed to."""
import sys, re, subprocess
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

sh = Path("fresh_discovery.sh").read_text()

ck("the raw text count is gone",
   'grep -Fc "$leg" run/outline_pushes' not in sh)
ck("a single helper decides it", "pushes_in_force() {" in sh)
h = sh[sh.find("pushes_in_force() {"):][:400]
ck("...matching the objective by text in column 3", '$3 == want' in h)
ck("...and counting only targets EARLIER than where it now sits",
   "($2+0) < now" in h)
ck("both callers use it",
   sh.count('pushes_in_force "$leg" "$i"') == 2)
ck("the blocker rung still declines a leg with a push in force",
   'if [ "$pushed_before" -gt 0 ]; then' in sh)
ck("the chain-wide cap of 20 is untouched",
   'cat run/outline_pushes 2>/dev/null | wc -l)" -lt 20' in sh)
ck("the script parses",
   subprocess.run(["bash", "-n", "fresh_discovery.sh"]).returncode == 0)

def in_force(want, now):
    out = subprocess.run(
        ["awk", "-F\t", "-v", f"want={want}", "-v", f"now={now}",
         "$3 == want && ($2+0) < now { n++ } END { print n+0 }",
         "run/outline_pushes"], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)

raw = Path("run/outline_pushes").read_text().count("Obtain the Secret Key")
ck(f"the old count said {raw} — the rung's cap is 2", raw >= 2)
ck("in force at leg 36: none, so the rung reopens",
   in_force("Obtain the Secret Key", 36) == 0)
ck("a push is still counted while it holds",
   in_force("Obtain the Secret Key", 99) == 2)
ck("the Silph leg shows the same undoing",
   in_force("Defeat the Silph Co. guards to reach the President", 36)
   < Path("run/outline_pushes").read_text().count(
       "Defeat the Silph Co. guards to reach the President"))

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
