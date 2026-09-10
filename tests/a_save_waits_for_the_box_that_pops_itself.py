#!/usr/bin/env python3
"""A save is not over when the StartMenu comes back into view.

SAVE is picked FROM the StartMenu, so the menu sits under the whole
sequence and is the top for the gap between "Now saving..." popping
itself and "<NAME> saved the game!" being pushed.  The drain loop broke
on the menu, which ended it inside that gap: the B presses after it hit a
box that ignores input, the op returned with the box still up, and the
NEXT save's need_overworld refused with "a box was up and would not
close: text: RED saved the game!" -- followed a second later by a third
save reporting "save file never changed".

Run 16's log has fourteen of those pairs on 2026-09-10 alone, always in
that order, seconds apart, from 19:00 the previous evening to 13:05.  The
ratchet save is what a dead game boots from, so each pair is an attempt
that would have resumed further back than it had got to.

The loop is not transcribed here: the lines are cut out of shim.lua at
test time and run, against a scripted UI stack.  No game, no model.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIM = (ROOT / "harness" / "shim.lua").read_text()

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

# ---- cut the shipped loop out of the shim ------------------------------
lines = SHIM.splitlines()
start = next(i for i, l in enumerate(lines)
             if l.strip() == "local saw_box, menu_for = false, 0")
end = next(i for i in range(start + 1, len(lines)) if lines[i] == "  end")
BLOCK = "\n".join(lines[start:end + 1])
ck("the drain loop was found in the shim", "for _ = 1, 200 do" in BLOCK, BLOCK[:80])

RIG = """
local seq = { %s }
local G = { overworld = { screenId = "Overworld" } }
local i = 0
local U = { wait = function() i = i + 1 end }
local function ui_top()
  local s = seq[math.min(i + 1, #seq)]
  if s == "overworld" then return G.overworld end
  return { screenId = s }
end
%s
print(i, tostring(saw_box))
"""


def run(seq):
    src = RIG % (", ".join('"%s"' % s for s in seq), BLOCK)
    p = subprocess.run(["lua", "-"], input=src, capture_output=True, text=True)
    if p.returncode != 0:
        return None, p.stderr.strip()
    waits, saw = p.stdout.split()
    return int(waits), saw == "true"


# the real order: menu -> saving box -> menu again -> saved box -> menu
# menu, "Now saving...", the gap where the menu shows through, "saved
# the game!", then the menu for good
SAVING = (["StartMenu", "TextBox", "StartMenu", "StartMenu", "TextBox"]
          + ["StartMenu"] * 20)
n, saw = run(SAVING)
ck("it does not stop in the gap between the two boxes", n is not None and n > 4,
   f"stopped after {n} wait(s)")
ck("...it stops once the menu has stayed the top", n == 12, f"waits={n}")
ck("...having seen a box", saw is True)

# the overworld is the end of it whenever it appears
n2, _ = run(["overworld"])
ck("the overworld ends it at once", n2 == 0, f"waits={n2}")
n3, _ = run(["StartMenu", "TextBox", "overworld"])
ck("...even with a box in the way first", n3 == 2, f"waits={n3}")

# no box ever pushed: the loop must not call the menu the end of it
n4, saw4 = run(["StartMenu"])
ck("a menu that never yields a box runs the wait out, not one pass",
   n4 == 200, f"waits={n4}")
ck("...and never claims to have seen a box", saw4 is False)

# ---- and the file is asked once more before this is called a failure ---
tail = SHIM.split("local saw_box, menu_for = false, 0", 1)[1]
tail = tail.split("save file never changed", 1)[0]
ck("the stamp is re-read before a failure is returned",
   "if not written and save_stamp() > stamp0 then written = true end" in tail)
ck("...and the failure is still reachable",
   'return false, ("save file never changed (top=%s)")' in SHIM)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d) + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
