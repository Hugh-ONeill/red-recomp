#!/usr/bin/env python3
"""A fishing rod in the bag is a grind from the shore, and the page says so.

Run 16, leg 32 (2026-09-08): the run took the Good Rod and had no verb for
it. It tried interact(name=GOOD_ROD), then use_item, whose text loop rides a
"Not even a nibble!" out cleanly but would tap A into the battle a bite
starts (the flute's fight began the same way, under the item's own menu).
Now {"op":"grind","rod":"GOOD_ROD"} walks to the nearest reachable cell with
seen water beside it, faces the water, casts from the bag as many times as
the budget allows, and a bite is a battle the executor fights under the op's
own intent and want, re-sending the op as it does for every grind. use_item
with a rod goes the same way; the bag line, the op catalogue and the
knows-move page name the verb; a grassless map with water and a rod held
says so instead of "no wild Pokemon live on this map". Source-anchored.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "harness" / "shim.lua").read_text()
ex = (ROOT / "planner" / "executor.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


i = sh.index("local function fish_from_shore(G, c)")
fish = sh[i:sh.index("function OPS.grind(G, c)", i)]
ck("grind dispatches a rod to the shore", 'if c.rod ~= nil or c.fish then\n    return fish_from_shore(G, c)' in sh)
ck("the rod is checked against the bag, naming what is held", 'return false, "no " .. rod .. " in the bag"' in fish and "you hold " in fish)
ck("a rod from the water is refused in the game's own words", "OAK: This isn't the time to use that!" in fish and "p.surfing" in fish)
ck("a SUPER_ROD on a map with no group of its own is refused before the walk", 'rdef.perMap' in fish and 'gives the %s nothing' in fish)
ck("...and never names a species", "GOLDEEN" not in fish and "POLIWAG" not in fish and "MAGIKARP" not in fish)
ck("the shore is the nearest reachable cell beside seen water", "seen_reach(G)" in fish and "real_water(G, map, wx, wy)" in fish and "_gm[wx" in fish)
ck("it walks there and faces the water", "OPS.walk_to(G, { x = bland[1], y = bland[2]" in fish and "if p.facing ~= bland[3] then U.tap(G, bland[3])" in fish)
ck("a cast is the bag's own USE, not a party picker", "bag_use(G, rod)" in fish and "PartyMenu" not in fish)
ck("a bite stops at the battle and says so", "(t.enemy or t.kind) then break" in fish and "a battle began" in fish)
ck("the wipe counts as the battle too", "BattleTransition" in fish)
ck("a menu left up is backed out, never tapped through", "ui_back_out(G)                      -- a menu is not the verdict" in fish)
ck("no nibble is said as chance, with the count and where you stood", 'cast the %s %d time(s) from (%d,%d) facing %s' in fish and "nothing bit. A bite is chance, not a wall" in fish)
ck("the game's not-near-water refusal is passed through with the facing", "not even near water" in fish and "the cell in front" in fish)
j = sh.index("function OPS.use_item(G, c)")
use = sh[j:j + 3000]
ck("use_item with a rod is the same grind", 'OPS.grind(G, { rod = c.item, casts = c.casts' in use and "fishing is a grind" in use)
k = sh.index("function OPS.grind(G, c)")
grind = sh[k:k + 12000]
ck("a grassless map with water and a rod names the verb", "but it has WATER and you hold a " in grind and "casts it from the shore" in grind)
ck("...and the bare refusal now says GROUND", "no wild Pokemon live on this map's GROUND" in grind)
ck("water with nothing to surf into still names the rod you hold", "holds no wild Pokemon to SURF into" in grind and "but a ROD hooks from a table of its own" in grind)
# the executor's pages
ck("the op catalogue names the rod option beside surf", 'Add "rod":"GOOD_ROD" (or\nOLD_ROD / SUPER_ROD' in ex and "a bite is a wild battle like any other" in ex)
ck("the knows-move page names fishing as a way to a different Pokemon", 'with a rod in the "\n                f"bag, FISHED' in ex)
ck("the bag line carries the verb on a rod", "def _rod_note(item: str)" in ex and '{self._rod_note(k)}' in ex and 'if item in ("OLD_ROD", "GOOD_ROD", "SUPER_ROD"):' in ex)
ck("grind stays a traversal, so a bite's battle re-sends the op", 'traversal = op in ("cross", "walk_to", "use_warp", "grind", "sweep")' in ex)
sys.exit(1 if fails else 0)
