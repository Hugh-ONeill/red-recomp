"""A standing shut door is never 'done' (2026-08-26).

Pressing a Silph card-key shutter without the key says "Darn! It needs a CARD
KEY!" — a real reply, so it banked a touch, and the floor then read FULLY
WORKED with the door still drawn shut across the way. The same tile, the same
press, answers "Bingo! The CARD KEY opened the door!" once the key is in the
bag: both replies are in this run's journal for DOOR_SILPH_CO_8F_7_8 (user:
"are the shutters counting as 'touched' because we might want to make them
fixtures so they dont count like that").

The shim only MINTS a shut door while its tile is still a door tile, so a
shut_door in the observation is proof the thing is still closed, whatever was
pressed at it."""
import sys, re
from pathlib import Path
sys.path.insert(0, "planner")
import ledger as L

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

def cand(kind, key, status):
    c = L.Candidate(key=key, kind=kind)
    c.status = status
    return c

# --- switches() ---
shut = cand("shut_door", "DOOR_SILPH_CO_8F_7_8", "touched")
fix = cand("fixture", "SLOT_MACHINE_1", "touched")
pc = cand("fixture", "PC", "touched")
gone = cand("shut_door", "DOOR_FAR", "unreachable")
npc = cand("npc", "SILPHCO8F_ROCKET", "touched")
sw = L.switches([shut, fix, pc, gone, npc])
ck("a touched shut door is pressable again", shut in sw)
ck("...and a fixture still is", fix in sw)
ck("a PC is still excluded", pc not in sw)
ck("an unreachable one is still excluded", gone not in sw)
ck("an ordinary npc is not a switch", npc not in sw)

# --- fully_worked() ---
ck("a floor with a standing shut door is not fully worked",
   L.fully_worked([shut, npc]) is False)
ck("a floor with none is still fully worked",
   L.fully_worked([npc]) is True)

src = Path("planner/ledger.py").read_text()

# --- the row says why it is worth another press ---
i = src.find("IT IS STILL DRAWN SHUT")
ck("the row says it is still shut", i > 0)
blk = src[max(0, i - 500):i + 600]
ck("...only once it has actually been pressed",
   'c.status in ("touched", "inert",' in blk)
ck("it says a door answers differently once the world moves",
   "answers differently once" in blk)
ck("it does not name what opens it",
   not re.search(r"(?i)(card.?key|you need|go and get)",
                 " ".join(re.findall(r'"([^"]*)"', blk))))

# --- and the head line calls a door a door ---
j = src.find("Everything here has been pressed at least once")
hblk = src[max(0, j - 400):j + 700]
ck("the head names closed doors as doors, not fixtures",
   '"the closed doors" if _shut' in hblk
   and '"the fixtures and closed doors" if _shut' in hblk)
ck("...and still says fixtures when that is all there is",
   'else "the fixtures")' in hblk)

import ast
try:
    ast.parse(src); ck("ledger.py parses", True)
except SyntaxError as e:
    ck(f"ledger.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
