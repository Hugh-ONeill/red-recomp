#!/usr/bin/env python3
"""Before the chain stops, the wording rung is asked once more.

Leg 13, 2026-08-29 ("Clear Route 4 of trainers"): its one trainer sits
behind a ONE-WAY LEDGE with the way round unwalked — the case VOID exists
for — and the rung that owns VOID was never asked, because of a two-ask
count. The rolling reword budget inside that same rung already draws the
line ("the budget withholds the REWRITE, not the QUESTION: stands, done
under another name and VOID are still the model's to answer"); the outer
cap was shutting the question itself. Stopping the run to save one model
call is the worst trade available, so the ask is made when the alternative
is stopping — and it is labelled as such.
"""
import sys
from pathlib import Path
sh = (Path(__file__).resolve().parents[1] / "fresh_discovery.sh").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))
ck("the two-ask cap can be bypassed only by the last word",
   '[ "${_asked:-0}" -ge 2 ] && [ "${2:-}" != "last-word" ]' in sh)
ck("...and says why when it is",
   "asked once more, because" in sh and "the alternative is stopping the chain" in sh)
ck("the stop path spends it, and carries on if the rung disposes of the leg",
   'if wording_rung "" last-word; then continue; fi' in sh
   and sh.index('if wording_rung "" last-word') < sh.index('echo "=== chain stopped at leg'))
ck("the ordinary asks are still capped at two",
   'echo "[wording] not asked: this leg has been asked twice already"' in sh)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
