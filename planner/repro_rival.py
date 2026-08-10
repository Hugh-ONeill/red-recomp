#!/usr/bin/env python3
"""Isolate the credits-after-rival anomaly.

Reach the rival battle, then force a chosen OUTCOME and log the exact
post-battle state transition (mode + screenId every step). --lose spams a
no-damage move (TAIL_WHIP) until Squirtle faints; --win spams Tackle.
The question: does a single-mon whiteout route to Hall of Fame -> Credits?

Usage: repro_rival.py [--lose|--win]
"""
import json
import sys
from bridge import Bridge

b = Bridge()
LOSE = "--win" not in sys.argv


def clear(maxn=15):
    for _ in range(maxn):
        o = b.obs()
        if o["mode"] != "dialog":
            return o
        b.send("tap", btn="a")
    return b.obs()


def to_overworld_map(target, tries=10):
    for _ in range(tries):
        clear()
        o = b.obs()
        if o["mode"] == "overworld" and (o.get("map") or {}).get("id") == target:
            return o
        b.send("mash_a", times=20)
    return b.obs()


def log(tag):
    o = b.obs()
    ui = o.get("ui") or {}
    sid = ui.get("screenId") or o.get("mode")
    party = [(m["species"], m["hp"]) for m in o.get("party", [])]
    print(f"  [{tag}] mode={o['mode']} screen={sid} party={party}"
          f" events={o.get('events')}")
    return o


print("=== bootstrap ===")
b.send("new_game")
for _ in range(6):
    if b.send("mash_a", times=30)["mode"] == "overworld":
        break
# out of the house
b.send("walk_to", x=7, y=1); b.send("wait", frames=40)
b.send("walk_to", x=2, y=7); b.send("walk", dir="down", steps=1)
b.send("wait", frames=40)
# trigger Oak at the north edge, ride the escort into the lab
b.send("walk_to", x=10, y=0, max_steps=80)
to_overworld_map("OAKS_LAB", tries=14)
print("=== in lab, picking Squirtle ===")


def have_party():
    return len(b.obs().get("party", [])) > 0


for pick_try in range(4):
    if have_party():
        break
    clear()
    b.send("walk_to", x=7, y=4)          # in front of Squirtle ball
    b.send("tap", btn="up")
    b.send("tap", btn="a")               # interact -> DexEntryMenu preview
    # advance until a yes/no box (a ui with numeric index) appears
    got_choice = False
    for _ in range(20):
        o = b.obs()
        ui = o.get("ui") or {}
        if o["mode"] == "ui" and isinstance(ui.get("index"), int) \
                and ui.get("screenId") is None:
            got_choice = True
            break
        b.send("tap", btn="a"); b.send("wait", frames=6)
    if got_choice:
        b.send("menu", index=1)          # YES
    # clear "received" text, skip the nickname screen
    for _ in range(20):
        o = b.obs()
        if (o.get("ui") or {}).get("screenId") == "NamingScreen":
            b.send("tap", btn="start"); b.send("tap", btn="a")
        elif o["mode"] == "dialog":
            b.send("tap", btn="a")
        else:
            break
print("  party:", [(m["species"], m["hp"]) for m in b.obs().get("party", [])])
if not have_party():
    sys.exit("starter pick failed")

print("=== trigger rival battle ===")
for _ in range(6):
    clear()
    if b.obs()["mode"] == "battle":
        break
    b.send("walk_to", x=5, y=9, max_steps=15)
    clear()
    if b.obs()["mode"] == "battle":
        break
    b.send("walk_to", x=4, y=11, max_steps=15)
o = b.obs()
print("  battle mode:", o["mode"])
if o["mode"] != "battle":
    sys.exit("did not reach the rival battle")

move = 2 if LOSE else 1  # 2=TAIL_WHIP (no damage -> we lose), 1=TACKLE
print(f"=== fighting to {'LOSE' if LOSE else 'WIN'} (move index {move}) ===")
for turn in range(1, 25):
    o = b.obs()
    if o["mode"] != "battle":
        break
    me = o["battle"].get("me", {})
    foe = o["battle"].get("foe", {})
    print(f"  turn {turn}: me {me.get('hp')} foe {foe.get('hp')}")
    b.send("battle_move", index=move)

print("=== POST-BATTLE TRANSITION ===")
for step in range(30):
    o = log(step)
    if o["mode"] == "overworld":
        print("  -> settled in overworld:", (o.get("map") or {}).get("id"))
        break
    if (o.get("ui") or {}).get("screenId") in ("Credits", "HallOfFame"):
        print("  -> !!! HALL OF FAME / CREDITS reached !!!")
        break
    b.send("tap", btn="a")
