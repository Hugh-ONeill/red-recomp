#!/usr/bin/env python3
"""run/status.txt says which earlier steps were carried past unmet.

The plan walks on past a failed map hop on purpose (a missed hop must not
forfeit the plan), and the model is told so in its prompt: PREMISE UNMET
names the step, what it asked for, and where the party stands. But the
status file showed only the step now being tried, so "SUBGOAL get_hm01"
read as reach_captain having been reached (2026-09-14, user: "its only
reached that falsely, its not up to the captains room yet").
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

i = src.index("    def status(self, **kw):")
body = src[i:src.index("\n    def ", i + 10)]
ck("status reads the carried steps", '_carried = [c for c in (getattr(self, "_carried_ids", None) or [])]' in body)
ck("...and names each with the condition it asked for",
   'f"{c} NOT achieved {json.dumps(_dws.get(c) or {})}"' in body)
ck("...as a CARRIED line right under SUBGOAL", 'lines.insert(2, "CARRIED  "' in body
   and body.index('f"SUBGOAL  ') < body.index('lines.insert(2, "CARRIED  "'))
ck("...saying the step now shown is tried anyway", "carried past, this step is tried anyway" in body)
ck("nothing is shown when nothing was carried", "if _carried:" in body)
ck("the model's own prompt already carries the same fact (PREMISE UNMET)",
   '"\\nPREMISE UNMET: "' in src and "self._carried_premise_note(sg, obs)" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
