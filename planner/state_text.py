"""Where the party actually stands, as one line for a re-author's --start.

Extracted from campaign.sh so the outline chain and the replan loop
describe the world with the same words. Mechanical save-reading only —
manual-tier under CLAIM_RULES.
"""
import json

# last_state.json is written by the executor as it exits, so it OUTLIVES the
# game process; obs.json belongs to the live bridge and is gone by the time
# the re-author runs.
o = None
for src in ("run/last_state.json", "run/obs.json"):
    try:
        o = json.load(open(src))
        break
    except Exception:
        continue
if o is None:
    print("a brand new game")
    raise SystemExit


# HP reaches the start text: the audit's ALREADY DONE check pruned
# buy_potions because the bag was visible here, but kept every heal leg —
# and the Pewter round trip serving them — because health never was.
def mon_text(p):
    s = f"{p.get('species')} L{p.get('level')}"
    hp, mx = p.get("hp"), p.get("max_hp")
    if hp is not None and mx:
        s += f" {hp}/{mx}hp"
    st = str(p.get("status") or "")
    if st not in ("", "0", "NONE", "OK"):
        s += f" {st}"
    return s


def party_text(mons):
    txt = ", ".join(mon_text(p) for p in mons)
    full = [p for p in mons if p.get("max_hp")]
    if full and all(p.get("hp") == p.get("max_hp") for p in full):
        txt += " (party at full HP)"
    return txt


def bag_text(bagd):
    txt = (", ".join(f"{k} x{v}" for k, v in (bagd or {}).items())
           or "an empty bag")
    n = len(bagd or {})
    # the 20-kind cap is a wall the plan must plan around: a full bag
    # eats every gift silently, so its fullness belongs in the one line
    # every author and reviewer reads
    if n >= 20:
        txt += (" — the bag is FULL (20 of 20 kinds; gifts and pickups "
                "FAIL until something is used, sold or tossed)")
    elif n >= 18:
        txt += f" — the bag is NEARLY FULL ({n} of 20 kinds)"
    return txt


if "region" in o:                    # last_state.json is already flattened
    m = o.get("map")
    party = party_text(o.get("party") or [])
    badges = ", ".join(o.get("badges") or []) or "no badges"
    bag = bag_text(o.get("bag"))
    print(f"standing in {m or 'an unknown location'} with "
          f"{party or 'no party'}, {badges}, and {bag}")
    raise SystemExit
m = (o.get("map") or {}).get("id")
if not m:                      # stale/missing obs: say so rather than
    print("an unknown location")   # inventing "standing in None"
    raise SystemExit
party = party_text(o.get("party") or [])
badges = ", ".join(o.get("badges") or []) or "no badges"
bag = bag_text(o.get("bag"))
print(f"standing in {m} with {party or 'no party'}, {badges}, and {bag}")
