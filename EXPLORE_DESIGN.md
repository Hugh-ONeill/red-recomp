# Exploration as a search — design note (2026-08-18)

Companion to `SPD_DESIGN.md` and `AUDIT_TODO.md`. The question the user put:
make travel and exploration more deterministic/algorithmic **without
mechanically forcing it** — lead by suggestion toward logical search
actions, instead of the run trying the same thing ten times with an action
or two between.

Everything below is measured with `planner/repeats.py` (new; reads the same
context/proposal/feedback triples `decisions.py` reads, no model calls) over
the 31 journals in `run/`, 5,405 escalations, 32,517 rounds.

## 1. What is actually happening

**The loop is not a search.** 43.8% of escalation rounds re-propose a first
op already proposed earlier in the same escalation; 18.8% repeat the previous
round verbatim; 44% of escalations contain two or more repeats. The post
map-edges era (`--new`, ~4,800 rounds) is no better: 43.0% / 18.6% / 58%.
Rounds per escalation: median 4, mean 5.7 (6.7 in the new era).

**Most of the repetition is invited by the harness.**

- **30.2% of all rounds are refused** by a guard (9,828). By kind: reversal
  ("the door you just came in through") 7,140; failed-3x 2,760; revisit 570;
  searched 427; dead-end 164; inert-object 127.
- **The prompt contradicts the guard.** 1,025 reversal refusals and 803
  failed-3x refusals (29%) were of an exit the *same* prompt had listed under
  "UNTRIED (prefer these)". 305 reversal refusals were of the door the
  KNOWN WAY line had just told it to take. Two definitions of "untried" and
  "back" — one in `exploration_text`, one in `_run_traced` — and they
  disagree. (`50914b0` fixed one such pair; the class remains.)
- **Refusals yield, so persistence pays.** The model re-proposed the exact op
  it had just been refused 3,623 times. 2,781 were refused again; **709 were
  then allowed** (the reversal and revisit guards yield after 2–3). From the
  model's side the harness says no, no, yes: the pattern "same thing with an
  action or two between" is precisely what a yielding refusal trains.
- **The reversal guard fires on rooms with one door.** In the live leg-3
  journal it refused leaving VIRIDIAN_MART (one door, twin tiles) twice, then
  re-entering it twice, then leaving OAKS_LAB (one door) twice and re-entering
  it once — seven refusals in one 15-round escalation, and the third try at
  each door went through. 35% of reversal refusals fire while the party stands in an
  interior map; the mart, both Pokemon Centers, Oak's lab, Bill's house, the
  bike shop and the trade house are all in the top 25.
- **A phantom object nags in 38% of prompts.** Signs are listed in
  `obs.map.objects` (kind `sign`, `TEXT_…_SIGN`), the untouched-things line
  says "press A on them, it is free", but `OPS.interact` by name searches
  `ow.npcs` and `map_fixtures` only — never `md.signs`. **1,726 sign
  interacts have failed "not visible"; none has ever succeeded.** A failed
  interact retracts the touch, so the sign stays untouched and is re-offered
  every round, and after three failures the failed-3x guard refuses it.
  That is a repetition engine and a "stop refusing" defect (route signs are
  the pamphlet tier made literal).
- **Cost.** ~9,800 refused rounds × 7.7 s median inference ≈ **21 hours of
  model time spent on rounds the harness then rejected**, in a loop where 95%
  of wall time is already inference (AUDIT_TODO #30). Escalations per
  subgoal completed are 2.08 and rising; the decay curve does not decay.

**The model is not the problem, still.** `decisions.py` says 99.5% of moves
name something the prompt offered. Given a prompt that says "prefer door X"
in one paragraph and a guard that refuses door X, proposing X again is the
logical choice. Illogical choices given the facts are ours
(`feedback_illogical_means_harness`).

Root cause, stated once: **three uncoordinated authorities** decide what is
sensible from here — the prose renderer (`exploration_text`, ~20 sections,
541 lines), the guards in `_run_traced` (reversal, revisit, searched, dead-op,
inert), and the mechanical helpers (free-round exit, sweep, escort), each
with its own trigger and its own definition of untried/taken/back. The model
re-derives the search state from prose every round, at 8 s a round, and the
three authorities disagree with it and with each other.

## 2. Principles

1. **One ledger, three readers.** A single candidate list per (target, area)
   — every exit, every thing, every person, with a status and a history — is
   what the prompt renders, what the guard checks against, and what the
   mechanics act on. *Never refuse what you offer; never offer what you would
   refuse.*
2. **Status, not refusal.** "The door you came in by", "taken 6x", "failed
   3x: blocked at (19,10)", "shut", "dead for this goal" are *facts on a
   candidate*, shown beside it with the last outcome verbatim. Only two hard
   refusals remain: **off-ledger** (a coordinate or name the ledger does not
   contain — hallucination) and **proven impossible with the world
   unchanged** (dead-op ≥3 with the same snapshot; a sealed seam). A refusal
   never yields after N: it is either a fact or a rule.
3. **The closed set lives in the menu.** Each entry says what happened the
   last time this run did it ("spoken to 4x this subgoal; every time: *Okay!
   Say hi to PROF.OAK for me!*"). A repeat is then a deliberate choice made
   in full view, and it can be measured. Nothing is forbidden.
4. **Rank mechanically, and say so.** untried before taken; unopened before
   known; nearest over walked ground; least-visited; local before remote
   (measured position bias: the model takes the first-listed 54% of the
   time). Ranking is arithmetic on walked ground; which entry matters is the
   model's. No destination of an unwalked door, no town-map itinerary, no
   named lock — the claim rules stand.
5. **The algorithm is an op, not an ambush.** The systematic frontier step —
   press what is untouched, speak to who is unspoken, take the nearest way
   never taken, else walk to the nearest area that still has one — becomes
   `{"op":"explore"}`, model-invoked, exactly as path-finding is `walk_to`.
   The free-round exit and the escort stop firing on their own; when a round
   achieved nothing the ledger *offers* explore as entry 1. The sweep stays
   automatic (pressing A on things is not a decision) but obeys 1–3.
6. **Feedback is a diff.** What changed (map, flags, party, bag, money), what
   was said (verbatim), and the updated ledger. `inert`, `backward`,
   the re-listed warps and edges become redundant — the ledger carries them.

## 3. The ledger

```
candidate := {
  key:      "3,7" | "north" | "obj:VIRIDIANMART_CLERK" | "explore"
  kind:     door | seam | thing | person | trainer | fixture | op
  status:   untried | taken(n, -> dest) | came_in_by | shut(n) | failed(n, why)
            | dead_for_target(n) | searched_beyond | touched(n) | asked
  history:  last outcome, verbatim, this subgoal   (bounded)
  rank:     (untried?, unopened?, hops over walked ground, visits, key)
  offer:    bool   -- what the guard consults; false only for 2's two cases
}
```

Built by one function from the same sources the renderers already read
(`_taken_here`, `_spent_exits`, `_sealed`, `dead_for`, `_tried_objs`,
`_inert_objs`, `hints`, `_arrived/_came_from`, `explored`, `frontier`).
Rendered compactly:

```
FROM VIRIDIAN_MART|0,2 (indoors, no edges; you have been here 3x):
 1. explore — nothing here is untried; the nearest area with a way never
    taken is VIRIDIAN_CITY|17,0 (1 leg): explore walks there and takes one.
 2. door (3,7) -> VIRIDIAN_CITY — the door you came in by; taken 2x.
 3. VIRIDIANMART_CLERK — spoken to 4x this subgoal; every time:
    "Okay! Say hi to PROF.OAK for me!"
 4. VIRIDIANMART_YOUNGSTER — spoken to 1x: "..."
 5. VIRIDIANMART_COOLTRAINER_M — spoken to 1x: "..."
```

The escalation reply stays a JSON macro. A step may be `{"op":"explore"}`
or any documented op; the guard checks map-changing ops and interacts
against `offer`. Off-ledger → refused with the ledger keys named. Nothing on
the ledger is refused.

## 4. `explore` — the frontier step, as an op

Deterministic, one expansion per call, reports what it did:

1. If a reachable *thing* here is untouched (items first, then fixtures,
   people, signs) — press it, report what it said / gave. (The sweep, but
   one thing at a time and by request.)
2. Else if this area has an untried exit — take the best by rank
   (unopened before known, goal-ward by walked-ground distance if the target
   is a place). Report the arrival.
3. Else walk over walked ground to the nearest area with an untried exit
   (`_route_to_frontier`'s ranking) and take it. Report the arrival.
4. Else say so: "nothing untried anywhere you can reach; something you have
   done must be undone or something you carry must be used" — and stop.

One leg per macro still holds: `explore` is map-changing, so it must be last.
It is claim-clean by construction: it knows no destinations it has not
walked, and it never prefers a door for what is behind it. What it replaces:
the implicit free-round exit (`free_round_exit`, 869 in the corpus), the
implicit escort (`rerouted`, 904), and half the prose that exists to make
the model do those by hand.

## 5. Staged, each with a number

| stage | change | measure (`repeats.py`) | expect |
|---|---|---|---|
| 0 | Reversal guard → status; never refuse a room's only exit; refusals never yield; failed-3x removes the key from UNTRIED and shows the failure; **fix sign interact** (`OPS.interact` reads `md.signs`) | refused-round share; after-refusal yields; sign fails | 30% → <10%; yields → 0; sign fails → 0 |
| 1 | Build the ledger; render it in place of the exits/things/people sections; guard reads `offer` | offered-untried contradictions; repeat share | contradictions → 0; 44% → <25% |
| 2 | `explore` op; free-round exit and escort no longer self-fire (offered instead) | rounds/escalation; escalations/subgoal (the decay metric) | median 4 → 3; decay curve finally decays |
| 3 | Feedback as diff + ledger; drop `inert`/`backward`/re-listed warps | prompt bytes; inference s/round | prompt −40%; s/round down |
| 4 (opt.) | Choose-only exploration turn: reply with a ledger number, macro as escape hatch | s/round; `decisions.py` trivial | further speed; a decision becomes a pick |

Stage 0 is a day and pays for itself; stages 1–2 are the redesign proper and
retire most of `exploration_text`'s sections rather than adding to them
(AUDIT_TODO #31: `escalate` 846 lines, `_run_traced` 791, `exploration_text`
541 — the ledger is how those shrink).

## 6. Stage 0 — landed 2026-08-18 (chain stopped for it)

- `harness/shim.lua` `OPS.interact`: a name is also looked up in `md.signs`
  under the same name observe() lists it by. Verified live against a copy
  of the save (own identity, `tests/contract.py` machinery): three Viridian
  signs read, `text_seq` bumped, words captured. Signs now stop being a
  phantom in the untouched-things line, and their text reaches `hints`.
- `planner/executor.py` reversal guard: (a) never fires when the door (or
  its twin tile) is the only reachable way out of a room with no seams —
  the note says so and the op runs; (b) fires ONCE per arrival, as a
  question that names the untried ways out and says "propose it again and
  it will run" — the second proposal runs; (c) a round whose only refusal
  was that question stays free but the free-round exit walk does NOT fire
  (`_back_asked`), so the harness cannot answer the question for the model.
- failed-3x refusal names the op and its arguments.
- `planner/repeats.py` is the regression meter. Re-run it after the next
  chain: expect the reversal share of refusals to fall by roughly a third
  (one-exit rooms) and the "refused then allowed" count to drop toward zero.

Offline tests (`tests/untried.py`, `spoke`, `touched`, `transient`, `fired`,
`goods`, `battle_intent`, `predicates`, `fresh_world`) pass.

## 6b. Stage 1 — built standalone, wiring pending (2026-08-18, chain live)

`planner/ledger.py`: `build(ex, obs, target, outcomes)` → ranked
`Candidate`s (doors, seams, things, people, plus the `explore` entry with
what it WOULD do); `render(...)` → the numbered block; `lookup(cands, step)`
→ the entry an op addresses or None (= off-ledger, the one refusal on this
ground); `untried_keys(...)` for the law. Read-only against the executor.
`tests/candidates.py` (39 checks) runs `tests/untried.py`'s worlds through
it — the ledger's untried set equals `_untried_exits` in every case — plus
the ledger's own rules (came-in-by is offered and not untried, twin tiles
are one door, unwalked doors name no destination, lookup on/off, render).
Rendered against a copy of the live ledger it agrees with today's exits
block line for line at ~2.8k chars against 5.7k of prose.

To wire at the next stop: (1) `_run_traced` writes
`self._outcomes[(target, here, key)] = {"n", "last"}` after each op — the
one new piece of state; (2) `exploration_text` renders the ledger in place
of the exits / things / people / hints-here paragraphs; (3) the reversal,
revisit, searched and inert guards become statuses, and `_run_traced`
refuses only `lookup(...) is None` (plus the existing dead-op ≥3 rule);
(4) `escalate` reads `explore` as an op (Stage 2). Measure with
`repeats.py` before and after.

## 6b'. WIRED — 2026-08-18, chain stopped for it (Stages 1, 2 and the plan echo)

- `exploration_text` renders `ledger.render(...)` for everything LOCAL
  (exits, things, people, the edge line, the shut-doors line, the four
  untouched/pressed/worth-a-word/never-spoken lines) and keeps the remote
  and target-level sections after it. `RED_LEDGER=0` restores the legacy
  renderer for A/B. The second render of the exploration text inside the
  feedback block, and the re-listed warps/edges/objects/inert/backward, are
  gone under the ledger: one ledger per prompt, one `escalate_context` per
  round.
- `_run_traced`: the reversal, revisit, searched-room, dead-end-door and
  inert-object refusals are gone; the only refusal on that ground is
  OFF-LEDGER (`ledger.lookup(...) is None`: a door/direction/name that is
  not here), which names what is. cant-afford and dead-op≥3 stay. After
  every op `_record_outcome` writes the per-(target|area, key) count and
  last outcome, which the ledger prints on the entry.
- `{"op":"explore"}` exists: `_explore_step` takes the ledger's first
  untouched/unspoken/cuttable thing (interact, or field_move CUT), else its
  first untried exit, else walks over walked ground to the nearest area
  with something left and expands once there, else says nothing is
  reachable — and runs the concrete op THROUGH `_run_traced`, so the touch
  rule, hints, transitions, blackout detection and the outcome ledger apply,
  and the concrete op (not "explore") is what distills. Documented in the
  vocabulary; counts as map-changing for the one-leg cut.
- The reply is `{"plan": "...", "ops": [...]}` (bare arrays still parse);
  the plan is logged with the proposal and echoed next round as *YOUR PLAN,
  in your own words, last round*.
- Live probe (own identity, Cerulean fixture, real 31B): the ledger rendered
  from real state; the model returned the object form every round; its
  plans built on each other through the echo ("Since I cannot use CUT yet,
  I will…"); it took an untried door, the badge-house man's badge menu was
  handed back open by the new interact rule. Probe fixes: the badge house's
  BACK door was labelled came-in-by (same-map heuristic dropped — arrival
  tile ± 1 and twins only), bushes read "never pressed" for ever (now
  bush/cuttable; explore cuts a cuttable one), exits could be cut by the
  render cap (never now), a bush was called a "reachable person".
- Tests: `tests/candidates.py` (55), `tests/explore_step.py` (12), the
  offline suite, `tests/replay_smoke.py` live. `decisions.py`/`repeats.py`
  read both prompt formats.

## 6c. Both halves of the loss are ours (user, 2026-08-18)

"Presented the information simply without distraction, the 31B produces
good strategies; the problem keeps being what the harness tells it and
what it can distill back out as actions." Measured:

**Input.** The escalation prompt today is ~17k chars: 6.9k of op
vocabulary (40%), ~4.7k of `exploration_text` prose, an atlas up to 4k,
the feedback block (trace + notes + re-listed warps/edges/objects + inert +
backward), and the observation JSON. Under a 12,288-token window it fits
(no TRUNCATED in this chain), but position is the budget: the model takes
the first-listed exit 54% of the time and reads at ~14% depth. The ledger
(§3, §6b) is the input fix — one ranked block, ~2.8k chars, every fact on
the entry it belongs to.

**Output.** 80% of all proposals are ONE op (26,264 of 32,665). The
one-leg rule made the model compliant, so it now spends one inference per
op and re-derives its intent every round: nothing of what it was trying to
do survives to the next prompt except our trace of what happened. Where it
did write further ahead, 14% of proposals were cut at the first
map-changing op (7,257 ops discarded, mean 1.6 per cut). Two changes,
zero claim cost, both "make it drink":

1. **The reply carries the plan.** `{"plan": "<one or two sentences>",
   "ops": [...]}`. The harness stores `plan` and shows it back next round
   as *YOUR PLAN, in your own words, last round* beside what has happened
   since. Nothing is composed by us; a strategy the model authored is no
   longer thrown away between legs. It also gives `decisions.py` and the
   casters a legible line of intent per round.
2. **Coordinate-free legs run.** The one-leg rule exists because
   coordinates on an unseen map are hallucinated. `cross dir`,
   `interact name`, `heal`, `buy`, `use_item`, `grind`, `explore` carry no
   coordinates, so a macro like `[cross west, cross west, interact
   ROUTE22_RIVAL1]` is executable as written: run leg by leg, stop at the
   first op that fails or the first coordinate-bearing op after a map
   change, then re-prompt with the plan echoed. Fewer inferences per
   subgoal (the 95%-of-wall-time term), and the model's own sequence is
   what runs.

Both belong to the wiring pass with the ledger; measure with
`repeats.py` (rounds per escalation, s per round) and `decisions.py`.

## 6d. Budget, not knowledge — the stale cutoff (2026-08-18)

A subgoal that spends round after round on an idea rather than on the
world (the mart leg: 78 rounds, `use_warp(3,7)` x16, `interact(CLERK)` x9)
should hand itself to the rewrite early — which now sees the repetition
counted (`author.tried_text`, the new "WHAT EACH STEP OF THAT PLAN TRIED"
section of the journal digest, fed to the rewrite and every ladder rung).

`STALE_CUTOFF` (env `RED_STALE`, default 6, 0 disables): six rounds in a
row that changed nothing the run CARRIES (badges, flags, bag kinds), KNOWS
(no ground new to this subgoal) or IS (party species/levels, money) end the
subgoal the way `_goal_drift` ends a travel leg that gets no nearer.
Distance is undefined for a flag/item/person target, so drift never fired
where the loops actually happen.

Never cut: a contested room (a fight lost, to be come back to); a room with
re-pressable switches — Surge's cans re-randomise on a miss and pressing
again is the only way through (a PC is a service, not a switch); a
training goal (levels are the change); a round that fainted; a round ending
off the overworld. The ledger agrees: a room with switches never reads
FULLY WORKED, and each switch's entry says it can be pressed again.

Also: the plan echo now shows the last FOUR plans with where each was
written (19% of consecutive ledger-era plans were a leave-then-return flip
made with only the last plan in view); `show_esc.sh -p [-f]` prints the
thought stream; `run/status.txt` carries a THINKS line.

## 7. What this does not do

- It does not point. The ledger holds only what the observation and the
  walked record already say; ranking is arithmetic; `explore` walks ground
  the run has walked and opens doors the run can see.
- It does not force. Everything on the ledger is allowed, including going
  back; `explore` runs only when asked. The two remaining refusals are the
  two nobody wants allowed (hallucinated keys, proven-impossible ops).
- It does not fix wrong facts. Leg 3 of the live chain is gated on
  `EVENT_GOT_POKEBALLS_FROM_OAK`, which the engine sets only after the
  Route 22 rival battle (`gen1recomp/data/scripts/oaks_lab.lua:100-101`) — the model's own
  misconception about "the Pokemon at the mart". The ledger will make that
  cheaper to fail (fewer refused rounds), not different.
