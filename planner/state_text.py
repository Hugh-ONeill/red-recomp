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

# A SNAPSHOT WITH NO PARTY IS NOT THIS WORLD. An attempt that dies in
# bootstrap still leaves a state file behind, and it holds the pre-load
# screen: no party, no badges, 3000 money, an empty bag. Described in
# those words it is a LIE about a save wearing six badges, and the
# re-author writes its plan against it (leg 41, 2026-08-23; the same lie
# the "brand new game" fallback made before 2f2276a, arriving by another
# road). A run past its first minute always has a party; no party means
# the snapshot is not of the world this leg is being written for, and
# "an unknown location" is the honest thing to say about it.
if not (o.get("party") or []):
    print("an unknown location")
    raise SystemExit


# HP reaches the start text: the audit's ALREADY DONE check pruned
# buy_potions because the bag was visible here, but kept every heal leg —
# and the Pewter round trip serving them — because health never was.
def mon_text(p):
    s = f"{p.get('species')} L{p.get('level')}"
    # ITS TYPES ARE ON THE PARTY SCREEN. Without them the sweep's
    # already-done judgment saw "CHARIZARD L37" and could not tell it was
    # the FLYING type the objective wanted.
    tys = [str(t) for t in (p.get("types") or []) if t]
    if tys:
        s += f" ({'/'.join(tys)})"
    hp, mx = p.get("hp"), p.get("max_hp")
    if hp is not None and mx:
        s += f" {hp}/{mx}hp"
    # WHAT IT CAN ACTUALLY DO. The author was told a level and a HP bar and
    # nothing else, so it could not reason about the four slots at all —
    # Charmeleon lost to Misty twelve times swinging RAGE with GROWL and
    # LEER filling half its moveset and TM_MEGA_PUNCH in the bag, and every
    # rewrite came back "go, heal, enter, fight". The party screen shows
    # moves; a plan written without them is written half-blind.
    mv = [str(m.get("id") if isinstance(m, dict) else m)
          for m in (p.get("moves") or [])]
    if mv:
        s += " knowing " + "/".join(mv)
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


def money_text(m):
    """How much money there is, next to what things cost.

    Everything else about a purchase reaches the author — the bag, the
    fullness of it, the price the day care asks — but never the wallet, so
    "it costs 100" could not be compared with anything. The run stood two
    coins short of its own CHARIZARD (98 against 100) with a NUGGET in the
    bag worth thousands, and no way to notice.
    """
    if m is None:
        return ""
    return f", {int(m)} money"


def hof_text(n):
    """The save's own count of Hall of Fame inductions (the PC shows it)."""
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return ""
    return (f" — the party has been entered into the HALL OF FAME "
            f"{n} time{'s' if n != 1 else ''}: the game is finished")


def respawn_text(r):
    """Where a faint sends you back to — the stake on every fight.

    Set by healing, so it can be hundreds of steps behind the party. It
    was never stated before the fact, only mourned after.
    """
    if not r or not r.get("map"):
        return ""
    where = r.get("outdoor") or r.get("map")
    return (f" — if your party faints you wake at {where}, the last Pokemon "
            f"Center you healed at (healing at a Center makes it the place "
            f"you wake)")


def daycare_text(dc):
    """The Pokemon that is NOT in the party because it is being raised.

    A missing party member is otherwise invisible: the start line simply
    reads one Pokemon shorter and nothing says why or how to undo it. The
    run handed a level 40 CHARIZARD to the Day Care Man and went on trying
    to win a grass gym with a level 6 MAGIKARP.
    """
    if not dc or not dc.get("species"):
        return ""
    lvl = f" L{dc['level']}" if dc.get("level") else ""
    cost = f" for {dc['cost']}" if dc.get("cost") else ""
    return (f" — your {dc['species']}{lvl} is NOT with you: it is at the "
            f"DAY CARE and can be taken back{cost} by talking to the man "
            f"there")


if "region" in o:                    # last_state.json is already flattened
    m = o.get("map")
    party = party_text(o.get("party") or [])
    badges = ", ".join(o.get("badges") or []) or "no badges"
    bag = bag_text(o.get("bag"))
    print(f"standing in {m or 'an unknown location'} with "
          f"{party or 'no party'}, {badges}"
          + money_text(o.get("money")) + f", and {bag}"
          + daycare_text(o.get("daycare"))
          + hof_text(o.get("hall_of_fame"))
          + respawn_text(o.get("respawn")))
    raise SystemExit
m = (o.get("map") or {}).get("id")
if not m:                      # stale/missing obs: say so rather than
    print("an unknown location")   # inventing "standing in None"
    raise SystemExit
party = party_text(o.get("party") or [])
badges = ", ".join(o.get("badges") or []) or "no badges"
bag = bag_text(o.get("bag"))
print(f"standing in {m} with {party or 'no party'}, {badges}"
      + money_text(o.get("money")) + f", and {bag}"
      + daycare_text(o.get("daycare"))
      + hof_text(o.get("hall_of_fame"))
      + respawn_text(o.get("respawn")))
