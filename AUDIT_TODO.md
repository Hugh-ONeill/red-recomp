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

- [x] **10. CHAIN-1 · High · VERIFIED — upkeep protection is off for the leg you're on**
  `fresh_discovery.sh:349` matches objective text exactly, so any reword
  (`reword_leg.py`, `insert_leg.py`, `_stage_missing`) silently drops the
  protection. 7 of 12 entries orphaned, 5 of 38 legs still protected.
  *Caveat from my own check:* in the current sample 4 of the 7 were deleted by
  the outline dedupe and 2 were swept as achieved — the reword mechanism is
  real but produced fewer of these orphans than the count implies.
  *Fix:* key on an id, or a normalised form written by the pass that rewords.
  **DONE, both halves.** `reword_leg.py` is now a RENAME: it carries the new
  wording into every ledger keyed on the old one — `outline.upkeep`,
  `.notes`, `.done`, `.stages`, `leg_audit_redo`, `outline_pushes`,
  `outline_pulls`, `outline_pulls_failed` — matching the whole key field, so
  "Reach Cerulean City" cannot rewrite itself inside "Reach Cerulean City
  Gym". And `_reconcile_upkeep()` runs at the end of authoring, after the
  three passes that come AFTER the sidecar is written: an entry whose
  wording lost a dedupe follows the objective to its surviving name (the
  dedupe records which absorbed which), and one that is simply gone is
  dropped and said out loud. The dangerous case was never the orphan — it
  was the SURVIVOR left unprotected, which turns an upkeep objective the
  world may not offer into a leg that stops the chain.

- [x] **11. EXEC-3 · High · REPORTED — the replay path has no open-question guard**
  The `ASKING` guard exists only in `_run_traced`; `run_subgoal`'s dispatch
  (`:5764–5797`) never checks it, so a distilled macro runs its next op into an
  open UI. **422 macro steps in `plans/*.json` have an op following an
  `interact`.** Separately `settle()` returns `None` when `Bridge.obs()` fails
  and four sites call `obs.get(...)` unguarded (`:3796, :3920, :4030, :4323`);
  `_attempt` catches only `TimeoutError`, so the `AttributeError` kills the run.
  **DONE.** The `ASKING` guard now runs on the replay path too and ends the
  macro, which fails the subgoal and hands the box to escalation — where the
  words go to the model. Answering is not the harness's to do: an `interact`
  that means to say yes carries `answer`, so a macro that walked into an
  unanswered question is a macro that is wrong.
  `settle()` never returns None. Rather than guard four call sites out of
  forty, the source returns `{}` — just as falsy for every `if obs:` in the
  file, and safe for every `obs.get(...)`.

- [x] **12. DSL-1 · Medium · REPORTED — the validator checks names, not shapes**
  `_check_pred` (`author.py:559–643`) has branches for eight keys and passes the
  rest on key-membership alone. `pred_holds` then indexes `want["x"]` directly.
  Six model-authorable shapes crash the process mid-leg; two more are silently
  unsatisfiable (`{"party_nonempty": "true"}`) or instantly true
  (`{"slot_level": {"slot": 2, "level": 15}}` → `need = 0`, trains nothing).
  When the process dies, `last_state.json` is never written and the campaign
  falls back to a possibly stale `obs.json`.
  **DONE, and the runtime hardened as well as the validator.** `pred_holds`
  no longer raises on anything: every branch that indexed a model-written
  value now coerces what is obvious and returns False otherwise, including
  the `raise ValueError` on an unknown key. Verified against all seven
  crashing shapes and both silent ones — `{"party_nonempty":"true"}` is now
  true, and `{"slot_level":{"slot":2,"level":15}}` no longer closes the leg
  instantly having trained nothing (`min` missing is not `min` zero).
  Because a crash became a silent stall, malformations are collected and
  NAMED once per leg on stdout and in the journal.
  *Correction to the finding:* `main()` already had a crash handler writing
  `last_state.json` from a fresh Bridge, so that half was not happening —
  though the crash path does lose which leg failed.

- [x] **13. MEM-1 · Medium · REPORTED — memory writes are non-atomic and a bad read zeroes it**
  `explored.json` is written with `write_text` ~25 times per round — truncate in
  place, no tmp+rename, no backup — and `_load_memory`'s outer `except` resets
  every structure to `{}` with no warning. A kill mid-save loses a day's walked
  map silently. The correct pattern is already in the repo twice
  (`bridge.py:78`, `shim.lua:784`). `distill()` writes plans the same way.
  **DONE.** `_save_memory` writes tmp+rename and keeps the previous good file
  as `explored.json.prev`; a ledger that will not parse falls back to it and
  says so, and if BOTH are unreadable it shouts rather than starting empty in
  silence. A genuinely fresh run stays silent, which is the distinction that
  was missing. `distill()`'s plan write gets the same treatment — that file
  is what the next attempt replays from, so a truncated one loses every leg
  in it. `fresh_discovery.sh` clears `.prev` and `.tmp` with the ledger, or a
  fresh chain would inherit a previous chain's whole walked map.
  Tested by truncating the live file mid-write: the day's map came back.

- [x] **14. BRIDGE-1 · Medium · VERIFIED — a Lua reserved word in a macro key stalls 120 s**
  `send(op, **step)` forwards every key the model wrote into a Lua table
  literal with no whitelist. A key named `end`/`for`/`local`/`function` makes
  `load()` return nil, the shim never acks, the executor blocks its full
  timeout. Same silent-stall class as the nested-table bug that cost 28 dead
  two-minute waits in one night. Latent, not yet observed.
  **DONE.** Every key goes out in bracket form — `["end"]=1` — which is legal
  Lua for any key at all, so the class cannot recur; it also covers keys that
  are not identifiers (`["2bad"]`). Confirmed with luajit that the old form
  fails to load on `end`/`for`/`local`/`function` and the new one parses all
  of them, then confirmed live: the contract test drives bootstrap, walk,
  cross, grind and a battle through the new serialiser.

- [x] **15. MISC-1 · Low · REPORTED — `stop_all.sh` pattern-kills box-wide**
  Kills `love .` and `xvfb-run` by pattern, against our own kill-only-what-you-
  started rule; `fresh_run.sh` already shows the right pattern.
  *(I have used this script all session — worth fixing on principle.)*
  **DONE — `rig.sh` + a rewritten `stop_all.sh`.** The launchers register what
  they start; each entry carries the process's `/proc` start time, so a reused
  PID can never be mistaken for ours. The pattern survives as a REPORT ONLY —
  losing "verify it is down" would be worse than the bug — and `--force` is
  the old behaviour, now asked for by name. `fresh_run.sh` also backgrounds
  the executor so the EXIT trap can reach it: in the foreground, a SIGTERM ran
  the trap, killed the game, and left the executor talking to a dead bridge,
  which is the exact contamination the script was written for.
  Tested: a stale registry entry leaves its PID alone, and an unregistered
  `love .` look-alike is reported and survives.

- [x] **16. MISC-1 · Low · REPORTED — one ollama failure forfeits a whole escalation**
  `:4758` breaks out with every remaining round unspent, and `chat` has no retry.
  **DONE.** `chat()` retries twice on a dropped or refused connection with a
  short backoff, and once on a timeout (which has already spent its 300s) —
  unwrapping `URLError` so the timeout budget actually applies. The
  escalation loop spends ONE round on a failure instead of breaking out, and
  only gives up after three in a row.

### What Tier 2 changes about how the run plays

One behaviour change, deliberate: a replayed macro now STOPS at an
unanswered question instead of running its next op into the open box. That
fails the subgoal, which escalates — the same path the escalation loop has
always taken, and the only one by which the question gets answered.

Everything else is failure handling. A predicate that used to crash now
returns False and says why; a chat that used to forfeit a budget now costs
one round; a ledger that used to vanish now falls back. None of it changes
what the run does when things go right, and each one only widens what it
survives when they do not.

---

## Tier 3 — accuracy of what the model is shown

- [x] **17. MEM-2 · Medium · REPORTED — four copies of two rules, drifted**
  The "untried exits" filter exists at `:3105, :2140, :2306, :2905`; the `:3105`
  copy is missing the `_no_cross` filter the other three apply. Live: `ROUTE_5|1,0
  south` (the Saffron guards) is in `no_cross`, still in `frontier`, and
  advertised every round as a way never tried. The "map has unopened doorways"
  rule likewise exists four times; `:2867` doesn't exclude shut edges.
  Root cause: `exploration_text` is 541 lines assembling one string from ~14
  independently-guarded fragments.
  **DONE for the first rule; the second is DECLINED with reasoning.**
  The frontier-minus-walked-minus-proven arithmetic turned out to exist in
  SIX places, not four, and two had drifted. All six now call one
  `_frontier_left(region)`.
  The "map has unopened doorways" rule: three of the four copies do exclude
  shut edges. The fourth (`observe`'s `ever` set) is not the same rule — the
  others ask "is this doorway still UNOPENED", where a door that turned you
  back is not opened; that one asks "is that part of the floor somewhere I
  have never STOOD", where walking into a door that refused you means you
  stood at it. Filtering shut edges there would have the note claim the run
  has never been somewhere it demonstrably has. Left alone, with a comment
  saying why so it is not "fixed" later.

- [x] **18. PROMPT-1 · Medium · REPORTED — the authoring prompt is at the cliff at leg 7 of 38**
  `EVIDENCE_BUDGET` budgets `observed_text` only; `journal_text`, `drafts_text`
  and the embedded plan JSON are unbounded. The review prompt measures ≈12.3k
  against a 12,288-token usable window, and ollama drops the **front**, where
  the predicate vocabulary lives. `_fit`'s `AREA CODES` block never matches its
  own header regex, so it falls back to a blunt tail cut that drops *WHERE
  EVENTS ACTUALLY FIRED* and *PROVEN UNREACHABLE*. The escalation prompt has no
  budget at all and `_atlas_text` grows with every map ever seen.
  **DONE, and the finding is understated — this has already happened 48
  times.** The logs hold 44 truncations at the 12288 cap and 4 at an older
  8192, and every one is the REVIEW prompt, each immediately after
  `[drafts] 6 earlier draft(s) for this goal shown to the review`. Drafts
  were the unbudgeted block. Reproduced from the artifacts at 13,029 tokens
  against the cap; with the three growing blocks budgeted together it is
  11,253, and the vocabulary sits after them where a front-drop cannot
  reach it.
  `_fit`'s splitter is fixed: it wanted 12+ chars of `[A-Z ,'-]` after the
  first letter, which `AREA CODES you may use...` fails on the `y` of
  "you". Four consecutive capitals is what every real header has.
  `prompt_guard()` now warns BEFORE the call and names the biggest parts —
  `chat()`'s existing detector fires afterwards and as a bare number, which
  never once said "it is the drafts".
  The escalation prompt measures ~5,000 tokens today, so it was never at
  the cliff, but `_atlas_text` was 910 of them over 39 maps at leg 8 of 38
  and Kanto has ~250. It is now bounded near-first at 4,000 chars: with 289
  maps loaded it holds at ~1,000 tokens, current map first, and says how
  many were dropped.

- [x] **19. SHIM-2 · Medium · REPORTED — four shim defects that answer wrongly rather than erroring**
  `bfs_to_edge`'s ledge branch returns a cell without `landing_ok` (`:1143`), so
  `cross` walks there and presses into a wall; arrow tiles are treated as
  standable (`:1131`) though `warp_reach` and `bfs_dir` both refuse them;
  `ui_shop_up` is satisfied by the Start menu so `buy`/`sell` will drive
  whatever is open (`:1774`, `:1942`); HMs are not `keyItem` in the engine data
  (`:2405`), so `toss` offers `HM_CUT` as spare and `obs.key_items` omits every HM.
  **DONE, all four.** The ledge branch now applies `landing_ok` like the two
  branches beside it (fail-open on a probe error, so it can only reject
  seams with genuinely nothing behind them). Arrow tiles are no longer
  queued or accepted as edge cells, matching `warp_reach` and `bfs_dir`.
  `ui_shop_up` asks for `ShopMenu` and its BUY/SELL list by name instead of
  for "any list at all" — the START menu passed the old test, so a stray one
  made `buy` press A into SAVE/OPTION/EXIT and call it a shop. And one
  `is_key_item()` treats `machine.kind == "HM"` as a key item for both
  readers: gen 1 refuses to toss or sell an HM and says so on screen.

- [x] **20. SHIM-3 · Medium · REPORTED — `observe()` is unbounded and freezes the heartbeat**
  Called bare outside `wd_run` (`:3970`, `:4023`). Three full-map floods per
  cycle plus a 72×72 tile scan, zero yields — ~17k `canMove` calls in one frame
  outdoors. The heartbeat only ticks on driver yields, so it *stops* during
  `observe`, reading as yield starvation: the exact misdiagnosis the file header
  describes chasing. `objreach` is `reach` recomputed; caching it is free.
  **DONE.** One fill per observation instead of two (the third, `region_reach`,
  is genuinely different — `no_ledges`). And the heartbeat now stamps
  "observe" on entry and hands the label back on exit, so a sample taken
  mid-observation reads as an observation in progress rather than as nothing
  moving at all — which is the misdiagnosis the file header describes
  chasing, produced by the very file written to prevent it.

- [x] **21. MISC-1 · Low · REPORTED — visits are double-counted**
  `:1089` and `:1690` both bump on every escort hop, inflating the model-facing
  "you have been here N times" and halving the effective threshold at `:2530`.
  **DONE.** Both writers go through `_count_visit`, which already had the
  repeat guard `_note` was using; it just never covered the other writer.

- [x] **22. MISC-1 · Low · REPORTED — `_battle_regions` doesn't persist**
  Its sibling `contested` does, so on a resumed attempt a gym you lost in is no
  longer exempt from the re-entry refusal.
  **DONE.** Saved and loaded beside `contested`, and blanked with it.

- [x] **23. MISC-1 · Low · REPORTED — `_plan_done` is write-only**
  The "waypoints stay walked" behaviour its comment describes does not exist.
  **DONE by DELETING it, not by implementing it.** The resume immediately
  below superseded that design on purpose, and says why in its own comment:
  the union version "skipped the navigation scaffold and stranded a bare
  flag target in Cerulean while its giver waited on the ship", because
  position is not an achievement. The code is right and the comment outlived
  the behaviour. Implementing the comment would reinstate the bug.

- [x] **24. MISC-1 · Low · REPORTED — `run_subgoal` logs `at=None,None`**
  x/y live under `obs["player"]`. The field was added specifically to pin the
  tile a cross failed from.
  **DONE.** x/y read from `obs["player"]`. Measured before the fix: 13 of 13
  `step` lines in the live log carried `at=None,None`.

### What Tier 3 changes about how the run plays

More than the other tiers, because these are answers rather than crashes.
The model stops being told that a proven wall is an unopened road, stops
being told it has been somewhere twice as often as it has, and gets a
review prompt that is not missing its front. `cross` stops walking to edge
cells with nothing behind them and to arrow tiles that slide it away. `buy`
stops driving whatever menu happens to be open. HMs stop being offered as
bag ballast.

The two removals are the ones to watch: `_plan_done` is gone (it was never
read) and the atlas is now truncated near-first past 4,000 chars. Neither
changes a decision the run makes today.

### One thing the audit did not raise — found here, DONE

- [x] **CLAIM · OVER — unwalked doors named their destination in three more
  places.** `exploration_text`'s untried-exit list, `_untried_exits` (which
  feeds the refusal and free-round text), and `_atlas_text` — in every
  escalation prompt — all printed `obs.map.warps[].dest` for doors the run
  had never opened, out of the same warp table item 6 removed from the
  unopened-doors ledger. A wider surface than item 6, since the model routes
  off these.
  **User's call, 2026-08-17: `(4,11)->UNKNOWN` until entered.** Once walked
  it shows the region the run actually came out in, which is better than the
  ROM's answer — a region rather than a map, and earned. MAP EDGES keep
  their destinations: which roads touch is drawn on the Town Map. The atlas
  stops STORING the observed destination rather than hiding it at render
  time, so the ledger carries no warp-table knowledge at all.
  One consequence worth stating: an unopened door used to be ranked by
  whether its secret destination named a map already visited — the same leak
  wearing a sort key. Unknown now means unknown, which sorts it with the
  frontier, where a door nobody has opened belongs.

- [x] **EXPLORE — one map under four region labels re-advertised its own doors.**
  Found by watching a live test chain wander Cerulean for an hour (user:
  "its not exploring correctly"). Cerulean carries FOUR region labels. The
  one the run lives in had 426 visits and all eleven exits taken; a label it
  had stood in TWICE inherited the whole city's doorway list and reported
  ten of them as ways never tried — so every round the model was told there
  was somewhere new two legs away whose first step was the trashed-house
  door it had opened 37 times. It went, and did it again, for hours. Doing
  exactly what it was told: ours, not the model's.
  **DONE (`a3daa6f`).** The ledger is keyed by region, which is right for
  writing and wrong for reading: a coordinate key is the same TILE whichever
  label you stand in, so "have I taken this exit" is a fact about the map.
  All four readers share one `_taken_here(region)`. Directions stay
  region-local — on a split map the stub side cannot reach the far seam, and
  saying otherwise would delete the discovery that opens the map (Route 4);
  `_no_cross` clears a genuinely unreachable seam at a cost of one attempt.
  Measured on the live ledger: phantom untried exits across multi-label maps
  **18 → 8**, the two-visit Cerulean label **10 → 3**.

- [x] **EXPLORE — "NOWHERE in your atlas" points at doors instead of roads.**
  Standing in Cerulean aimed at Vermilion, the model is told *"VERMILION_CITY
  is NOWHERE in your atlas: no door you have ever taken leads there. The only
  doors never opened are listed here — one of them, or something never
  touched, is how it opens."* The run HAS walked `ROUTE_5 -> UNDERGROUND_PATH`,
  one door south; what it has never done is come out the far end. The sentence
  is true about Vermilion and false about the road, and it sends the run
  door-hunting in the city it is standing in.
  **DONE (`d4f70c8`), and the sentence was the smaller half.** The list that
  should have carried the answer — "places you have already been that still
  have ways you have NEVER taken" — built a line per candidate and joined
  `sorted(elsewhere)[:6]`: sorted on the rendered STRING, alphabetically by
  region id. Twelve candidates; the six that survived began C, M and P, and
  four had no walked route at all. `UNDERGROUND_PATH_ROUTE_5|1,1` — two legs
  away over walked ground, THREE exits never taken, and the road to
  Vermilion — sorted tenth and was cut. **The one room that mattered was
  dropped by its initial letter.** Ranked now by reachable, then nearest,
  then most left to do: it moves to second.
  The sentence itself now says the truest thing available — of the ground
  already walked, which does the printed map put nearest, and how to get
  there. Both halves were already permitted (the walked ledger is the run's
  own, the distance is the Town Map's) and it names no door beyond ground
  already covered. Rendered against the stuck state it reads: *"the closest
  ground you HAVE walked to it is ROUTE_5|1,0 … 3 leg(s) from VERMILION_CITY
  … What lies beyond that edge you have not seen."*

- [x] **EXPLORE — a thing touched once is retired for ever.**
  The Town Map has never been obtained in any run. During `pick_starter`, on
  leg 1, the model pressed `BLUESHOUSE_DAISY1` ("AAAAAAA is out at Grandpa's
  lab" — the pre-Pokedex line, no gift) and `BLUESHOUSE_TOWN_MAP` (the wall
  decoration), because the harness had just said *"Press A on them before you
  leave — it is free"*. Both went into `_tried_objs` permanently, and the
  "things you have not touched" line only ever lists untouched things. The
  free-round re-talk written for exactly this is gated on
  `target_key.startswith("flag:")`, so it never fires in Blue's house.
  The general class: this game's design is that people change what they say
  once the world changes, and the harness retires them after one visit.
  **DONE (`935d24a`).** Correction found while building it: Daisy's gate is
  `EVENT_GOT_STARTER`, not the Pokedex — and the line the log recorded her
  saying is the branch the script takes when that flag is FALSE, so the run
  talked to her minutes before picking the starter that unlocks her gift.
  Nothing is un-said: the touch stands, the lifetime ledger stays monotone
  (fourteen readers depend on it), and a per-object mark of what the world
  was at press time drives one new line — *WORTH ANOTHER WORD* — that states
  the fact and leaves the judgment where it belongs.
  `_touch_bag` had already tried this keyed on KEY ITEMS, which cannot see a
  badge and cannot see the starter. The mark is `[badges, flag count, bag
  kinds]`, which can. Bounded twice: only while the mark differs, and three
  times per thing per run — counted per WORLD STATE, not per render, or a
  subgoal stuck in one room burns all three before the model acts on one.
  Already-touched things backfill at the current mark, so nothing floods on
  the first boot.
  *Checked for a cheaper signal first, per the user's question:* there is no
  importance marker anywhere — flags are a flat `name -> bool` table with no
  metadata. The one derivable split, `check_flag` vs `set_flag` in the
  recomp's scripts, is **59 gates to 9 records**, so it barely discriminates.
  Ranking the event was the wrong idea; ranking the delta against the thing
  you touched is the right one.

- [x] **EXPLORE — the far side of a door was never recorded as opened.**
  An edge is keyed on the tile you DEPARTED from, so city -> house writes
  `27,11` on the city and house -> city writes `3,0` on the house. The
  city-side tile of the back door never gets an entry, because you only ever
  ARRIVE on it. Cerulean's `(27,9)` was still reported as never opened after
  the run had come out through it **32 times** — and it is the way south.
  (Compare `(9,9)` at the badge house, which IS recorded, purely because the
  run once happened to leave through it.) User spotted it in the rendered
  output. **DONE (`862c7aa`)** — recorded on arrival, only when the tile
  landed on IS a doorway AND leads back where you came from. It also
  unblocks the fully-worked test, which prunes any room whose map still has
  an unopened doorway.

- [x] **EXPLORE — "fully worked" and "worth another word" contradicted each other.**
  User's question. `note_searched` means "every exit taken, everything
  touched" *as of when it was checked*, and the re-offer ledger exists
  because a room stops being finished when the world moves. Printing both in
  one prompt makes the model pick. **DONE (`862c7aa`)** — the worked CLAIM
  yields where something is worth another word ("you HAD fully worked this
  area, but that was before what has happened since"), and rooms with a live
  re-offer drop out of the finished list. The searched LEDGER is untouched
  and still monotone.
  *Declined the wider version:* expiring worked-ness on any flag would
  un-finish every room in the game each time a trainer is beaten, and the
  escort would drag the run back through all of them — the churn the ledger
  exists to prevent.

- [x] **EXPLORE — a seam proof never expired, while a shut door always did.**
  Followed from the question above. `shut_at` re-offers a door once the world
  mark differs; `_no_cross` was a bare set, proven once and shut for ever.
  Seven live proofs, one of them `ROUTE_5|1,0 south` — the Saffron guards,
  the seam that opens when the run has the drink, which nothing would ever
  have offered again. **DONE (`06b446a`)** — parallel `_no_cross_at` mark and
  one `_sealed(region)`, same shape as the touch marks; the set and the saved
  ledger are unchanged. Backfilled at the current mark so nothing re-opens on
  the first boot. A re-offered seam that is still shut costs one attempt and
  re-proves itself; the enforcement that once refused the op is already
  disabled, so nothing can trap the run.

- [x] **STRUCT — a second test: `tests/replay_smoke.py`.** The contract test
  proves the SHAPE of an observation; this proves the executor still PLAYS —
  bootstrap, settle, a macro replayed step by step, a predicate satisfied,
  the ledger written — and runs the two predicate shapes that used to end
  the process, checking they are refused AND named. Between them they cover
  the paths a day of edits keeps touching. Both pass live.

---

## Tier 4 — claim structure and measurement

These need a decision from the user, not a patch from me.

- [x] **25. CLAIM-1 · High · VERIFIED — no subgoal records an author**
  The recorded fix was "written once at creation and never touched". The
  never-touched half shipped; the written-at-creation half did not.
  `subgoal_provenance` has one writer in the codebase — a `setdefault` in
  `distill()` filling the literal `"unknown (pre-audit)"`. **430 subgoals: 294
  absent, 136 placeholder, 0 naming an author.** File-level `authored_by` is
  well covered and honest, but cannot distinguish a model-written subgoal from
  a hand-inserted one in the same file — the exact distinction once overstated.
  *Fix:* write it in `author.py` at creation; backfill nothing.
  **DONE (`bd63eb8`).** Written the moment a subgoal is created. My own count
  across 742 plan files: 3,906 absent, 594 placeholder, 24 naming a model —
  and all 24 are in the old hand-seeded spine files, so no leg plan the
  outline chain writes had one. Nothing backfilled.

- [x] **26. CLAIM-2 · Medium · VERIFIED — the oracle has never scored the policy that plays**
  Its one live run (26,998 turns, 86.9% agreement) predates commit `7480e0d`,
  which made the model-authored spec actually play. No orchestrator passes
  `--score-battles`. The quality meter and the artefact being claimed have never
  met. The offline gym comparison (47/67 vs 36/67) is real but is 67 turns.
  **DONE (`bd63eb8`), as a switch rather than a run.** `RED_SCORE_BATTLES=1`
  does what `--score-battles` does. Adding the flag to `fresh_run.sh` means
  editing a shell script that may be mid-chain, and the rule here is that a
  running script is never edited — an env var can be set on the next launch.
  Scoring probes and never chooses, so it costs turns, not correctness.
  The scoring RUN itself is still to do.

- [x] **27. CLAIM · BORDERLINE — three handovers to rule on**
  - `SEEDED_BADGES` — badge names are on the box, but the leader↔badge pairing
    and objective wording are harness-authored, and `_check_badges` re-inserts
    them against the model's choice. Honest framing: 8 of ~30 legs are seeded.
  - `edges_text()` — the full outdoor adjacency of Kanto from turn 0, before the
    Town Map is in the bag. **Gate it on holding `TOWN_MAP` and it lands cleanly.**
  - `model_view` leftovers — strips `flags` and `battle.probe` correctly, but
    still ships `region_anchors` (harness bookkeeping) and `events` (the raw
    engine emit-name list).
  **ALL THREE DONE (`bd63eb8`), user's rulings.**
  *SEEDED_BADGES:* kept and stated. Ruled pamphlet tier — badge names are on
  the box and the leader pairing is what the booklet tells a player. What
  changed is that `SPD_DESIGN.md` now has its own section saying eight of
  roughly thirty objectives are seeded, instead of leaving it to be found in
  `_check_badges`.
  *edges_text:* gated on the TOWN MAP being in the bag, and so are
  `doors_text()` and the executor's "THE TOWN MAP: X attaches to" line — the
  same artifact under its own label; gating one and not the others would be
  incoherent. The gate was dismissed once, correctly, because the map had
  never been obtained in any run; that is now fixed at both ends (the
  re-offer ledger, plus a REMOTE list so a room in Pallet can surface from
  Cerulean), so the errand is reachable and the gate is a gate rather than a
  wall. Side effect: the author prompt drops 13,685 -> 10,736 chars, which
  buys back ~740 tokens against item 18's cliff.
  *model_view:* both stripped. `region_anchors` sits under `map`, not the top
  level, so the first attempt did nothing until it was checked against a real
  observation — and the map dict is copied before editing, since `o` is a
  shallow copy and stripping in place would have taken it out of the
  executor's own observation too.

- [x] **28. STRUCT — RL-refines is one of four claim pillars and has no implementation**
  No torch, no reward spec, no nav net, no distilled battle net. A legitimate
  choice, but the claim structure currently overstates what is built.
  **DONE (`bd63eb8`) — restated, not built, user's call ("we might need it
  later when doing the footprint stuff").** `SPD_DESIGN.md` now opens that
  section with NOT BUILT: no torch, no reward spec, no nets, and the record
  run uses none. What is built, and is the actual differentiator, is
  learning-free play plus evidence-driven replanning. The design is kept as a
  design and marked as one, because the claim should show what was considered
  and not done as well as what was done.

- [ ] **29. STRUCT — the headline metric is computed nowhere** *(deferred by
  the user; 30 waits on it)*
  `SPD_DESIGN.md` names the escalation-decay curve as "the headline metric".
  Escalations per leg per attempt, straight out of the journal — a short script,
  not a project. It is the number that says whether any of this compounds.

- [ ] **30. STRUCT — escalation is acting as the runtime pilot, not the offline compiler**
  **2.6 of 3.05 hours of executor wall time is model inference**, 1,271
  escalation calls at 7.4 s median. Escalation succeeds 49% of the time and only
  **38 of 158 successes were distilled back into a plan**, so the same walls are
  re-solved live rather than compiled away. `distill_refused_empty` fires 54
  times and is correct to refuse. Worth knowing before scaling to 38 legs.

- [ ] **31. STRUCT — three functions carry most of the risk** *(left alone by
  the user for now — a between-claim-runs job)*
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
