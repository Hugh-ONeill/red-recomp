# SPD architecture — Scripted Policy Distillation for Red (sketch v0)

Design sketch, 2026-08-10. Companion to `~/Documents/red-recomp-project/
CLAIM_RULES_v1.md` (the model-claim + the "model authors / executor runs / RL
refines / fallback declared" structure) and `project_red_recomp_campaign`.

## Why SPD, from the probe evidence

Eight probes this session converged on one shape. The local 26B is a *good
high-level decider* — 100% valid ops, correct starter, correct battle moves,
knows the route ("go north to Route 2") — and a *poor low-level executor and
trap-recoverer*: blind walk wanders into doors, it loops on local snags, and
it re-derives the same intent every step, burning calls. Every win came from
moving mechanics OUT of the model into decision-free executor ops (walk_to,
cross, interact, use_warp, auto-advance). SPD is the generalization of that
move: **the model authors plans and policies OFFLINE; a robust executor runs
them; the model is consulted only to author and to recover.** This is also
the PokeAgent Track 2 winner's shape (40:13) and the only architecture the
retrospective shows converting for non-frontier models.

## The three tiers

### Tier 0 — Executor (deterministic, NO model at runtime)
The current harness IS most of this already. It runs an op stream, rides
non-decision states (auto-advance), and each op is decision-free. SPD adds:
- **Subgoal runner**: takes a plan (Tier 1), runs each subgoal's op-macro,
  evaluates its `done_when` predicate against the observation, advances on
  success, escalates on failure/timeout.
- **Predicate evaluator**: `done_when` is a small DSL over the obs —
  `{map: "VIRIDIAN_CITY"}`, `{party_nonempty: true}`, `{badge: "BOULDERBADGE"}`,
  `{flag: "EVENT_BATTLED_RIVAL_IN_OAKS_LAB"}`, `{hp_ok: true}`. (Event flags
  are instrumentation for the executor's own control flow, not model
  observations — consistent with the claim rules.)
- **Battle handling**: when a macro step enters battle, run the battle policy
  (below) turn-by-turn until it ends, then resume the macro.
- Executor NEVER uses blind `walk` for travel (the wander trap) — only
  walk_to within a map and cross between maps.

### Tier 1 — The Plan (authored by the model, offline; the distilled artifact)
A JSON route: an ordered list of subgoals. Each carries a goal predicate, a
macro (op sequence) and/or a policy reference, and an escalation hint. This
is what the model WRITES and what hardens over attempts — the "distilled
policy" in SPD terms. Example (the opening, which the probes already proved
runnable op-by-op):

```json
{ "goal": "boulder_badge",
  "subgoals": [
    {"id":"leave_house","macro":[{"op":"use_warp","x":7,"y":1},
       {"op":"use_warp","x":2,"y":7}],"done_when":{"map":"PALLET_TOWN"}},
    {"id":"get_starter","macro":[{"op":"cross","dir":"north"},
       {"op":"interact","name":"OAKSLAB_SQUIRTLE_POKE_BALL"},
       {"op":"menu","index":1},{"op":"menu","index":2}],
       "done_when":{"party_nonempty":true}},
    {"id":"win_rival","macro":[{"op":"use_warp","x":4,"y":11}],
       "battle_policy":"default","done_when":{"flag":"BATTLED_RIVAL_OAKS_LAB"}},
    {"id":"to_viridian","macro":[{"op":"cross","dir":"north"}],
       "done_when":{"map":"VIRIDIAN_CITY"}},
    {"id":"to_route2","macro":[{"op":"cross","dir":"north"}],
       "done_when":{"map":"ROUTE_2"}},
    {"id":"viridian_forest","policy":"maze_north","done_when":{"map":"PEWTER_CITY"}},
    {"id":"pewter_gym","macro":[{"op":"use_warp","name":"gym_door"}],
       "done_when":{"map":"PEWTER_GYM"}},
    {"id":"beat_brock","battle_policy":"gym","done_when":{"badge":"BOULDERBADGE"}}
  ]}
```

### Tier 2 — The model as author + escalation handler (offline + rare runtime)
- **Authoring**: given the goal + its (open) game knowledge + grounded-rag,
  the model writes the Tier-1 plan. First cut can be hand-seeded from the
  verified opening; the target is the model producing it.
- **Escalation**: when a subgoal fails its predicate after K attempts, the
  executor captures the stuck state and asks the model to either (a) issue a
  few corrective ops live (bounded CPP-style), or (b) REWRITE that subgoal's
  macro/policy. Option (b) is the distillation event — the fix becomes part
  of the plan, so the same wall is never hit twice. Escalations should decay
  toward zero across attempts; that decay curve is the headline metric.

## Battle policy (the model-authored battlebot, per CLAIM_RULES §1-2)
- The model writes a battle decision function as data: prioritized rules over
  the battle obs (`me`/`foe` species, types, hp, moves). e.g. "KO if a move
  can; else highest expected damage by type; switch if <X% and a safe pivot
  exists; heal if item + <Y%". Executor runs it per turn, no LLM in the loop.
- **The checkpoint-search battlebot is the ORACLE, not the runtime**: bench
  the authored policy vs oracle-optimal play on a fixed battle set;
  winrate-vs-oracle is the quality meter for each policy revision. Oracle
  decisions never ship into the record run under the model-claim.
- Two named policies to start: `default` (route trainers/wild) and `gym`
  (Brock — the model should reason Squirtle's water STAB trivializes it).

## What is seeded, stated plainly (2026-08-17)

The outline is the model's, with one exception worth naming rather than
burying: **eight of roughly thirty objectives are harness-seeded** — the
eight badge objectives in `author.SEEDED_BADGES`, which `_check_badges`
re-inserts if a drafting pass drops one.

Ruled pamphlet tier: badge names are on the box and the leader-to-badge
pairing is the sort of thing the booklet tells a player before they start.
The wording of those eight lines is ours. Everything else on the outline,
and every plan written under every objective, is the model's.

## RL / refinement — NOT BUILT (restated 2026-08-17)

**This section describes a design, not an implementation.** There is no
torch dependency, no reward spec, no navigation net and no distilled battle
net anywhere in the tree, and the record run does not use any. Listing it
as one of four claim pillars overstated what exists, which the audit was
right to call out.

What is actually built, and is the real differentiator, is **learning-free
play plus evidence-driven replanning**: the model authors the outline and
every plan, the executor runs them, and when a leg fails the model rewrites
that leg from what the run actually walked — the exploration graph, the
proven-unreachable ledger, the journal — and resumes from the last save.
No weights are trained at any point.

The design below is kept because it may be built later (the footprint work
is the likely occasion), and because the claim should show what was
considered and not done as well as what was done. Until it exists, it is
not a pillar.

### The design, if it is ever built (claim-pure — CLAIM_RULES §3)
Checkpoints make resets free, so subgoals expressible as a small policy get
trained rather than scripted:
- **Navigation policies** (Viridian Forest `maze_north`): the model authors a
  reward spec (progress toward the north exit, penalty for re-entering
  buildings); PPO/behavior-cloning trains a small net. This directly kills the
  wander/bounce class instead of prompt-patching it.
- **Battle policy**: distill oracle decisions + the authored rules into a net,
  RL-refined against checkpoint resets. Nets are open by construction.
Distillation endpoint: a route+policies that need NO LLM at runtime — a
from-scratch bot whose every decision was authored by the open model (logged
provenance is what separates it from the in-tree pokered `bot_route.lua`,
which is human-authored and claim-forbidden in the decision path).

## Fallback (declared, CLAIM_RULES §4)
If a subgoal can't be authored to pass within its refinement budget, escalate
to the live open model (still model-claim). Last resort for battles only: the
oracle battlebot pilots → the claim honestly downgrades to the system-claim.
Never blurred; the record states which was achieved.

## What changes vs the current probe harness
Today: one flat LLM-per-decision loop (`brock_probe.py`). SPD inserts a plan
layer + executor between the model and the ops. LLM calls drop from ~every
decision to ~per-subgoal-authoring + rare escalations — cheaper, faster, and
it removes the wander/loop/burn failure classes structurally rather than by
prompt.

## Build order
1. **Executor + predicate DSL + subgoal runner**, driven by a HAND-SEEDED
   opening plan (the verified leave_house..to_viridian macros). No model yet.
   This alone should clear the opening deterministically and end the Viridian
   bounce — validates the plan/predicate/executor spine. (Also fixes cross to
   be NPC-robust and drops blind walk — prerequisites either way.)
2. **Battle policy v0** (model-authored rules as data) + the checkpoint-search
   **oracle** to score it. Run the rival + Brock through it.
3. **Model authors the plan** from the goal (replace hand-seeding); add the
   escalation handler + the distillation write-back. Measure the escalation
   decay curve.
4. **RL refinement**: NOT BUILT — see the restatement above. `maze_north`
   navigation net for Viridian Forest; battle-policy net distilled from the
   oracle. Deferred, possibly to the footprint work.
5. **31B rider** throughout — does the bigger author produce better plans /
   escalate less.

## Open questions to resolve while building
- Predicate for "rival battle done" — is there a clean event flag, or infer
  from `no battle + map==OAKS_LAB + party leveled`? (flag preferred.)
- How to name warps for macros (gym_door etc.) — extend the objects/warps obs
  with stable labels, or address by x,y (brittle across versions).
- Escalation granularity: per-subgoal vs per-op — start per-subgoal.
- Where the plan lives: one JSON per goal, versioned in-repo; distillation
  edits it in place with a provenance log (who authored/changed each macro).
