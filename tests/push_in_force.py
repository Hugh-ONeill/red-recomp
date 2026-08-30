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

Count a push only while it still HOLDS: the leg is now AT OR AFTER the
position it was pushed to.

AT counts (2026-08-30). push_leg lands the leg exactly ON `after`, so a
strict `<` said a push stopped holding the instant it was made: it could
only ever count while something had been INSERTED before the leg. The guard
built on it was dead, and "Obtain Fresh Water" — pushed 21->25 with the
model's own reason that Celadon must be reached first — was pulled straight
back to 20 twenty minutes later, rebuilding the deadlock, with the refusal
that exists for exactly that never firing."""
import sys, re, subprocess
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

sh = Path("fresh_discovery.sh").read_text()

ck("the raw text count is gone",
   'grep -Fc "$leg" run/outline_pushes' not in sh)
ck("a single helper decides it", "pushes_in_force() {" in sh)
# the helper grew the comment explaining AT-counts
h = sh[sh.find("pushes_in_force() {"):][:1400]
ck("...matching the objective by text in column 3", '$3 == want' in h)
ck("...and counting a target the leg has not slid back in front of",
   "($2+0) <= now" in h)
ck("both callers use it",
   sh.count('pushes_in_force "$leg" "$i"') == 2)
ck("the blocker rung still declines a leg with a push in force",
   'if [ "$pushed_before" -gt 0 ]; then' in sh)
ck("the chain-wide cap of 20 is untouched",
   'cat run/outline_pushes 2>/dev/null | wc -l)" -lt 20' in sh)
ck("the script parses",
   subprocess.run(["bash", "-n", "fresh_discovery.sh"]).returncode == 0)

# THE LIVE LEDGER MOVES; the test does not. Written against run/outline_pushes
# as it stood, this test failed the moment the leg was reworded (its rows
# then carried the longer name). The helper is read out of the script and
# run against a fixture that never changes.
import os, tempfile
_prog = re.search(r"pushes_in_force\(\) \{.*?'(\$3 == want[^']*)'", sh, re.S)
ck("pushes_in_force's awk program can be read out of the script", bool(_prog))
_fx = Path(tempfile.mkdtemp(prefix="pushes_")) / "outline_pushes"
_fx.write_text("32\t36\tObtain the Secret Key\n"
               "34\t37\tObtain the Secret Key\n"
               "30\t32\tDefeat the Silph Co. guards to reach the President\n"
               "34\t36\tDefeat the Silph Co. guards to reach the President\n")

def in_force(want, now):
    out = subprocess.run(
        ["awk", "-F\t", "-v", f"want={want}", "-v", f"now={now}",
         _prog.group(1) if _prog else "", str(_fx)],
        capture_output=True, text=True)
    return int(out.stdout.strip() or 0)

raw = _fx.read_text().count("Obtain the Secret Key")
ck(f"the old count said {raw} — the rung's cap is 2", raw >= 2)
# THE OUTLINE SHRANK THE LEG BACK IN FRONT OF BOTH TARGETS: neither is
# being honoured any more, so neither was spent.
ck("in force at leg 34, in front of both targets: none",
   in_force("Obtain the Secret Key", 34) == 0)
ck("...so the rung reopens there, which was the whole bug",
   in_force("Obtain the Secret Key", 34) < 2)
# ...BUT SITTING EXACTLY WHERE A PUSH PUT IT IS THAT PUSH BEING HONOURED.
ck("at leg 36 the first push is holding: one",
   in_force("Obtain the Secret Key", 36) == 1)
ck("at leg 37 both are holding: two, and a third is refused",
   in_force("Obtain the Secret Key", 37) == 2)
ck("a push is still counted while it holds",
   in_force("Obtain the Secret Key", 99) == 2)
ck("the Silph leg reads the same way",
   in_force("Defeat the Silph Co. guards to reach the President", 31) == 0
   and in_force("Defeat the Silph Co. guards to reach the President", 36) == 2)
ck("a name the ledger never saw is not in force anywhere",
   in_force("Reach Cinnabar Island", 99) == 0)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
