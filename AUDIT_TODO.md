# Audit follow-up — red-recomp

Source: harness audit, 17 Aug 2026, HEAD `6908cc2`. 27 findings.
Report: https://claude.ai/code/artifact/b65acac7-74fa-4148-bcca-c9f23693b648

`VERIFIED` = reproduced against live artifacts. `REPORTED` = read out of the
code with file:line, not independently executed. Severities are the audit's.

Ordered by my recommendation, not by severity. The ordering principle: things
that are **silently not running** come before things that are wrong, because a
dead rule cannot be reasoned about; things that **lie to the model** come next,
because that is the one rule the whole project rests on; things that **stop or
corrupt an unattended run** after that, since the claim run is set off once and
left alone.

---

## Tier 0 — before the next chain runs at all

Three edits that turn three dead rules back on, then the test that stops the
next one being dead for a fortnight.

- [x] **1. BATTLE-1 · High · VERIFIED — every HP-gated battle rule is dead**
  `harness/shim.lua:649` emits `maxhp`; `planner/battle_policy.py:254` reads
  `max_hp`, gets `None`, returns `1.0`. In-battle POTIONs, the HP flee and
  `setup.min_hp_frac` have never fired — **0 `battle_item` ops in 64,218 logged
  battle turns**, live since 2026-08-10. `plans/policy_model_v1.json` carries a
  POTION rule at `hp_below 0.3` that has never run.
  *Fix:* read both keys in `_hp_frac`, or rename in the shim. Prefer reading
  both — the log corpus is full of the old spelling.
  **DONE** — `_hp_frac` reads `max_hp` then `maxhp`. Proven live end to end:
  bought POTIONs, spammed GROWL in a real Route 24 wild battle so the lead
  took honest damage down to 0.23, the live `policy_model_v1` spec reached
  for the item, and `OPS.battle_item` — never invoked once in the project's
  history — worked first time (21 → 36 hp, bag 3 → 2). Also verified the
  rules do *not* misfire at full HP.

- [x] **2. EXEC-2 · High · VERIFIED — the blackout fallback tests the bag, not HP**
  `planner/executor.py:4197` — `after[6]` is `(bag_kinds, bag_total)`; HP is
  index 7. The correct twin is 1,600 lines away at `:5817`. A wipe *inside* a
  Lua op (`grind`, `cross`, `walk_to`, where mode never reads `battle`) is not
  detected, `_faint_at` never arms, the walk-back never runs. Across 20 logs:
  ~600 blackouts caught via mode, 5 via state — and those 5 only because the
  bag happened to grow.
  **DONE** — `after[7] > before[7]`. Confirmed against `_snapshot`: for a
  wipe in Mt Moon that respawns at the Pewter centre with the bag untouched,
  index 6 is `(1,2)` both sides (no rise, no detection) and index 7 goes
  `0 → 30`. The macro-path twin at `:5817` was already correct.

- [x] **3. SHIM-1 · High · VERIFIED — watchdog leaves a direction held**
  `harness/shim.lua:112` clears `input.state` but not `pressQueue`;
  `walk()` inserts into the queue *then* yields, and the watchdog raises before
  the yield returns. `Input:step()` re-asserts `state[btn]=true` for queued
  buttons with no source map — exactly how synthetic injects work. The player
  then walks during every subsequent `U.wait`. Same window in `use_warp` and
  `cross`. *Fix:* clear `pressQueue` alongside `state`.
  **DONE** — `wd_run`'s abort path drains `pressQueue` before clearing
  `state`. The mechanism is confirmed in the engine rather than inferred:
  `src/core/Input.lua:159-167` walks the queue every fixed step and sets
  `state[btn] = true` for any entry with no source map, commented in the
  engine itself as "synthetic pressQueue inject (tests/drivers)" — which is
  precisely what `walk()` writes. Not reproducible on demand (the watchdog
  needs a 120,000-frame op) but the fix is a strict superset of the old
  clear on a path that has already abandoned its op.

- [x] **4. STRUCT — the contract test (no file exists anywhere in the harness)**
  One boot, capture one battle observation and one overworld observation,
  assert every key `battle_policy` and `pred_holds` actually read is present.
  Catches #1 and would have caught the dead `"asked a QUESTION"` guard on the
  day it was written. **This is the highest-leverage item in the document** —
  four of the bugs found in the last two days are the same shape: a Python-side
  name the Lua side never emits.
  **DONE — `tests/contract.py`.** Boots its own love process under its own
  identity (`red-contract`) against a *copy* of the save, so it can never
  reach the campaign's game; captures one overworld observation and one
  battle observation and checks the 21 + 24 fields the readers actually
  read, each annotated with the rule that depends on it.
  When a field is missing it looks at the siblings that *are* there and
  reports `SPELLING MISMATCH -- shim emits 'max_hp'`: naming the culprit is
  the difference between a failing test and a fixed one. Self-tested by
  reintroducing BATTLE-1 synthetically — it catches exactly that one field.
  Three semantics that keep it honest: a key present but empty confirms the
  name and never fails; a field legitimately nil in a healthy sample
  (`status`, `disabledSlot`) is reported, never failed, because silence
  cannot prove a name wrong; and if `--save` is given but the party comes up
  empty the test dies rather than reporting "contract holds" against a new
  game — which is what its own first run did, and is the same silent pass it
  exists to stop. Both halves currently pass live.
  Run: `python tests/contract.py` (add `--save PATH` for a specific state).

---

### What Tier 0 changes about how the run plays

The claim run is set off once and left alone, so it is worth writing down
exactly what behaviour these four edits switch on. Waking `_hp_frac` makes
three rules in `plans/policy_model_v1.json` live for the first time:

| rule | was | now |
| --- | --- | --- |
| `battle_items` POTION `hp_below 0.3`, 4/battle | never fired | heals in battle below 30% |
| `flee_wild.hp_below 0.2` | never fired | leaves any wild below 20% |
| `setup.min_hp_frac 0.5` (TAIL_WHIP) | always allowed | no setup below 50% |

Two of the three only ever *stop* the party dying, and the third only ever
removes a move. `field_heal`, `field_cure` and `replacement` also call
`_hp_frac`, but on party mons, which always carried `max_hp` — those were
already working and are unchanged. The one genuinely new code path is
`OPS.battle_item`, which had never executed; it is now proven live, and its
call site is bounded anyway (`items_used` increments in `choose` before the
op runs, so a broken op could cost at most 4 turns in a battle, not a hang).

Fixing the blackout index only *adds* detections, and the walk-back it arms
already existed. The watchdog and the contract test cannot change play at
all: one runs on an abort path, the other in its own process against a copy.

---

## Tier 1 — the harness is lying to the model

The rule is *stop lying, stop hiding, stop refusing — never point.* These break
the first clause and the last.

- [x] **5. EXEC-1 · High · VERIFIED — the distance line reports a toll as map distance**
  `planner/executor.py:1495` prints `_goal_score` (which adds `4 + visits//8`
  per blocked edge) as *"the printed map puts X N step(s) from Y"*. Logged:
  `ROUTE_9 6 step(s) from ROUTE_10` — it is 1 hop. `GAME_CORNER 99 step(s) from
  CELADON_CITY` — the Game Corner is *inside* Celadon; 99 is the unreachable
  sentinel rendered as a distance. Also feeds the give-up test at `:1502`, so
  toll inflation can end a subgoal while the party stands still.
  *Fix:* print the untolled hop count, or say plainly the number includes a
  penalty; suppress the sentinel rather than rendering it.
  **DONE** — both the line and the give-up test now use the untolled hop
  count over the printed map plus this run's walked links. `ROUTE_9` to
  `ROUTE_10` reads 1, Cerulean to Celadon 4, Saffron to Celadon 2. Where the
  map has no answer it says so instead of printing 99. This also fixes the
  worse half of the bug: the toll grows with visits, so the give-up test
  could fire on a party that had not moved a tile.

- [x] **6. CLAIM · OVER — `_unopened_doors` prints destinations of unwalked doors**
  e.g. `(4,11)->CERULEAN_CAVE_1F`. Reporting a visible doorway is stop-hiding;
  naming where it goes is pointing. Our own note already calls reading
  undiscovered back doors out of the warp table forbidden.
  **DONE** — both renderings drop the destination; the doorway and the person
  standing at it are what is on screen. Entries already written in the old
  format are stripped on load, because `author.py` prints that ledger verbatim
  and a stale region nobody revisits would otherwise keep handing the ROM's
  answer over for the rest of the run.

- [x] **7. CLAIM · OVER — the town-map BFS itinerary is a solved route**
  The adjacency line is defensible as the item's face. The shortest path
  computed over `MAP_EDGES` and printed as *"stand in THOSE and cross the
  matching edge"* is not — the audit calls it the strongest violation in the
  runtime path. It also excludes interiors, so it is wrong as well as pointing.
  **DONE** — the itinerary block is gone, and the adjacency line loses its
  "To arrive, stand in one of THOSE and cross the matching edge" instruction;
  the adjacency fact itself stays. The legitimate thing the itinerary carried
  — a leg leaned on and never opened — is walked evidence and survives in the
  ranking, which prices exactly those legs. A comment in its place says not to
  reinstate the path in order to hang that annotation off it.

- [x] **8. CLAIM · OVER — `doors_text()` states interior connectivity**
  Which cave or tunnel opens off which road, and that an id under two roads
  joins them — which the Town Map does not draw. `SYS` calls the interior "the
  one thing it cannot work out for itself" immediately before handing it over.
  **DONE, user's call** — cut to the pins, not cut entirely. The listing of
  which named place opens off which road stays: a labelled pin beside a road
  is the map's own face, and it was written after a plan swapped Diglett's
  Cave for Rock Tunnel. What is deleted is every sentence stating what the
  ids MEAN — an id under one road, an id under two roads, a shared name over
  four. The model can see a token appear twice; drawing the inference is the
  part that belongs to it.

- [x] **9. CLAIM · OVER — `policy_author.py` CONTEXT hand-feeds ROM knowledge**
  `planner/policy_author.py:92–113`: Brock's roster and levels, Onix's typing
  and weakness, the rival's moveset, the forest encounter table, which items
  Viridian stocks versus Pewter and in what order to buy them. Per
  `fresh_run.sh:29` the spec authored under that prompt **fights every battle of
  the record run** — the widest blast radius of anything here.
  Some of it is legitimately run-observed ("uncured poison is the #1 recorded
  death" comes from the journal); the rosters, levels, movesets and shop timing
  do not. *Fix is mechanical:* the run already keeps a damage journal, a
  sightings ledger and a wipe count — assemble the same context from evidence.
  **DONE** — `CONTEXT` is gone, replaced by `policy_author.evidence_context()`,
  which reads the run's own battle log and the live observation. The brief is
  now: the party as it stands with movesets, what is in the bag, the 14 foes
  most fought with level ranges and counts, median and longest battle length,
  the damage each move has been WATCHED to do to each species and the level it
  was doing it at, the worst hitters and what they hit for, and where the party
  has blacked out. 1,805 battles on record; every line is a transcript.
  It was also describing a run that never happened — it opened "Squirtle lead"
  while this run has led with a Charmander since the first morning.
  Two attribution traps found and closed while building it: a faint replacement
  is logged as `pick_party`, not `battle_switch`, which filed sixteen PIDGEY
  GUSTs under a level-19 CHARMELEON; and only a `battle_move` may be credited
  with damage, or "heal with POTION" enters the move list as a move.

### What Tier 1 changes about how the run plays

Nothing in the executor's decisions: the drift number is now true rather than
inflated, which can only make the give-up test fire *less* often and never on
a stationary party. The three claim cuts remove text from prompts — the model
is told less, not told differently, and no code path branches on any of it.
The policy brief is the one place a behaviour change is possible, and only on
the next authoring run: a spec authored from this run's evidence may differ
from `policy_model_v1.json`. The existing artifact is untouched and still what
plays until a new one is authored and evaluated.

---

## Tier 2 — will stop or corrupt an unattended run

- [ ] **10. CHAIN-1 · High · VERIFIED — upkeep protection is off for the leg you're on**
  `fresh_discovery.sh:349` matches objective text exactly, so any reword
  (`reword_leg.py`, `insert_leg.py`, `_stage_missing`) silently drops the
  protection. 7 of 12 entries orphaned, 5 of 38 legs still protected.
  *Caveat from my own check:* in the current sample 4 of the 7 were deleted by
  the outline dedupe and 2 were swept as achieved — the reword mechanism is
  real but produced fewer of these orphans than the count implies.
  *Fix:* key on an id, or a normalised form written by the pass that rewords.
  Then re-check `outline.notes` and `outline.done` for the same break.

- [ ] **11. EXEC-3 · High · REPORTED — the replay path has no open-question guard**
  The `ASKING` guard exists only in `_run_traced`; `run_subgoal`'s dispatch
  (`:5764–5797`) never checks it, so a distilled macro runs its next op into an
  open UI. **422 macro steps in `plans/*.json` have an op following an
  `interact`.** Separately `settle()` returns `None` when `Bridge.obs()` fails
  and four sites call `obs.get(...)` unguarded (`:3796, :3920, :4030, :4323`);
  `_attempt` catches only `TimeoutError`, so the `AttributeError` kills the run.

- [ ] **12. DSL-1 · Medium · REPORTED — the validator checks names, not shapes**
  `_check_pred` (`author.py:559–643`) has branches for eight keys and passes the
  rest on key-membership alone. `pred_holds` then indexes `want["x"]` directly.
  Six model-authorable shapes crash the process mid-leg; two more are silently
  unsatisfiable (`{"party_nonempty": "true"}`) or instantly true
  (`{"slot_level": {"slot": 2, "level": 15}}` → `need = 0`, trains nothing).
  When the process dies, `last_state.json` is never written and the campaign
  falls back to a possibly stale `obs.json`.

- [ ] **13. MEM-1 · Medium · REPORTED — memory writes are non-atomic and a bad read zeroes it**
  `explored.json` is written with `write_text` ~25 times per round — truncate in
  place, no tmp+rename, no backup — and `_load_memory`'s outer `except` resets
  every structure to `{}` with no warning. A kill mid-save loses a day's walked
  map silently. The correct pattern is already in the repo twice
  (`bridge.py:78`, `shim.lua:784`). `distill()` writes plans the same way.

- [ ] **14. BRIDGE-1 · Medium · VERIFIED — a Lua reserved word in a macro key stalls 120 s**
  `send(op, **step)` forwards every key the model wrote into a Lua table
  literal with no whitelist. A key named `end`/`for`/`local`/`function` makes
  `load()` return nil, the shim never acks, the executor blocks its full
  timeout. Same silent-stall class as the nested-table bug that cost 28 dead
  two-minute waits in one night. Latent, not yet observed.

- [ ] **15. MISC-1 · Low · REPORTED — `stop_all.sh` pattern-kills box-wide**
  Kills `love .` and `xvfb-run` by pattern, against our own kill-only-what-you-
  started rule; `fresh_run.sh` already shows the right pattern.
  *(I have used this script all session — worth fixing on principle.)*

- [ ] **16. MISC-1 · Low · REPORTED — one ollama failure forfeits a whole escalation**
  `:4758` breaks out with every remaining round unspent, and `chat` has no retry.

---

## Tier 3 — accuracy of what the model is shown

- [ ] **17. MEM-2 · Medium · REPORTED — four copies of two rules, drifted**
  The "untried exits" filter exists at `:3105, :2140, :2306, :2905`; the `:3105`
  copy is missing the `_no_cross` filter the other three apply. Live: `ROUTE_5|1,0
  south` (the Saffron guards) is in `no_cross`, still in `frontier`, and
  advertised every round as a way never tried. The "map has unopened doorways"
  rule likewise exists four times; `:2867` doesn't exclude shut edges.
  Root cause: `exploration_text` is 541 lines assembling one string from ~14
  independently-guarded fragments.

- [ ] **18. PROMPT-1 · Medium · REPORTED — the authoring prompt is at the cliff at leg 7 of 38**
  `EVIDENCE_BUDGET` budgets `observed_text` only; `journal_text`, `drafts_text`
  and the embedded plan JSON are unbounded. The review prompt measures ≈12.3k
  against a 12,288-token usable window, and ollama drops the **front**, where
  the predicate vocabulary lives. `_fit`'s `AREA CODES` block never matches its
  own header regex, so it falls back to a blunt tail cut that drops *WHERE
  EVENTS ACTUALLY FIRED* and *PROVEN UNREACHABLE*. The escalation prompt has no
  budget at all and `_atlas_text` grows with every map ever seen.

- [ ] **19. SHIM-2 · Medium · REPORTED — four shim defects that answer wrongly rather than erroring**
  `bfs_to_edge`'s ledge branch returns a cell without `landing_ok` (`:1143`), so
  `cross` walks there and presses into a wall; arrow tiles are treated as
  standable (`:1131`) though `warp_reach` and `bfs_dir` both refuse them;
  `ui_shop_up` is satisfied by the Start menu so `buy`/`sell` will drive
  whatever is open (`:1774`, `:1942`); HMs are not `keyItem` in the engine data
  (`:2405`), so `toss` offers `HM_CUT` as spare and `obs.key_items` omits every HM.

- [ ] **20. SHIM-3 · Medium · REPORTED — `observe()` is unbounded and freezes the heartbeat**
  Called bare outside `wd_run` (`:3970`, `:4023`). Three full-map floods per
  cycle plus a 72×72 tile scan, zero yields — ~17k `canMove` calls in one frame
  outdoors. The heartbeat only ticks on driver yields, so it *stops* during
  `observe`, reading as yield starvation: the exact misdiagnosis the file header
  describes chasing. `objreach` is `reach` recomputed; caching it is free.

- [ ] **21. MISC-1 · Low · REPORTED — visits are double-counted**
  `:1089` and `:1690` both bump on every escort hop, inflating the model-facing
  "you have been here N times" and halving the effective threshold at `:2530`.

- [ ] **22. MISC-1 · Low · REPORTED — `_battle_regions` doesn't persist**
  Its sibling `contested` does, so on a resumed attempt a gym you lost in is no
  longer exempt from the re-entry refusal.

- [ ] **23. MISC-1 · Low · REPORTED — `_plan_done` is write-only**
  The "waypoints stay walked" behaviour its comment describes does not exist.

- [ ] **24. MISC-1 · Low · REPORTED — `run_subgoal` logs `at=None,None`**
  x/y live under `obs["player"]`. The field was added specifically to pin the
  tile a cross failed from.

---

## Tier 4 — claim structure and measurement

These need a decision from the user, not a patch from me.

- [ ] **25. CLAIM-1 · High · VERIFIED — no subgoal records an author**
  The recorded fix was "written once at creation and never touched". The
  never-touched half shipped; the written-at-creation half did not.
  `subgoal_provenance` has one writer in the codebase — a `setdefault` in
  `distill()` filling the literal `"unknown (pre-audit)"`. **430 subgoals: 294
  absent, 136 placeholder, 0 naming an author.** File-level `authored_by` is
  well covered and honest, but cannot distinguish a model-written subgoal from
  a hand-inserted one in the same file — the exact distinction once overstated.
  *Fix:* write it in `author.py` at creation; backfill nothing.

- [ ] **26. CLAIM-2 · Medium · VERIFIED — the oracle has never scored the policy that plays**
  Its one live run (26,998 turns, 86.9% agreement) predates commit `7480e0d`,
  which made the model-authored spec actually play. No orchestrator passes
  `--score-battles`. The quality meter and the artefact being claimed have never
  met. The offline gym comparison (47/67 vs 36/67) is real but is 67 turns.

- [ ] **27. CLAIM · BORDERLINE — three handovers to rule on**
  - `SEEDED_BADGES` — badge names are on the box, but the leader↔badge pairing
    and objective wording are harness-authored, and `_check_badges` re-inserts
    them against the model's choice. Honest framing: 8 of ~30 legs are seeded.
  - `edges_text()` — the full outdoor adjacency of Kanto from turn 0, before the
    Town Map is in the bag. **Gate it on holding `TOWN_MAP` and it lands cleanly.**
  - `model_view` leftovers — strips `flags` and `battle.probe` correctly, but
    still ships `region_anchors` (harness bookkeeping) and `events` (the raw
    engine emit-name list).

- [ ] **28. STRUCT — RL-refines is one of four claim pillars and has no implementation**
  No torch, no reward spec, no nav net, no distilled battle net. A legitimate
  choice, but the claim structure currently overstates what is built.

- [ ] **29. STRUCT — the headline metric is computed nowhere**
  `SPD_DESIGN.md` names the escalation-decay curve as "the headline metric".
  Escalations per leg per attempt, straight out of the journal — a short script,
  not a project. It is the number that says whether any of this compounds.

- [ ] **30. STRUCT — escalation is acting as the runtime pilot, not the offline compiler**
  **2.6 of 3.05 hours of executor wall time is model inference**, 1,271
  escalation calls at 7.4 s median. Escalation succeeds 49% of the time and only
  **38 of 158 successes were distilled back into a plan**, so the same walls are
  re-solved live rather than compiled away. `distill_refused_empty` fires 54
  times and is correct to refuse. Worth knowing before scaling to 38 legs.

- [ ] **31. STRUCT — three functions carry most of the risk**
  `escalate` 846 lines, `_run_traced` 791, `exploration_text` 541, with 310- and
  213-line closures nested inside two of them. MEM-2's four-copy drift and the
  two-dispatch-site divergence in EXEC-3 are both direct consequences.

---

## What the audit says to keep

Not a to-do list — a list of things not to break, and worth lifting elsewhere.

- **Verify against the save, never the menu** — `buy`/`sell`/`toss`/`party_swap`/
  `use_item` confirm through `bag_count` or `G.save`; `save_game` confirms against
  the save file's mtime. `shim.lua:1985, :2905, :2232, :3769`
- **On-demand transitive hopelessness**, never cached, because taking a fossil
  opens ways that were shut. `executor.py:1195–1216`
- **Failure asymmetry** — a self-loop never overwrites a real destination;
  "couldn't reach" stays distinct from "stood at it and it refused".
  `executor.py:1748–1760, :1841–1852`
- **Observation beats conclusion at load time** — a walked edge revokes a stored
  `no_cross` proof, and it `print`s rather than logs because the log isn't open
  yet. `executor.py:825–855`
- **Choose-only model passes** — merges and blocker questions come back as an
  index the harness maps to verbatim text. The model selects; the harness never
  composes.
- **Generation before formatting** — `outline_eras` asks loosely in prose, then
  imposes shape only on the final flattening. `author.py:2067–2160`
- **Progress-aware round budgets** — a refused round is free, capped at three.
- **Reading the screen from inside the yield hook** — `shim.lua:68–88`
- **Positional-only resume** — a deed is never inferred from where the party stands.
- **The exact-signature truncation detector** — matches ollama's `num_ctx/2 + 3`
  window rather than a threshold, so it never cries wolf.
- **Comments that carry the evidence and correct the record**, including one that
  retracts an invented justification.
