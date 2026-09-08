#!/usr/bin/env python3
"""A buy that reaches a clerk who opens no shop says so, in the interact's
own words, instead of "couldn't reach the clerk".

Celadon's department store, run 16 (2026-09-08): the 1F desk is staffed by a
CLERK who sells nothing. `buy POKE_BALL` picked her by name, walked to her,
and came back "couldn't reach the clerk" — a pathing story — so the model
went upstairs believing the Poke Ball counter was on the floor below. Now the
refusal carries the interact's own detail either way: reached-and-spoke with
no shop, or the walk's real failure. Source-anchored: the shim is Lua.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sh = (ROOT / "harness" / "shim.lua").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


i = sh.index("function OPS.buy(G, c)")
buy = sh[i:sh.index("function OPS.sell(G, c)", i)]
ck("the bare 'couldn't reach the clerk' is gone from buy", 'return false, "couldn\'t reach the clerk"' not in buy)
ck("buy keeps the interact's own detail", "local _oki, _deti = OPS.interact(G, { x = clerk.cellX, y = clerk.cellY," in buy)
ck("a clerk who spoke but opened no shop is said to sell nothing", "was reached and spoke, but opened no shop" in buy and "this \"\n          .. \"counter sells nothing" in buy)
ck("...naming the other counters on the floor", "other counters on this floor: " in buy)
ck("...and the open box is closed behind it", buy.index("ui_back_out(G)\n        return false, (_nm .. \" was reached") > 0)
ck("a walk that really failed says so with the reason", '"couldn\'t reach " .. _nm .. (_d ~= "" and (" — " .. _d) or "")' in buy)
j = sh.index("function OPS.sell(G, c)")
ck("sell got the same treatment", "was reached and spoke, but opened no shop" in sh[j:j + 12000])
sys.exit(1 if fails else 0)
