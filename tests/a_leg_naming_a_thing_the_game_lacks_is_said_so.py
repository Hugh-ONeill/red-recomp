#!/usr/bin/env python3
"""A leg naming an HM/TM this game does not have is said so wherever the
rungs read it, the validator does not swap in another item for it, and
the chain asks the wording rung before authoring it.

"Retrieve the HM08 from the Victory Road warden", 2026-08-28: it steered
a blocker pull, a missing-rung answer, a later-rung move and, once
authored ("did you mean HM_FLY, HM_CUT?"), a walk to Fuchsia for HM_FLY.
"""
from __future__ import annotations
import io, json, sys, contextlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A          # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
L = "Retrieve the HM08 from the Victory Road warden"
line = A._leg_line(47, L)
ck("an outline line names the missing thing on the line", line.startswith("  47. Retrieve the HM08")
   and "names a thing this game does not have: there is no HM08 in this game" in line)
ck("...and an ordinary line is untouched", A._leg_line(48, "Reach the Indigo Plateau") == "  48. Reach the Indigo Plateau")
probs = " || ".join(A.validate({"goal": L, "subgoals": [
    {"id": "talk_to_warden", "done_when": {"has_item": {"HM08": 1}}, "steps": []}]}))
ck("the validator says there is no such item, with the game's list", "there is no HM08 in this game" in probs and "HM_STRENGTH" in probs)
ck("...and offers no stand-in", "did you mean" not in probs and "not a stand-in" in probs)
probs2 = " || ".join(A.validate({"goal": "x", "subgoals": [
    {"id": "a", "done_when": {"has_item": {"POKEBALL": 1}}, "steps": []}]}))
ck("a plain misspelling still gets spelling help", "did you mean" in probs2)
seen = {}
def chat(msgs, model):
    seen["body"] = msgs[-1]["content"]; return "{}"
A.brock_probe.chat = chat
for name in ("_reword_history", "recent_events", "done_ledger_text"):
    setattr(A, name, lambda *a, **k: "")
A.attempt_yield_text = lambda goal: ("", 0)
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    A.check_wording(L, [(47, "Reach the Indigo Plateau")], [], "start", "", "m", asked=["phantom"])
ck("the wording rung is told the fact at the top", "THIS OBJECTIVE NAMES A THING THE GAME DOES NOT HAVE: there is no HM08" in seen.get("body", ""))
ck("...and what was asked", "does the game have the thing it names? — no" in seen.get("body", ""))
sh = (ROOT / "fresh_discovery.sh").read_text()
ck("the chain asks the wording rung before authoring such a leg",
   "--phantom --goal \"$leg\"" in sh and 'wording_rung "phantom"' in sh
   and sh.index('wording_rung "phantom"') < sh.index('echo "=== leg $i/${#LEGS[@]}: authoring — $goal"'))
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
