# The two midgame arenas

Built 2026-09-12 to sit between the Brock arena and the Elite Four one, so
a battle spec can be scored at the stage it will actually play.

The tiers are the game's own shelves, not a guess: a rule can only fire on
an item the run can buy, and the shops change three times.

| first sold at | what appears | arena |
|---|---|---|
| Pewter | POTION | `plans/brock.json` (existing) |
| Vermilion | SUPER_POTION | **`run/arena_erika.lua`** |
| Lavender | GREAT_BALL, REVIVE | " |
| Fuchsia | ULTRA_BALL, FULL_HEAL | **`run/arena_koga.lua`** |
| Saffron | HYPER_POTION | " |
| Indigo Plateau lobby | FULL_RESTORE, MAX_POTION | `run/arena_e4.lua` |

Two items a spec may NOT reach for at any tier: **ETHER and MAX_REVIVE are
not sold anywhere in Red.** Both are field-find only. `policy_model_v6`
named MAX_REVIVE, and FULL_RESTORE and MAX_POTION which are sold in exactly
one shop in the game — three of its five battle-item rules could not have
fired however well the run shopped.

## arena_erika — the Super Potion tier

Base: `run/saves/leg_20_defeat_erika_for_the_rainbow_badg.20260907-182506`.
Parked at CELADON_GYM (4,17), Erika and all seven gym trainers unbeaten.

    NIDORINA  L29   GLOOM L30   CHARIZARD L37   EEVEE L25

Bag off Celadon Mart 2F's shelf at what 12,882 affords: SUPER_POTION x8,
REVIVE x2, PARLYZ_HEAL x3, GREAT_BALL x5.

The Charizard's only fire move is EMBER, so this is not the free win a
fire party against a grass gym would normally be.

## arena_koga — the Ultra Ball / Full Heal tier

Base: `run/saves/leg_30_reach_fuchsia_city.20260908-121253` — the leg
BEFORE Koga, so no Soul Badge is held and its stat boost is not in play.
Parked at FUCHSIA_GYM (4,17), Koga and all six gym trainers unbeaten.

    NIDORINA L37   GLOOM L34   CHARIZARD L41   EEVEE L25   DODUO L22

Bag off Fuchsia's own shelf at what 12,814 affords: SUPER_POTION x8,
REVIVE x2, FULL_HEAL x3, ULTRA_BALL x1. Two members are far under level,
which is what makes attrition real and item rules worth having.

That base save arrived with two members fainted. They were healed by
DROPPING `hp` and `stats` from the party in the save, which the game
rebuilds at load from species/level/DVs/statExp — so these are the same
mons with the same training, standing up, rather than a fresh party at
default DVs. The derived max HP came back 113/93/135, matching the
original exactly, which is the check that it worked.

## What is NOT done

`policy_author.py` cannot score these yet. It knows two arenas: `brock`
replays a plan, and `e4` walks room to room by map id and flag. A gym is
one room with N trainers in it, which neither shape fits. The saves are
ready; the scorer is the remaining work.
