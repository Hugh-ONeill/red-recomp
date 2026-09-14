#!/usr/bin/env python3
"""Temperature is per call site: high where variety IS the answer, low
everywhere a wrong answer must at least be a consistent one.

At the rounds' 0.3 a naming reply is near enough a function of the
prompt. The run returned SAGE, JERK, Ignis, Spike and Sparky on every
replay, and one edited sentence in NAME_SYS_OWN moved all of them at once
(2026-09-14, user: "it reproduced SAGE/JERK Ignis, Spike, Sparky like
every time we re-ran it"). Nothing about naming needs consistency: every
answer is valid, and what bounds it is structural, the sanitiser plus the
refusal loop that turns down the menu's presets, the species and an empty
reply.

The same is true, and costlier, of the DRAWS. A leg is drafted several
times and chosen between precisely because one draw is high variance; at
0.3 the drafts are near copies. Measured over the chain log that prompted
this: 1181 of 2019 draw sessions collapsed to one shape, 669 of them
writing the same plan three times, so more than half the drafting paid
two or three model calls for one opinion and left the picker nothing to
pick between.

Low stays low where it matters: the escalation rounds, and every judgment
rung (check-done, check-blocker, check-missing, check-wording, and the
TM, stone and heal questions). Variety there is flakiness, and an
intermittently wrong guard is worse than a consistently wrong one,
because you cannot see it.
"""
from __future__ import annotations
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import brock_probe as B                                   # noqa: E402
import author as A                                        # noqa: E402
import executor as E                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

# ---- the argument ------------------------------------------------------------
ck("chat takes a temperature", "temp" in inspect.signature(B.chat).parameters)
ck("...defaulting to None, which means the rounds' own",
   inspect.signature(B.chat).parameters["temp"].default is None)
src_b = (ROOT / "planner" / "brock_probe.py").read_text()
ck("...and 0.3 is what None means",
   '"options": {"temperature": (0.3 if temp is None' in src_b
   and "else float(temp))," in src_b)

# ---- the two sites that want variety -----------------------------------------
ck("naming is drawn at 1.0", E.NAME_TEMP == 1.0)
ck("drafts are drawn at 0.8", A.DRAW_TEMP == 0.8)
src_e = (ROOT / "planner" / "executor.py").read_text()
src_a = (ROOT / "planner" / "author.py").read_text()
ck("ask_name passes its own temperature", "temp=NAME_TEMP)" in src_e)
ck("the draw loop passes its own", "think=bool(think) and i == 0, temp=DRAW_TEMP)" in src_a)
ck("...and author carries it through to the call",
   "temp: float | None = None) -> dict | None:" in src_a
   and "think=_thinking,\n            temp=temp)" in src_a)
ck("both knobs can be turned back from the environment",
   'os.environ.get("RED_NAME_TEMP")' in src_e and 'os.environ.get("RED_DRAW_TEMP")' in src_a)

# ---- and every judgment rung keeps the rounds' own ----------------------------
for fn in ("check_done", "check_blocker", "check_missing", "check_wording",
           "check_already_done", "pick_plan", "review"):
    if fn not in src_a:
        continue
    body = src_a.split(f"def {fn}(", 1)[1].split("\ndef ", 1)[0]
    ck(f"{fn} does not raise its temperature", "temp=" not in body, fn)
for fn in ("_ask_teach", "_ask_stone", "_ask_heal"):
    if f"def {fn}" not in src_e:
        continue
    body = src_e.split(f"def {fn}(", 1)[1].split("\n    def ", 1)[0]
    ck(f"{fn} does not raise its temperature", "temp=" not in body, fn)

# ---- it actually reaches the request -----------------------------------------
sent = {}
class _R:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return json.dumps({"message": {"content": "{}"}}).encode()
def _fake(req, timeout=None):
    sent.update(json.loads(req.data.decode()))
    return _R()
_old = B.urllib.request.urlopen
B.urllib.request.urlopen = _fake
try:
    B.chat([{"role": "user", "content": "x"}], "m")
    ck("a plain call asks for 0.3", sent["options"]["temperature"] == 0.3, sent.get("options"))
    B.chat([{"role": "user", "content": "x"}], "m", temp=1.0)
    ck("a naming call asks for what it was given", sent["options"]["temperature"] == 1.0)
    B.chat([{"role": "user", "content": "x"}], "m", temp=0.8)
    ck("...and so does a draft", sent["options"]["temperature"] == 0.8)
finally:
    B.urllib.request.urlopen = _old

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:200])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
