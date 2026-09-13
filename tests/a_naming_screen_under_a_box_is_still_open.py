#!/usr/bin/env python3
"""Six attempts at one bug, and the fact it needed was withheld by the shim.

Run 17 caught two PIKACHU and a NIDORAN and took a CHARMANDER, and named
none of them. Every time the journal said the same thing: party_grew with
asked=false, and the word "nickname" nowhere in it (2026-09-13, user:
"ended up with two pikachus? neither of them named though").

Five fixes went into the PLANNER — a wait after the party grows, a guard in
the yes/no branch, a guard in the UI drain, stepping the dialogue on
instead of sleeping through it. Each was a real improvement and none of
them could have worked, because the observation they all read was hiding
the thing they were looking for.

The mode chain reports what is ON TOP and tests TextBox before naming. So
after a catch, while "Gotcha! PIKACHU was caught!" and the dex page still
ride above it, o.naming was nil. The shim's own throw_ball answers the
nickname box and breaks on naming_on_stack — a STACK check, which saw it
perfectly — and the executor then asked the OBSERVATION and was told there
was nothing to name.

mode still says what is on top, because a text box is a text box and has
to be advanced. What changed is that the question behind it is no longer
invisible. OPS.name reads the stack directly and types fine from there.
"""
from __future__ import annotations
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

SH = (ROOT / "harness" / "shim.lua").read_text()
EX = (ROOT / "planner" / "executor.py").read_text()

# ---- the publication ----------------------------------------------------
tail = SH.split('o.mode = "boot"', 1)[1][:1600]
ck("a naming screen is published even when it is not on top",
   "if not o.naming then" in tail and "local _ns = naming_on_stack(G)" in tail)
ck("...from the same stack check the ops use",
   "o.naming = naming_fields(G, _ns)" in tail)
ck("...and says what is riding above it",
   "o.naming.behind = _screen_name(G)" in tail)
ck("mode is left alone: a text box still reads as a text box",
   'o.mode = "dialog"' in SH
   and 'o.mode = "dialog"' not in tail.split("if not o.naming")[1])

# the on-top branch is untouched, so nothing regresses for the plain case
ck("the on-top naming branch still sets mode and ui",
   'elseif naming_on_stack(G) then' in SH
   and "o.ui.naming = naming_fields(G, ns)" in SH)

# ---- the readers that were standing down -------------------------------
ck("settle drives the screen when the observation shows one",
   'if o.get("naming") and not getattr(self, "_naming", False):' in EX)
ck("a catch drives it too, straight after the battle",
   'if (obs or {}).get("naming"):' in EX
   and "_resolve_naming" in EX.split('if (obs or {}).get("naming"):')[1][:200])
ck("the planner-side wait still breaks the moment it appears",
   'if o.get("naming"):' in EX)

# ---- the op does not care what is on top -------------------------------
nameop = SH.split("function OPS.name(G, c)", 1)[1][:400]
ck("the name op asks the STACK, not the observation",
   "local ns = naming_on_stack(G)" in nameop)
ck("...and refuses only when there is genuinely no screen",
   'return false, "no naming screen is open"' in nameop)
ck("...and rides whatever text is above it",
   'U.tap(G, "a")' in SH.split("function OPS.name(G, c)", 1)[1][:1200])

# ---- and the shim's catch path still answers the box -------------------
ck("throw_ball still says YES for itself",
   '-- "give a nickname?" — YES:' in SH)

# ---- THE PRESS THAT WAS EATING IT, found on the seventh attempt --------
# ui_back_out has always protected the naming SCREEN. The QUESTION that
# opens it — "Do you want to give a nickname to X?" — is a TextBox with a
# choice riding on it, which exists BEFORE that screen, and B on a choice
# is No. Every op calls need_overworld, need_overworld calls this, so the
# question was answered No inside an op's preamble before any observation
# was taken. Five planner fixes and one observation fix could none of them
# have worked (2026-09-13).
bo = SH.split("ui_back_out = function(G)", 1)[1][:3400]
ck("the naming SCREEN is still never touched",
   "if naming_on_stack(G) then return false end" in bo)
ck("the QUESTION is answered rather than dismissed",
   'if _tx:find("nickname", 1, true) then' in bo)
ck("...with YES, by placing the cursor, not a blind press",
   'ui_cursor_to(G, "index", 1)' in bo and "row 1 is YES" in bo)
ck("...and hands over the screen it opens",
   bo.split('_tx:find("nickname"')[1][:300].count("naming_on_stack") == 1)
ck("every other box is still closed with B",
   'U.tap(G, "b"); U.wait(6)' in bo)
ck("...and the loop still has somewhere to continue to",
   "::continue::" in bo)
# TextBox.lua pushes a SEPARATE ChoiceBox once the last page types out, so
# the top has an index and no pages and the words are on the box below it.
# Reading t.pages here matched nothing, which was attempt eight.
ck("the box on top is the choice, with no pages of its own",
   "t.index ~= nil and t.pages == nil" in bo)
ck("...and the words come from the speech still showing under it",
   'tostring(last_text or ""):lower()' in bo)

ck("the file compiles",
   subprocess.run(["luac", "-p", str(ROOT / "harness" / "shim.lua")]).returncode == 0)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
