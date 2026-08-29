#!/usr/bin/env python3
"""The naming screen is a question for the model, not a box to mash.

Player, rival, caught and gift Pokemon all used to be named by whatever
key the harness was tapping (A picks the letter under the cursor, which
starts on A: AAAAAAA). Guards: the shim reports a naming screen wherever
it sits on the stack (mode "ui", naming fields, never "battle" even after
a catch); settle_dialog and ui_back_out stop instead of typing; a catch
answers YES to the nickname and hands the grid over; new_game stops at
the first name; {"op":"name","text":...} drives the grid (rows, columns,
case page, START to confirm) and rides the dialogue after; the executor
asks the model with the title, the newest party member and the presets,
sanitises the reply to the grid's letters, and resolves names in settle
and at bootstrap; an unreadable reply keeps the default rather than
wedging.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sh = (ROOT / "harness" / "shim.lua").read_text()
checks = []
def ck(name, ok): checks.append((name, bool(ok)))

ck("the shim finds a naming screen anywhere on the stack",
   "local function naming_on_stack(G)" in sh and 'type(s.glyphs) == "table" and s.maxLen' in sh)
ck("a naming screen is reported as ui with its fields, before the battle branch",
   sh.index("elseif naming_on_stack(G) then\n") < sh.index("elseif battle_frame(G) and not learn_on_stack(G) then")
   and "o.ui.naming = naming_fields(G, ns)" in sh and "o.naming = o.ui.naming" in sh)
ck("settle_dialog and ui_back_out stop instead of typing",
   "if naming_on_stack(G) then return true, naming_words(G) end" in sh
   and "if naming_on_stack(G) then return false end" in sh)
ck("a catch says YES to the nickname and hands the grid over",
   'ui_cursor_to(G, "index", 1)           -- the name is the model\'s to give' in sh
   and "if naming_on_stack(G) then asked_name = true; break end" in sh)
ck("new_game stops at the first name",
   'return true, "new game: " .. naming_words(G)' in sh)
ck("the name op drives the grid: case page, rows then columns, START confirms, then rides",
   "function OPS.name(G, c)" in sh and 'U.tap(G, "select")' in sh
   and "local function naming_move_to(G, ns, r, col)" in sh
   and 'U.tap(G, "start"); U.wait(10)               -- confirm (START = ED)' in sh
   and "local function ride(said)" in sh)
ck("...presets are picked by name, else NEW NAME",
   "return ride((\"picked the ready-made name" in sh
   and 'ui_cursor_to(G, "index", 1); U.tap(G, "a"); U.wait(10)   -- NEW NAME' in sh)
ck("the observation carries the names given",
   "o.player_name = tostring(_pl.name)" in sh and "o.rival_name = tostring(_pl.rival)" in sh)

import executor as E   # noqa: E402
obs = {"naming": {"title": "NICKNAME?", "max": 10, "presets": None},
       "party": [{"species": "PIDGEY", "level": 3}, {"species": "RATTATA", "level": 4}]}
p = E._naming_prompt(obs)
ck("the prompt says what is being named (the newest party member) and the limit",
   "NICKNAME?" in p and "RATTATA L4" in p and "UP TO 10" in p)
p2 = E._naming_prompt({"naming": {"title": "YOUR NAME?", "max": 7, "presets": ["RED", "ASH", "JACK"]}})
ck("...and the presets for the player's own name", "your own name" in p2 and "RED, ASH, JACK" in p2)
E.brock_probe.chat = lambda msgs, model: '{"name": "Sir Ratty III <3"}'
ck("the reply is sanitised to the grid's letters and cut to the limit",
   E.ask_name(obs, "m") == "Sir Ratty ")
E.brock_probe.chat = lambda msgs, model: "no json here"
ck("an unreadable reply keeps the default", E.ask_name(obs, "m") == "")
E.brock_probe.chat = lambda msgs, model: (_ for _ in ()).throw(RuntimeError("down"))
ck("a model error keeps the default rather than wedging", E.ask_name(obs, "m") == "")
ck("no model, no call", E.ask_name(obs, None) == "")
ex = (ROOT / "planner" / "executor.py").read_text()
ck("settle resolves a naming screen; bootstrap resolves the new game's names",
   'if o.get("naming") and not getattr(self, "_naming", False):' in ex
   and 'if "asking for a NAME" in str(r.get("detail") or ""):' in ex
   and 'globals()["NAMING_MODEL"] = args.model' in ex)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
