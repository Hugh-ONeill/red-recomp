#!/usr/bin/env python3
"""Neutrally ascribed progress: every campaign run is measured in the
world's own terms and the record is shown at the rungs.

The first runs at "Obtain the Secret Key" brought the run to Fuchsia and
emptied the Safari Zone of its HMs; the last ones walked the same loop and
gained nothing — no item, no event, no new ground. Same objective; only
the measure tells them apart. User, 2026-08-27: "if we try the same
things enough times for that to happen whatever it was trying to do
doesn't make sense to be doing, particularly if there's no significant
'neutrally ascribed progress' associated with it."

The shell snaps leg_delta before each campaign call and diffs after, into
run/attempt_yield. The rungs show the record; what it means is the
model's reading. The one contract kept here: no new SENTENCE over ground
whose last two runs yielded nothing.
"""
from __future__ import annotations
import os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A            # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

sh = (ROOT / "fresh_discovery.sh").read_text()
i = sh.index("run_campaign() {")
blk = sh[i:i + 900]
ck("run_campaign snaps the world before the call",
   "leg_delta.py snap run/attempt_start.json" in blk)
ck("...and diffs it after", "leg_delta.py diff run/attempt_start.json" in blk)
ck("...keeping the row under the leg's wording, index and attempt count",
   ">> run/attempt_yield" in blk and '"$leg" "$i" "$2"' in blk)
ck("...and returns the campaign's own exit code", "return $_rc" in blk)
ck("a fresh chain clears the ledger", "run/attempt_yield run/attempt_start.json" in sh)

tmp = Path(tempfile.mkdtemp(prefix="yield_"))
(tmp / "run").mkdir()
os.chdir(tmp)
NOTHING = ("NOTHING changed while this leg ran: no event fired, no item or "
           "badge was gained, and no new place was entered.")
rows = [
    "Obtain the Secret Key\t30\t1\tWHAT CHANGED WHILE THIS LEG RAN — items gained: HM_SURF x1; 6 place(s) entered for the first time: SAFARI_ZONE_WEST|20,0.",
    "Obtain the Secret Key\t34\t3\t" + NOTHING,
    "Obtain the Secret Key from the Secret House\t36\t3\t" + NOTHING,
]
(tmp / "run/attempt_yield").write_text("\n".join(rows) + "\n")
(tmp / "run/outline_rewordings").write_text(
    "36\tObtain the Secret Key\tObtain the Secret Key from the Secret House\n")

text, dry = A.attempt_yield_text("Obtain the Secret Key from the Secret House")
ck("the record follows the leg through its rewordings", "run 1 (as leg 30" in text)
ck("a gaining run is shown as what it gained", "HM_SURF x1" in text)
ck("a dry run is shown as nothing new", "nothing new" in text)
ck("the dry tail is counted", dry == 2)
ck("...and said, with the reading left to the model",
   "THE LAST 2 RUNS YIELDED NOTHING NEW" in text and "yours to read" in text)
ck("no record, no words", A.attempt_yield_text("Reach Cinnabar Island") == ("", 0))

captured = []
reply = ['{"why": "x", "after": null}']
def fake_chat(msgs, model):
    captured.append(msgs[-1]["content"])
    return reply[0]
A.brock_probe.chat = fake_chat
A.recent_events = lambda: ""
A.done_ledger_text = lambda: ""
A.check_already_done = lambda *a, **k: False
ahead = [(36, "Obtain the Secret Key from the Secret House"), (39, "Reach Cinnabar Island")]
A.check_later("Obtain the Secret Key from the Secret House", 36, ahead, "start", "", "m")
ck("the later rung shows the record", "WHAT EACH RUN AT THIS OBJECTIVE YIELDED" in captured[-1])
reply[0] = '{"why": "x", "reword": "Obtain the Secret Key from the Warden"}'
# the same leg never reworded: two dry runs under its own name
(tmp / "run/outline_rewordings").write_text("")
(tmp / "run/attempt_yield").write_text(rows[0] + "\n" + rows[1] + "\n"
    + "Obtain the Secret Key\t36\t3\t" + NOTHING + "\n")
new = A.check_wording("Obtain the Secret Key", ahead, [], "start", "", "m", asked=("later",))
ck("the wording rung shows the record", "WHAT EACH RUN AT THIS OBJECTIVE YIELDED" in captured[-1])
ck("two dry runs: a rewrite is not on offer",
   "A REWRITE IS NOT ON OFFER" in captured[-1] and "yielded nothing new" in captured[-1])
ck("...and one that comes back is refused", new == "")
(tmp / "run/attempt_yield").write_text(rows[0] + "\n" + rows[1] + "\n"
    + "Obtain the Secret Key\t36\t3\tWHAT CHANGED WHILE THIS LEG RAN — 1 place(s) entered for the first time: ROUTE_19|6,0.\n")
new = A.check_wording("Obtain the Secret Key", ahead, [], "start", "", "m", asked=("later",))
ck("a run that gained ground keeps the rewrite open",
   "NOT ON OFFER" not in captured[-1] and new == "Obtain the Secret Key from the Warden")

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
