"""FLY is not in the menu indoors, and the refusal never said so.

PartyMenu offers FLY and TELEPORT only when Map.isOutside, and FLASH only
where it is dark (src/ui/PartyMenu.lua, CheckIfInOutsideMap). The harness
explained the BADGE gate on that menu and neither of the others, so the run
was told "FLY was not offered in the menu (it lists: CUT, STATS, SWITCH)" —
which reads as its FARFETCHD, who knows both moves, having lost one. 134
FLY attempts stand in this run's journal (user, 2026-08-24: "its not
realizing we cant fly inside").
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
shim = (ROOT / "harness" / "shim.lua").read_text()
vocab = (ROOT / "planner" / "executor.py").read_text()

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


i = shim.find("was not offered in the menu")
block = shim[max(0, i - 2600):i + 400]

ck("the badge gate is still explained", "badge case" in block)
ck("the outdoor gate is named for FLY", "only while you are" in block
   and "OUTSIDE" in block)
ck("TELEPORT is covered by the same gate",
   'mv == "FLY" or mv == "TELEPORT"' in block)
ck("the dark gate is named for FLASH",
   "only where it is DARK" in block)
ck("it uses the engine's own isOutside, not a guess",
   "MapM2.isOutside" in block)
ck("it does not claim a gate it has not tested",
   "okv2 and not out2" in block)

ck("the op vocabulary warns before the attempt, not only after",
   "FLY IS ONLY EVER LISTED WHILE YOU ARE OUTSIDE" in vocab)
ck("...and points at the field that says which", "map.outdoor" in vocab)

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
