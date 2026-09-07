#!/usr/bin/env python3
"""A round's journal row says what its model call cost.

Run 16's rounds took a median 30 s on the S.S. Anne where run 14's took 16
(2026-09-07; user: "i think this is taking longer than the last runthrough
in this area"). The meter could say a leg's rounds and minutes and nothing
about what a round was made of, though ollama reports prompt tokens and
seconds and generated tokens and seconds on every reply and the probe read
one of those numbers for its truncation check and dropped the rest. Now the
probe keeps the last call's accounting and the proposal row carries it.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import brock_probe as B   # noqa: E402
ex = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))

st = B.stats_of({"prompt_eval_count": 9000, "prompt_eval_duration": 11_500_000_000,
                 "eval_count": 420, "eval_duration": 16_200_000_000, "total_duration": 28_000_000_000})
ck("tokens are counted and durations are seconds",
   st == {"ptok": 9000, "gtok": 420, "p_s": 11.5, "g_s": 16.2, "tot_s": 28.0})
ck("a reply without the numbers yields Nones, not a crash",
   B.stats_of({}) == {"ptok": None, "gtok": None, "p_s": None, "g_s": None, "tot_s": None}
   and B.stats_of(None)["ptok"] is None)
ck("the probe records the last call's accounting", "LAST = stats_of(d)" in B.__doc__ or "LAST = stats_of(d)" in (ROOT / "planner" / "brock_probe.py").read_text())
ck("the proposal row carries it, Nones left out",
   '**{k: v for k, v in (getattr(brock_probe, "LAST", None) or {}).items()' in ex
   and "if v is not None})" in ex)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
