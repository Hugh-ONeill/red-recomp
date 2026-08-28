#!/usr/bin/env python3
"""Whether a leg is already done is asked BEFORE its first attempt.

"Navigate the Safari Zone" reached its first attempt with every Safari
map stood in and lit end to end, and spent the attempt hunting a key
that is not there: the leg's own judge ran only after a failure, and the
sweep at the end of the previous leg had run before the walked record
reached it (2026-08-28). One check-done per leg, with --observed so the
walked record is in front of it, ahead of the dry gate and the campaign.
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(name, ok): checks.append((name, bool(ok)))
sh = (ROOT / "fresh_discovery.sh").read_text()
ck("the script parses", subprocess.run(["bash", "-n", str(ROOT / "fresh_discovery.sh")]).returncode == 0)
i = sh.index("judged already accomplished before running")
blk = sh[max(0, i - 900):i]
ck("check-done is asked before the leg runs", "--check-done" in blk and "--observed run/explored.json" in blk)
ck("...after the leg baseline is taken", sh.index("leg_delta.py snap run/leg_start.json") < i)
ck("...before the dry gate and the first campaign call",
   i < sh.index("--dry-tail --goal") and i < sh.index('run_campaign "$cont" 1'))
ck("...not for a leg that could not be written (that goes to the ladder)", '[ "${_no_plan:-0}" = 0 ]' in blk)
ck("a yes crosses the leg off and sweeps ahead", 'echo "$i" > "$PROGRESS"' in sh[i:i + 300] and 'sweep_ahead "$i"' in sh[i:i + 300])
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
