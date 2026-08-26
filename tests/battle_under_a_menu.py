"""A battle under a menu is still a battle (2026-08-26).

`use_item(POKE_FLUTE)` woke ROUTE12_SNORLAX — "SNORLAX woke up! It attacked in
a grumpy rage!" — and the fight began UNDER the item's own PartyMenu. Every
battle test in shim.lua asked `G.stack:top()`, so:

  * observe() called it mode=ui, and the executor's battle policy was never
    handed the fight;
  * need_overworld() tried to B out of the menu and reported "not in overworld
    (a box was up and would not close: PartyMenu)";
  * in_battle() answered nil, so every battle op said "not in battle".

The run then sat in escalate_repeat_refused (user: "it started a battle but
the policy isnt handling it"). StateStack keeps every frame in `states`."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

lua = Path("harness/shim.lua").read_text()

ck("the stack is scanned for a battle frame",
   "local function battle_frame(G)" in lua)
b = lua[lua.find("local function battle_frame(G)"):][:700]
ck("...over StateStack's own frame list", "G.stack.states" in b)
ck("...top-down", "for i = #st, 1, -1 do" in b)
ck("...on .enemy only, so a shop is never called a battle",
   "f.enemy ~= nil" in b and ".kind" not in b.split("for i =")[1])

ck("it is declared before its users",
   lua.index("local function battle_frame(G)") < lua.index("local function need_overworld")
   and lua.index("local function battle_frame(G)") < lua.index("local function in_battle"))

# need_overworld
n = lua[lua.find("local function need_overworld"):][:700]
ck("need_overworld leaves a menu that sits on a battle alone",
   "if battle_frame(G) then return false end" in n)

# observe
ck("observe reports the fight, not the menu",
   'elseif battle_frame(G) then' in lua
   and 'o.mode = "battle"' in lua)
o = lua[lua.find("elseif battle_frame(G) then"):][:800]
ck("...and still names what is on top",
   "behind_a_menu = _screen_name(G)" in o)
ck("...placed after the dialog branch so text still reads as text",
   lua.index('o.mode = "dialog"') < lua.index("elseif battle_frame(G) then"))
ck("...and before the plain ui branch",
   lua.index("elseif battle_frame(G) then") < lua.index('o.mode = "ui"'))

# in_battle
i = lua[lua.find("local function in_battle(G)"):][:1400]
ck("battle ops can see a battle under a menu", "battle_frame(G)" in i)
ck("...backing out with B, which is the battle's own go-back",
   'U.tap(G, "b")' in i and "if G.stack:top() == f then break end" in i)
ck("...and refusing exactly as before if it will not come off",
   "return (G.stack:top() == f) and f or nil" in i)
ck("a battle already on top is untouched",
   "if b and (b.enemy or b.kind) then return b end" in i)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
