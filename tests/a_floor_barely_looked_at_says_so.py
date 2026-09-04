#!/usr/bin/env python3
"""A floor barely looked at says so (2026-09-04).

The unseen-ground list counted SPOTS — openings where the seen ground ends —
so "ROCKET_HIDEOUT_B2F|19,7 (3 spot(s), 2 leg(s))" read as a floor nearly
finished, and the plan said "I have already explored most of B3F and B2F"
(user: "wrong theres lots of unseen ground on bf2"). Three openings can lead
onto most of a floor; the run had looked at 195 cells of B2F against 629 of
B3F. The run's own count of what it has seen now rides the row, with the
caveat that it says how much was looked at, never how big the floor is.

Synthetic: a temp seen.json, no game, no model."""
import sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

with tempfile.TemporaryDirectory() as d:
    seen = Path(d) / "seen.json"
    seen.write_text('return {\n["ROCKET_HIDEOUT_B2F"] = { "17,4","17,5","18,4" },\n'
                    '["ROCKET_HIDEOUT_B3F"] = { "1,1","1,2","1,3","1,4","1,5","1,6" },\n}\n')
    e = object.__new__(E.Executor); e._seen_path = str(seen)
    ck("the count is the run's own seen mask for that floor", e._seen_cell_count("ROCKET_HIDEOUT_B2F") == 3)
    ck("...per floor", e._seen_cell_count("ROCKET_HIDEOUT_B3F") == 6)
    ck("a floor never on screen counts zero", e._seen_cell_count("SILPH_CO_1F") == 0)
    w = e._seen_cells_words("ROCKET_HIDEOUT_B2F|19,7")
    ck("the words ride a region key and say cells ever on screen", w == "3 cells ever on screen, ", w)
    ck("...and say nothing for a floor with no record", e._seen_cells_words("SILPH_CO_1F|0,0") == "")
    ck("...and never how big the floor is", "of " not in w and "%" not in w)
    seen.write_text('return {\n["ROCKET_HIDEOUT_B2F"] = { "17,4","17,5","18,4","18,5","18,6" },\n}\n')
    import os, time
    os.utime(seen, (time.time() + 5, time.time() + 5))
    ck("the cache follows the file's mtime", e._seen_cell_count("ROCKET_HIDEOUT_B2F") == 5)
e2 = object.__new__(E.Executor); e2._seen_path = "/nonexistent/seen.json"
ck("no file = zero, no error", e2._seen_cell_count("X") == 0 and e2._seen_cells_words("X|0,0") == "")

src = (ROOT / "planner" / "executor.py").read_text()
ck("the unseen-ground rows carry the count",
   'f"{_m} ({-_n} spot(s), " + self._seen_cells_words(_m)' in src)
ck("...with the caveat on the list's tail",
   "one spot can \"\n                  \"open onto most of a floor; the cell count says how much \"\n                  \"you have looked at, not how big the floor is." in src)
bad = [c for c in checks if not c[1]]
for n, ok, dd in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(dd)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
