"""A boxed Pokemon is named on every page, not only on party-goal pages
(2026-08-26): the run boxed its EEVEE to fit a DIGLETT that satisfied "the
party holds a GROUND or WATER type", and on a map or flag goal — the kind of
goal a Surf block produces — storage was never mentioned again."""
import sys, re
from pathlib import Path
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()
i = src.find("IN PC STORAGE (yours, not in the party")
ck("the general page names storage", i > 0)

# it must sit on the page every goal gets, not inside a party-goal branch
seg = src[max(0, i - 1400):i]
ck("...outside the party-goal branches",
   "_rs_line = self._respawn_line(obs)" in seg)
ck("it names species, level, box and index",
   'f"{m.get(\'species\')} L{m.get(\'level\')} "' in src[i:i + 900]
   and "box {m.get('box')}, #{m.get('index')}" in src[i:i + 900])
ck("it says a boxed one counts for nothing until withdrawn",
   "counts for nothing until it is taken out" in src[i:i + 400])
ck("it names the op that takes one out", 'pc_withdraw' in src[i:i + 700])
ck("nothing is said about WHY to take one out",
   not re.search(r"(?i)(surf|vaporeon|water stone|you should|use the)", src[i:i + 900]))
ck("it only fires when something is stored",
   "if _boxed:" in src[max(0, i - 400):i + 200])
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
