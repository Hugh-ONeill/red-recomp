#!/usr/bin/env python3
"""A naming screen is a question, not an obstacle to clear.

The game offers ready-made names and a default, and taking one is the
quickest way to make the screen go away. So the run took RED, then BLUE,
then GARY, every time — and across every journal this repo keeps, NOT ONE
Pokemon has ever been nicknamed. The two paths that could have produced a
nickname both leak: the catch flow in the shim answers the "give a
nickname?" box YES and hands the screen over correctly, but a GIFT and a
revived FOSSIL raise that same box through the executor's yes/no branch,
where it was answered on the merits — and saying no costs nothing and ends
the box.

NOT A TRADE, THOUGH. An in-game trade is never asked about: Commands.lua
sets `newMon.nickname = trade.nickname` straight off the trade table, so
the DUGTRIO comes back called GURIO whatever anyone wanted, and a gift
that ships with a nickname of its own skips the question the same way
(`if gift.nickname then ... end`, and the prompt is gated on `not
gift.nickname`). Only the ones the game actually asks about can be named
(user, 2026-09-12: "you cant rename a traded pokemon"). Named here because
this file first claimed otherwise, and a test that states a falsehood
about the game pins it.

(user, 2026-09-12: "I want to see what nicknames it actually chooses for
things instead of simply trying to complete the objective of choosing a
name as swiftly and thoughtlessly as possible". It is also a REQUIREMENT
of the nuzlocke rules a later run will play under.)

So: the nickname box is always accepted, the menu names are shown as what
NOT to send rather than as a shortcut, and a reply that is blank or off
the menu is put back with the reason. WHAT to call it was always the
model's and still is — nothing here proposes a name.

The old behaviour is one environment variable away, because a naming
screen nobody can get past would wedge a run, and that rule is older than
this one.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                       # noqa: E402
import brock_probe as B                                    # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

STARTER = {"naming": {"title": "CHARMANDER's NICKNAME?", "max": 10,
                      "presets": [], "default": "CHARMANDER"},
           "party": [{"species": "CHARMANDER", "level": 5}]}
PLAYER = {"naming": {"title": "YOUR NAME?", "max": 7,
                     "presets": ["NEW NAME", "RED", "ASH", "JACK"],
                     "default": "RED"},
          "party": []}


def stub(*replies):
    """A model that says these things in order, recording what it was told."""
    seen = []
    it = iter(replies)

    def chat(msgs, model, **k):
        seen.append(msgs[-1]["content"])
        try:
            return next(it)
        except StopIteration:
            return replies[-1]
    B.chat = chat
    return seen


# ---- the prompt says what is wanted -------------------------------------
seen = stub('{"name":"Ignis"}')
ck("a name of its own is taken as given",
   E.ask_name(STARTER, "stub") == "Ignis")
ck("...and the page asked for one",
   "A NAME OF YOUR OWN" in seen[0])
ck("...naming the default as NOT an option",
   "ALSO NOT FOR YOU" in seen[0])

seen = stub('{"name":"SAGE"}')
E.ask_name(PLAYER, "stub")
ck("the menu names are still listed, because they are on the screen",
   "RED" in seen[0] and "ASH" in seen[0])
ck("...but listed as what to avoid",
   "NOT FOR YOU" in seen[0] and "what to avoid" in seen[0])

# ---- a name off the menu is put back ------------------------------------
seen = stub('{"name":"RED"}', '{"name":"SAGE"}')
ck("a ready-made name is refused and asked again",
   E.ask_name(PLAYER, "stub") == "SAGE" and len(seen) == 2)
ck("...and the second ask says what came back",
   "YOUR LAST ANSWER WAS" in seen[1] and "RED" in seen[1])

seen = stub('{"name":""}', '{"name":"Thistle"}')
ck("an empty reply is refused and asked again",
   E.ask_name(STARTER, "stub") == "Thistle"
   and "YOUR LAST ANSWER WAS empty" in seen[1])

seen = stub('{"name":"CHARMANDER"}', '{"name":"Ignis"}')
ck("the species shouted back is not a nickname either",
   E.ask_name(STARTER, "stub") == "Ignis" and len(seen) == 2)

seen = stub('{"name":"CHARMANDER"}')
ck("...but three refusals let the game's default stand, never a wedge",
   E.ask_name(STARTER, "stub") == "CHARMANDER" and len(seen) == 3)

# ---- it is still typed the way the grid can type it ---------------------
seen = stub('{"name":"Sir Reginald Fluffington III"}')
ck("a name is cut to the screen's own limit",
   len(E.ask_name(STARTER, "stub")) == 10)
seen = stub('{"name":"Zap\\u2764\\u2764"}')
ck("...and characters the grid has no key for are dropped",
   E.ask_name(STARTER, "stub") == "Zap")

# ---- the old behaviour is one variable away -----------------------------
E.NICKNAMES_REQUIRED = False
try:
    seen = stub('{"name":"RED"}')
    ck("with it off, a ready-made name is taken and asked once",
       E.ask_name(PLAYER, "stub") == "RED" and len(seen) == 1)
    ck("...and the page offers the menu as a shortcut again",
       "picks it" in seen[0])
finally:
    E.NICKNAMES_REQUIRED = True

SRC = (ROOT / "planner" / "executor.py").read_text()
ck("the switch is an environment variable, default on",
   'os.environ.get("RED_NICKNAMES", "1") != "0"' in SRC)

# ---- the box that guards the screen ------------------------------------
ck("a nickname question is answered yes without being weighed",
   'if NICKNAMES_REQUIRED and "nickname" in str(text or "").lower():' in SRC)
ck("...and the naming screen behind it is then driven",
   SRC.split('a nickname is always accepted')[1][:400].count(
       "_resolve_naming") == 1)
ck("every other yes/no box is still the model's to judge",
   "ans = self._ask_question(obs, sg, text)" in SRC)

# ...AND THE QUESTION ARRIVES LATE. The op that brings the Pokemon returns
# as soon as it has pressed its button; the engine then plays "CHARMANDER!
# I choose you!" and only THEN asks. A single glance sees an overworld with
# no box, moves on, and the next thing to touch the UI presses B — which is
# NO. Run 17's starter arrived un-named four minutes after this file was
# written (2026-09-13). The catch flow had already learned the same lesson
# in its own words: wait on the PARTY, not on a frame count.
ck("a party that just grew is waited on, not glanced at",
   "_grew = _pn > getattr(self, \"_party_n\", _pn)" in SRC
   and "for _try in range(12 if (_grew and NICKNAMES_REQUIRED) else 1):" in SRC)
_LOOP = SRC.split("for _try in range(12 if", 1)[1][:2200]
ck("...and the wait ends the moment the question appears",
   'if "nickname" in _t and o.get("mode") in ("dialog", "ui"):' in _LOOP
   # the branch now places the cursor, presses, re-observes and THEN
   # breaks, so the break sits further down than it used to
   and _LOOP.split('if "nickname" in _t')[1][:900].count("break") >= 1)
# last_text OUTLIVES ITS BOX, so the mode guard is what stops a nickname
# answered ten rounds ago sending a stray A into whatever is on screen now.
# Re-observing each pass is what makes the WAIT safe; dropping the guard
# would not have (2026-09-13).
ck("...and a stale line cannot fire it, because the box must be up",
   'o.get("mode") in ("dialog", "ui")' in SRC)
ck("...and gives up rather than waiting out an arrival that never asks",
   "range(12 if (_grew and NICKNAMES_REQUIRED) else 1)" in SRC)

# WAITING IS NOT ADVANCING, and that is why five fixes in a row missed the
# box. The starter script plays "_OaksLabReceivedMonText" — a text box
# that waits on an A press — and only THEN does give_pokemon raise the
# nickname question behind it. A loop that sleeps twelve times sits on
# "you received CHARMANDER" for all twelve. The journal said so plainly
# every time: party_grew asked=false, and the word "nickname" nowhere in
# it (2026-09-13).
ck("the wait steps the dialogue on rather than sleeping through it",
   'self._send_safe("tap", btn="a")) or o' in SRC
   and 'o.get("mode") == "dialog"' in SRC)
ck("...but only a plain text box, never a choice pressed blind",
   'and not _ui.get("is_choice")' in SRC)
ck("...and still sleeps when there is no box to step",
   'self._send_safe("wait", frames=6)' in SRC)
ck("the YES puts the cursor on YES instead of pressing blind",
   'self._send_safe("menu", index=1)' in SRC
   and "takes whatever the cursor happens to be on" in SRC)

# ...AND THE DRAIN THAT PRESSES B IS WHERE IT ACTUALLY WENT. Two guards
# sat further up and neither held for the starter: _ask_question needs the
# box to read as a CHOICE, and settle's wait needs to run before anything
# else touches the screen. Run 17 logged party_grew with asked=false after
# twelve polls, and the word "nickname" never appeared in its journal
# once, because the UI drain had already pressed B — which is No
# (2026-09-13, the third attempt at this fix). A loop that dismisses boxes
# is the LAST thing to see one, so it has to check too.
ck("the drain never presses B on a nickname box",
   'if NICKNAMES_REQUIRED and "nickname" in _nt:' in SRC)
ck("...it presses A instead and drives the screen behind it",
   SRC.split('if NICKNAMES_REQUIRED and "nickname" in _nt:')[1][:400]
      .count("_resolve_naming") == 1)
ck("...and says where it caught it",
   'where="ui_drain"' in SRC)
ck("every OTHER box is still dismissed with B as before",
   'self.b.send("tap", btn="b")' in SRC)

# ---- the catch path already did this, and still does -------------------
SH = (ROOT / "harness" / "shim.lua").read_text()
ck("the shim's throw still answers the nickname box YES",
   '-- "give a nickname?" — YES:' in SH
   and "the name is the model's to give" in SH)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
