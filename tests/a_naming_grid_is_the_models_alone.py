#!/usr/bin/env python3
"""While the grid is up, the name is the model's — so nothing else presses.

Ten looks, nine of them guesses. The answer came from tracing every button
press with the box it landed on (2026-09-13):

    tap:a      index=1                              <- YES to the question
    tap:start  screen=NamingScreen title=NICKNAME?  <- and it is over
    tap:a      ...

The nickname question WAS being answered yes. The grid WAS opening. Some
other op reaching for the start MENU pressed START, the grid read it as
"done", committed an empty name, and closed before the model was asked.
Every earlier fix — answering the question instead of dismissing it,
publishing the screen from under a text box, keeping the UI drain off it,
stepping the dialogue on — was about getting the question TO the model. It
was arriving, and being confirmed away a frame later.

OPS.name presses START itself, legitimately, to confirm what it has typed.
So the guard is not a blanket refusal: the dispatcher raises the exemption
for the "name" op alone and lowers it again after, so no early return,
error or watchdog kill can leave it open for the next op.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

SH = (ROOT / "harness" / "shim.lua").read_text()

ck("every press goes through one place",
   "local _tap = U.tap" in SH and "U.tap = function(game, btn)" in SH)
ck("every button is refused while a naming grid is up",
   "if not naming_driver and naming_on_stack(game) then" in SH)
# Refusing START alone left the grid OPEN, and the same caller's next
# press was A — which on a letter grid types the letter under the cursor,
# and the cursor starts on "A". The starter came back AAAAAAAAAA, ten
# presses being all it takes to fill maxLen (2026-09-13).
ck("...because A on a letter grid TYPES, it does not confirm",
   "called AAAAAAAAAA" in SH)
ck("...refused outright, so the caller's own loop can try again later",
   "Refused, not deferred" in SH)
ck("...and the refusal names which button it was",
   'dlg_trace(game, "REFUSED:" .. tostring(btn), 0)' in SH)

ck("the name op is exempt, because START is its confirm",
   'naming_driver = (cmd.op == "name")' in SH)
ck("...and the exemption is lowered by the dispatcher, not the op",
   SH.split('naming_driver = (cmd.op == "name")')[1][:260]
     .count("naming_driver = false") == 1)
ck("...so no early return or watchdog kill can leave it open",
   "cannot\n      -- outlive the op that raised it" in SH)
ck("the flag starts down", "local naming_driver = false" in SH)

ck("the op still confirms with START itself",
   'U.tap(G, "start"); U.wait(10)               -- confirm (START = ED)' in SH)
ck("...and the trace itself stays opt-in",
   'local DLG_TRACE = os.getenv("RED_DIALOG_TRACE") == "1"' in SH)

# the guard has to be able to SEE a naming screen from where it is installed
ck("the guard is installed after the thing it asks",
   SH.index("local function naming_on_stack(G)")
   < SH.index("U.tap = function(game, btn)"))

ck("the file compiles",
   subprocess.run(["luac", "-p", str(ROOT / "harness" / "shim.lua")]).returncode == 0)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
