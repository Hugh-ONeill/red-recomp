#!/usr/bin/env python3
"""A leg whose last two runs yielded nothing is not run again as it stands.

"Obtain the Secret Key" got 37 attempts over 19 campaign calls because
every rung that said "continue" handed the leg a fresh 1+3 attempts when
it resurfaced. User, 2026-08-27: "we can't have a situation where we're
trying the same actions over and over again … if we're not getting it or
making any progress over the course of a leg then whatever is going on
the leg is not right for this outline, whether it needs to be moved,
changed, or removed."

Two dry runs in a row (run/attempt_yield, since the last disposition
marker) send the leg straight to the ladder. Every disposition — push,
pull, reword, insert — writes a marker that resets the count.
"""
from __future__ import annotations
import os, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A            # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

sh = (ROOT / "fresh_discovery.sh").read_text()
ck("the script parses", subprocess.run(["bash", "-n", str(ROOT / "fresh_discovery.sh")]).returncode == 0)
gate = sh.index("--dry-tail --goal")
ck("the dry gate stands before the first campaign call of the leg",
   gate < sh.index('run_campaign "$cont" 1'))
ck("...and skips straight to the ladder", '[ "${_dry:-0}" -ge 2 ]' in sh and "crc=2" in sh[gate:gate + 900])
ck("...saying so in the log", "not run again as it stands" in sh)
for what in ("moved to after leg $at", "reworded to: $said", "a step was put before it",
             "leg $blocker was pulled ahead of it", "a pull that put it here was undone",
             "authoring failed; moved to after leg"):
    ck(f"a disposition writes its marker: {what[:28]}", f'disposed "{what}' in sh)
ck("the marker lands in the yield ledger under the leg", "DISPOSED: %s" in sh and ">> run/attempt_yield" in sh)

tmp = Path(tempfile.mkdtemp(prefix="dry_"))
(tmp / "run").mkdir()
os.chdir(tmp)
NOTHING = "NOTHING changed while this leg ran: no event fired, no item or badge was gained, and no new place was entered."
GAIN = "WHAT CHANGED WHILE THIS LEG RAN — items gained: HM_SURF x1."
G = "Obtain the Secret Key"
def ledger(*rows):
    (tmp / "run/attempt_yield").write_text("".join(f"{G}\t36\t{a}\t{t}\n" for a, t in rows))
def cli():
    out = subprocess.run([sys.executable, str(ROOT / "planner/author.py"), "--dry-tail", "--goal", G],
                         capture_output=True, text=True, cwd=tmp)
    return int(out.stdout.strip() or -1)

ck("no record: not dry", A.dry_tail(G) == 0)
ledger(("1", NOTHING))
ck("one dry run is not enough", A.dry_tail(G) == 1 and cli() == 1)
ledger(("1", NOTHING), ("3", NOTHING))
ck("two dry runs in a row: the leg is dry", A.dry_tail(G) == 2 and cli() == 2)
ledger(("1", GAIN), ("3", NOTHING), ("3", NOTHING))
ck("...however much it gained earlier", A.dry_tail(G) == 2)
ledger(("1", NOTHING), ("3", NOTHING), ("0", "DISPOSED: moved to after leg 39"))
ck("a disposition resets the count", A.dry_tail(G) == 0 and cli() == 0)
ledger(("1", NOTHING), ("3", NOTHING), ("0", "DISPOSED: moved to after leg 39"), ("3", NOTHING))
ck("...and the runs after it count from there", A.dry_tail(G) == 1)
ledger(("1", NOTHING), ("3", GAIN))
ck("a run that gained something is not dry", A.dry_tail(G) == 0)

ledger(("1", GAIN), ("0", "DISPOSED: moved to after leg 37"), ("3", NOTHING), ("3", NOTHING))
text, dry = A.attempt_yield_text(G)
ck("the record shows the disposition where it happened", "then, as leg 36: moved to after leg 37" in text)
ck("...numbers only the runs", "run 1 (" in text and "run 3 (" in text and "run 4 (" not in text)
ck("...and a dry leg is told it will not be run again as it stands",
   dry == 2 and "AS IT STANDS IT WILL NOT BE RUN AGAIN" in text
   and "it moves" in text and "it changes" in text and "it goes" in text
   and "a person looks" in text)
ledger(("1", GAIN), ("3", NOTHING))
text, dry = A.attempt_yield_text(G)
ck("a leg one dry run in is not told that", "WILL NOT BE RUN AGAIN" not in text)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
