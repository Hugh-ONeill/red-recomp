"""One model reply cannot run for a quarter of an hour.

Run 16 (2026-09-07): an escalation reply fell into a repetition loop and
generated 6500+ tokens at 22 tok/s where a forty-token JSON macro was due.
The client's 300 s timeout fired, retried once, and the retry ran on the
same way; the party stood on the Route 24 / Cerulean boundary for ten
minutes with the GPU at 99% (user: "it seems like its been stuck in the
same place for a while").  Nothing capped the generation.

Every reply the harness asks for is bounded -- a macro, a verdict, a plan,
an outline draft -- so the request carries num_predict.  A reply cut there
fails JSON parsing and costs one round, not the quarter hour.
"""
import sys
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import brock_probe as B
src = Path("planner/brock_probe.py").read_text()
ck("the request carries a token ceiling", '"num_predict": NUM_PREDICT' in src)
ck("the ceiling is a few thousand tokens: room for a plan, not for a runaway",
   1024 <= B.NUM_PREDICT <= 8192)
ck("it can be raised or lowered by environment like the window",
   'os.environ.get("RED_NUM_PREDICT")' in src)
ck("a timeout is still retried once and no more", "budget = 1 if _is_timeout(e) else retries" in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
