# red-recomp

A local LLM plays Pokémon Red, through a harness whose entire job is to
**tell it the truth and then get out of the way**.

The model is [Gemma](https://ollama.com/library/gemma) running on Ollama on
one local GPU (an RTX 3090 until 2026-09-02, a Radeon AI PRO R9700 since) — no
frontier model, no API, nothing over the network. It
decides where to go, what to do and what its own goals are. The harness
drives the game, reports what is on screen, and refuses to decide anything.

This repo is the harness and the planner. It drives
[pokemon-gen1-recomp-project](https://github.com/bryanthaboi/pokemon-gen1-recomp-project)
— a LÖVE reimplementation of Red, by someone else — which must be checked out
separately at `~/Developer/gen1recomp`. `run.sh` launches it with
`harness/shim.lua` as its driver. No ROM and no game assets live here.

## Watching a run

`run/status.txt` is the whole run in one screen — the leg being attempted, the
step and its machine-checkable condition, the model's reasoning in its own
words, the op in flight, what the game said back, and where the party is:

![The run's live status line: PLAN, SUBGOAL, GOAL, DONE_WHEN, THINKS, DOING,
LAST, WHERE, PARTY, MONEY and BAG, refreshed every second](status.png)

`watch -n1 cat run/status.txt`. `THINKS` is the model's plan for the round,
quoted rather than summarised, and `LAST` is the harness's answer to the
previous op — the two lines that say whether a stuck run is the model's
mistake or ours.

## Status

Reached the Hall of Fame on 2026-08-28, on a model-authored outline, with a
few hand tweaks along the way. Not a hands-off single run.

Paused from 2026-08-30 to 2026-09-02 while the 3090 that ran the model was
replaced. Back on a Radeon AI PRO R9700 (32 GB), which holds the 31B model
at a 32k window with room to spare; the author's review prompt had outgrown
the 24k the old card could fit.

## The rule the whole thing is built on

> **Stop lying, stop hiding, stop refusing — and never point.**

Every bug worth fixing in this project has turned out to be one of four
things the harness was doing to the model:

- **lying** — asserting something false ("you have already cleared Rock
  Tunnel", when every way out of it the run ever took led back to the side it
  came in by);
- **hiding** — knowing something and not saying it (the walked graph ate
  21958 characters of a 22000-character budget, and seventy characters of the
  causal journal survived);
- **refusing** — rejecting a thing the model was entitled to do (two
  validator rules that between them told it to "end on a place the run has
  never reached" and then rejected a place of any kind);
- **pointing** — deciding for it (the room sweep used to walk the party
  across a city to cut down a tree that blocked nothing).

The first three are harness bugs. The fourth is a harness bug *even when it
helps*, because a run that only succeeds when the harness steers is not the
thing being built.

Two corollaries fall out of that, and most of the code obeys them:

- **An illogical choice is a harness gap.** Wrong *facts* are the model's
  problem. A choice that is illogical *given what it was shown* is ours — it
  was shown the wrong thing, or not shown enough.
- **Prove the model can before saying it won't.** Five separate times, "the
  model just won't do X" turned out to be a signal that never reached it.

## What the harness may say

Roughly: the **manual tier** and the **on-screen tier**. What a player could
read off the screen, or out of the box the game came in. What is in the bag,
what the party knows, which doorways are on this floor, what an NPC just
said, that it is dark in here and FLASH lights it.

What it may **not** say: where things are, what to do next, which road leads
where it has not walked. It does not know that Fresh Water is sold in Celadon
and it will not tell you. It *will* tell you, four times over, that the
counter you are standing at sells seven things and none of them is water —
because the party read that shelf itself.

## How a run works

```
fresh_discovery.sh   the outline chain: the model writes its own list of
      │              objectives ("legs"), and this walks them
      ├─ campaign.sh        one leg: author a plan, run it, re-author on failure
      │     └─ fresh_run.sh → planner/executor.py
      │                          │
      │                          └─ harness/shim.lua   (LÖVE/LuaJIT driver)
      └─ the ladder        when a leg is stuck: is it already done? is
                           something else needed first? should it move later?
                           is it worded wrong? is it VOID?
```

The model never presses a button. It sends **ops** — `walk_to`, `cross`,
`interact`, `use_warp`, `field_move`, `explore`, `buy`, `use_item`,
`party_swap`, `skip`, and about a dozen more — and every op is
decision-free: it does exactly what it says or explains precisely why it
could not.

The **ladder** is how a run survives its own mistakes. A leg that cannot be
finished is not a dead end: the model is asked whether it is already done
under another name, whether something has to happen first, whether it belongs
later in the list, whether it is worded wrong, or whether it was never real.
Every one of those answers is the model's; the harness only crosses things
off and moves them.

## Tests

```
for t in tests/*.py; do python3 "$t"; done
```

250 of them, and they are named as sentences, because each one is a claim
about what the harness owes the model:

```
a_bush_is_cut_when_it_is_in_the_way.py
walking_in_is_not_walking_through.py
the_causal_story_is_not_starved_by_the_graph.py
a_leg_counted_is_not_a_leg_confirmed.py
not_standing_somewhere_is_not_a_deed.py
a_question_is_not_answered_by_asking_again.py
```

Most were written the day a run failed, and the docstring is the incident
report: what the model was told, what it did, and what it should have been
told instead.

## Where it has got to

Run 15 has five badges — Boulder, Cascade, Thunder, Rainbow, Marsh — with a
Charizard, a Pidgeot, a Gloom, a Hitmonlee, a Dugtrio, and a Gyarados raised
from a ¥500 Magikarp the model bought for itself. Along the way it took the
Rocket Hideout for the Silph Scope, cleared the Pokémon Tower and got the Poké
Flute from Mr. Fuji, worked its way up Silph Co. with the Card Key for the
Master Ball, and woke both Snorlax. An earlier run reached the Hall of Fame on
a model-authored outline.

The interesting number is not the badge count. It is that when the run gets
stuck, the fix is almost never in the model.

## Design notes

- `SPD_DESIGN.md` — the three-tier architecture (executor / authored plans /
  refinement) and why the mechanics live outside the model
- `EXPLORE_DESIGN.md` — the exploration ledger: what counts as ground the run
  has seen, what counts as a way out it has never taken
- `AUDIT_TODO.md` — the running list of things the harness is still not
  honest enough about
