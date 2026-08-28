#!/usr/bin/env python3
"""The author of a leg is shown that objective's own history.

The rungs that judge a leg read its lineage, yield record and new
ground; the author that writes the leg read none of it, so "Obtain the
Secret Key", moved by hand to after Cinnabar after six runs in the
Safari Zone, was authored a seventh time as a walk to the Secret House
(2026-08-28). Same record, same model, before it writes.
"""
from __future__ import annotations
import os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A            # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
tmp = Path(tempfile.mkdtemp(prefix="hist_")); (tmp / "run").mkdir(); os.chdir(tmp)
G = "Obtain the Secret Key"
NOTHING = "NOTHING new while this leg ran: no event fired, no item or badge was gained, and no new place was entered."
(tmp / "run/attempt_yield").write_text(
    f"{G}\t30\t1\tWHAT CHANGED WHILE THIS LEG RAN — items gained: HM_SURF x1; 4 place(s) entered for the first time — by map: SAFARI_ZONE_WEST x2, SAFARI_ZONE_SECRET_HOUSE x1, SAFARI_ZONE_NORTH x1.\n"
    f"{G}\t36\t3\t{NOTHING}\n{G}\t36\t3\t{NOTHING}\n"
    f"{G}\t36\t0\tDISPOSED: moved BY HAND to after leg 39 Reach Cinnabar Island\n")
(tmp / "run/outline_rewordings").write_text(f"36\tObtain the Secret Key from the Warden\t{G}\n")
A.recent_events = lambda: ""
A.outline_so_far = lambda *a, **k: ""
A.done_ledger_text = lambda *a, **k: ""
t = A.objective_history_text(G + " (a doubt you recorded when outlining: something)")
ck("the doubt suffix is stripped before the lookup", "THIS OBJECTIVE HAS BEEN TRIED BEFORE" in t)
ck("the author sees the lineage", "AS YOU FIRST WROTE IT" in t)
ck("...the yield record, dry runs included", "WHAT EACH RUN AT THIS OBJECTIVE YIELDED" in t and "nothing new" in t)
ck("...the disposition", "moved BY HAND to after leg 39" in t)
ck("...and where the walking went", "GROUND THIS OBJECTIVE'S RUNS WALKED" in t and "SAFARI_ZONE_WEST x2" in t)
prompt = A.build_prompt(G, "standing in FUCHSIA_CITY")
ck("build_prompt carries it", "THIS OBJECTIVE HAS BEEN TRIED BEFORE" in prompt)
ck("an objective never tried gets no such section", A.objective_history_text("Defeat Blaine") == "")
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
