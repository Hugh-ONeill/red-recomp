# The Elite Four arena

`run/arena_e4.lua`, rebuilt 2026-09-12 from
`run/saves/leg_58_defeat_the_elite_four_and_become_.20260911-153656`
via `planner/gin_save.py --spec plans/arena_e4.json`.

## What was wrong with the old one

It was hand-ginned on 2026-08-24 (player name "AAAAAAA") and its party led
with a **CHARIZARD L71** against a league that tops out in the low sixties,
behind five stragglers — EEVEE L30, TENTACOOL L26, GLOOM L37. It also
started in **BRUNOS_ROOM**, the second of the five, not the first.

That makes a score unreadable. `policy_model_v3` cleared eight rooms with
no `battle_items` rule and no `field_heal` at all, which reads as a finding
about the spec until you notice the level-71 sweeper doing it (user,
2026-09-12: "we must have given it overlevelled mons if it was able to
solve it without item usage").

## What it is now

The party run 16 actually walked into the league with, at the levels it
actually had, with the moves it actually knew:

    GYARADOS  L54  HYPER_BEAM THUNDERBOLT BITE SURF
    VAPOREON  L53  BUBBLEBEAM SAND_ATTACK QUICK_ATTACK BLIZZARD
    CHARIZARD L61  FIRE_BLAST MEGA_PUNCH STRENGTH DOUBLE_EDGE
    NIDOQUEEN L50  FURY_SWIPES TACKLE SCRATCH EARTHQUAKE
    DODRIO    L51  AGILITY GROWL FLY FURY_ATTACK
    VILEPLUME L51  PETAL_DANCE MEGA_DRAIN SOLARBEAM CUT

Parked at LORELEIS_ROOM (4,11), all five rooms unbeaten, with a bag bought
off the Plateau lobby's own shelf (FULL_RESTORE, MAX_POTION, FULL_HEAL,
REVIVE, ULTRA_BALL) at what 30,372 affords. The bag matters: a spec can
only be judged on rules it is able to fire, and the lobby is the ONLY shop
in the game that sells FULL_RESTORE or MAX_POTION.

## Consequences

**Every Elite Four score recorded before 2026-09-12 is stale.** They were
measured on a different party starting in a different room, so v2's "1
room" and v3's "8 rooms" are not comparable to anything measured from here
and should not be trusted to choose a spec. Re-score with
`policy_author.py --arena e4 --from-save run/arena_e4.lua`.

## Refreshing it

The arena is pinned to one run's league party on purpose — it is the only
honest answer to "what does this harness actually bring to the league". Cut
a new one when that stops being true: take the newest
`run/saves/leg_*_elite_four*/slot1.lua` and re-run the gin_save line above.
