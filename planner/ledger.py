#!/usr/bin/env python3
"""ONE candidate list per (target, area) — the ledger.

EXPLORE_DESIGN.md §3, Stage 1. Three readers, one source:

  * the PROMPT renders it (in place of the exits / things / people
    paragraphs of exploration_text);
  * the GUARD in _run_traced consults it — an op whose key the ledger holds
    is never refused for being back-tracking, revisiting or repeating; only
    an OFF-LEDGER key (a coordinate or name that is not here) and an op
    already proven impossible with the world unchanged are;
  * `explore` (Stage 2) acts on it — the deterministic frontier step is
    "the first candidate whose status is untried / untouched / unspoken,
    else the nearest area that still has one".

Never refuse what you offer; never offer what you would refuse. Measured
over 32,517 rounds (planner/repeats.py) the old arrangement refused 30%
of rounds, 1,025 + 803 of them for an exit the same prompt had listed as
"prefer these", and the refusals yielded on the third go — the harness
teaching persistence. The ledger cannot contradict itself because there
is one of it.

STATUS, NOT REFUSAL. "The door you came in by", "taken 3x this subgoal",
"failed 3x: blocked at (19,10)", "shut", "dead for this goal" are facts on
the entry, beside what happened the LAST time this run did it. A repeat is
then a deliberate choice made in full view, and repeats.py can count it.

WHAT IT MAY SAY (the claim rules, unchanged): a door's destination only
if this run has walked it (`_walked_dest`), else the frontage words for a
building that looks like what it is; a seam's far side only if walked;
never the warp table, never a Town Map itinerary, never a named lock. The
ranking is arithmetic on walked ground — untried before taken, unopened
before known, fewer visits before more, local before remote — and WHICH
entry matters is the model's.

READ-ONLY. build() touches nothing on the executor: it calls only pure
readers (_taken_here, _spent_exits, _sealed, dead_for, _walked_dest,
_untaken, _worth_another_word(backfill=False), _twin_keys, _route,
_frontier_left) so it can be rendered any number of times per round.

The one thing the executor does not keep yet — what happened the LAST
time this run did each thing, per (target, area, key) — arrives as the
`outcomes` argument: {key: {"n": int, "last": str}} for the area being
stood in. Until _run_traced writes it, pass None and the ledger says
"taken Nx" from the walked graph and nothing about words; that is
strictly what the prompt says today, so wiring in stages is safe.

Standalone on purpose (2026-08-18): a chain is running and executor.py
is not to be edited under it. Wiring is a few lines at the next stop:
    cands = ledger.build(self, obs, target, outcomes)
    memory = ledger.render(cands, self, obs, target)   # replaces the
                                                        # exits/things block
    if ledger.lookup(cands, step) is None: refuse as OFF-LEDGER
"""

from __future__ import annotations

from dataclasses import dataclass, field

# status vocabulary — the order here IS the rank order within a kind
STATUS_RANK = {
    "untried": 0,       # a door / seam never taken from here
    "untouched": 0,     # a thing / person here never pressed
    "unspoken": 0,      # a person here never spoken to (alias of untouched)
    "reopened": 1,      # a shut door, now that the world has moved
    "taken": 2,         # walked before; count and destination known
    "touched": 2,       # pressed before; count and last words known
    "worth_a_word": 3,  # pressed when the world was different (weak lead:
                        # a sign says the same thing for ever)
    "came_in_by": 3,    # the door you arrived through (also "taken")
    "spent": 4,         # reached for 2+ times in this world, never through
    "shut": 4,          # walked into, turned back
    "inert": 4,         # pressed, world unchanged, same world now
    "sealed": 5,        # seam proven uncrossable from this area (as of now)
    "dead": 5,          # this goal has provably failed beyond it
    "unreachable": 6,   # visible, cannot be walked to right now
    "cuttable": 0,      # a bush, and a party Pokemon knows CUT: a way on
    "bush": 3,          # a bush, and nobody knows CUT yet
    "op": -1,           # explore
}


@dataclass
class Candidate:
    key: str                     # "3,7" | "north" | object NAME | "explore"
    kind: str                    # door | seam | item | person | trainer |
                                 # sign | fixture | cut_tree | op
    status: str = "untried"
    n: int = 0                   # times taken / pressed (this subgoal if the
                                 # outcomes ledger says, else lifetime walked)
    dest: str | None = None      # exits: walked destination region, or None
    note: str = ""               # last outcome verbatim / the fact behind
                                 # the status, bounded by render()
    x: int | None = None         # things: where it sits (for a field move)
    y: int | None = None
    reachable: bool = True       # things: can be walked to right now
    beyond: str = ""             # exits: what lies past a walked exit —
                                 # fully worked, or how much is left there
    hops: int | None = None      # exits: legs to the goal over walked ground
    offer: bool = True           # False only for the two hard cases
    rank: tuple = field(default_factory=tuple)

    def label(self) -> str:
        if self.kind == "seam":
            return f"walk {self.key}"
        if self.kind == "door":
            return f"door ({self.key})"
        if self.kind == "op":
            return self.key
        return f"{self.key}"


# ------------------------------------------------------------------ helpers

def _map_of(region: str | None) -> str:
    return str(region or "").split("|")[0]


def _came_in_by(ex, obs, here: str, key: str, dest_map: str | None) -> bool:
    """The reversal test _run_traced makes, read-only, one place.

    Twin tiles of the arrival door count; a same-MAP destination counts
    only when that map is known to have ONE region (Mt Moon's B1F pocket
    is reached by a ladder whose destMap is B1F); the learned graph's
    `to == came_from` counts always."""
    arrived = getattr(ex, "_arrived", None)
    came_from = getattr(ex, "_came_from", None)
    if not arrived or arrived[0] != here:
        return False
    x, y = (key.split(",") + [None])[:2]
    try:
        tile = (int(x), int(y))
    except (TypeError, ValueError):
        return False
    ax, ay = tuple(arrived[1])
    if tile == (ax, ay):
        return True
    # A DOOR YOU STAND BESIDE. Outdoors gen1 puts you one tile in front
    # of the door you came out of, and a doorway can be two tiles wide;
    # a tile next to the arrival point that leads back to the map you
    # came from is the door you came in by. A door ELSEWHERE on this map
    # that also leads there is not — Cerulean's badge house has a front
    # door to the city and a back door to the city's yard, and the old
    # "same map, one known region" rule called the back door the front.
    prev_map = _map_of(came_from)
    if (dest_map and prev_map and dest_map == prev_map
            and abs(tile[0] - ax) + abs(tile[1] - ay) <= 1):
        return True
    known = (ex.explored.get(here, {}) or {}).get(key) or {}
    return bool(known and came_from and known.get("to") == came_from)


def _twins(ex, obs, key: str) -> set:
    x, y = (key.split(",") + [None])[:2]
    try:
        step = {"x": int(x), "y": int(y)}
    except (TypeError, ValueError):
        return set()
    return set(ex._twin_keys(obs, step))


def _join(a: str, b: str) -> str:
    return (a + "; " + b) if (a and b) else (a or b)


def worked_regions(ex, target: str) -> dict:
    """Rooms the searched ledger calls finished for this goal — read-only,
    with the unfinished-floor exclusion _worked_for already applies."""
    try:
        return ex._worked_for(target) if hasattr(ex, "_worked_for") else {}
    except Exception:
        return {}


def untouched_in(ex, region: str) -> list:
    """Things SEEN in a region and never pressed — the sightings ledger
    minus the touched ledger, the same subtraction the prose makes for
    'rooms you have seen things in that you have never touched'."""
    names = (getattr(ex, "sightings", {}) or {}).get(region) or []
    got = (getattr(ex, "_tried_objs", {}) or {}).get(region, set()) or set()
    return sorted(n for n in names if n not in got)


def shelf_of(ex, region_or_map: str) -> list:
    """What a mart was seen to sell, from the counter's own reply."""
    mid = _map_of(region_or_map)
    return list((getattr(ex, "_shelves", {}) or {}).get(mid) or [])


def beyond(ex, dest: str, target: str) -> str:
    """What lies past a walked exit, in one clause: fully worked (nothing
    new that way), or how much is still untried there. THIS is the fact the
    ideal turns on — leave a worked area for ground that still has
    something, and do not go back into ground that has nothing."""
    _shelf = shelf_of(ex, dest)
    if _shelf:
        # a shop's shelf is what lies beyond its door, and it is the fact
        # a re-supposed purchase keeps missing
        return f"{dest} sells: {', '.join(_shelf[:8])}"
    left = ex._frontier_left(dest)
    things = untouched_in(ex, dest)
    if left or things:
        parts = []
        if left:
            parts.append(f"{len(left)} exit(s) never taken")
        if things:
            parts.append(f"{len(things)} thing(s) never pressed "
                         f"({', '.join(things[:3])})")
        return f"{dest} still has " + " and ".join(parts)
    if dest in worked_regions(ex, target):
        return f"{dest} is fully worked — nothing new that way"
    return ""


UNWORKED = ("untried", "untouched", "unspoken", "reopened", "cuttable")


def switches(cands: list) -> list:
    """Reachable fixtures other than a PC: pressable AGAIN by nature. The
    Vermilion gym's cans re-randomise on a miss and pressing again is the
    only way through; a PC is a service with its own ops."""
    return [c for c in cands if c.kind == "fixture" and c.key != "PC"
            and c.status not in ("unreachable",)]


def fully_worked(cands: list) -> bool:
    """Nothing here is untried, untouched, unspoken, reopened or cuttable —
    and nothing here is a switch. (A bush nobody can cut yet is not
    unfinished business here; a room with switches is never finished, it
    is a puzzle about which and when.)"""
    if switches(cands):
        return False
    return not any(c.status in UNWORKED for c in cands if c.kind != "op")


# -------------------------------------------------------------------- build

def build(ex, obs: dict, target: str = "", outcomes: dict | None = None,
          want_explore: bool = True) -> list[Candidate]:
    """Every exit and every thing where the party stands, with a status."""
    obs = obs or {}
    m = obs.get("map") or {}
    mid = m.get("id")
    here = ex._where(obs)
    outcomes = outcomes or {}
    now = getattr(ex, "_mark_now", None)

    taken = ex._taken_here(here)
    spent = ex._spent_exits(here)
    sealed = ex._sealed(here)
    tried = ex._untaken(m, set(ex._tried_objs.get(here, set()) or set()))
    inert = ex._inert_objs.get(here, {}) if hasattr(ex, "_inert_objs") else {}
    again = set(ex._worth_another_word(here, obs, backfill=False)
                if hasattr(ex, "_worth_another_word") else [])
    snap = ex._snapshot(obs) if hasattr(ex, "_snapshot") else None
    seen_maps = {_map_of(a) for a in ex.visits}
    knows_cut = any(
        "CUT" in [str(mv.get("id") if isinstance(mv, dict) else mv)
                  for mv in (mon.get("moves") or [])]
        for mon in (obs.get("party") or []))

    out: list[Candidate] = []

    # ---- exits: doors -------------------------------------------------
    for w in (m.get("warps") or []):
        key = f"{w.get('x')},{w.get('y')}"
        rec = taken.get(key) or {}
        walked = ex._walked_dest(mid, key)
        dest_map = w.get("dest")
        c = Candidate(key=key, kind="door", dest=walked)
        oc = outcomes.get(key) or {}
        c.n = int(oc.get("n") or rec.get("n") or 0)
        if oc.get("last"):
            c.note = str(oc["last"])
        if not w.get("reachable"):
            c.status = "unreachable"
            # the nearest person is context, never the cause
            folk = [(abs((o.get("x") or 0) - (w.get("x") or 0))
                     + abs((o.get("y") or 0) - (w.get("y") or 0)),
                     o.get("name"))
                    for o in (m.get("objects") or [])
                    if o.get("reachable") and o.get("name")
                    and o.get("x") is not None]
            near = min(folk, default=(None, None))
            if near[0] is not None and near[0] <= 8:
                c.note = c.note or f"nearest person {near[1]}"
        elif key in spent:
            c.status = "spent"
            c.n = spent[key]
            c.note = c.note or ("reached for and never once got through — "
                                "something stops you before the doorway")
        elif rec.get("shut"):
            reopened = (now is not None and rec.get("shut_at") != now) or \
                       (w.get("reachable") and not rec.get("shut_reach", True))
            c.status = "reopened" if reopened else "shut"
            c.n = int(rec.get("n") or 0)
            c.note = c.note or ("walked into and turned back; nothing is "
                                "known about what is beyond it")
        elif key in taken:
            bad = ex.dead_for(target, rec.get("to") or "") if target else 0
            if bad:
                c.status = "dead"
                c.note = c.note or (f"this goal has already failed beyond it "
                                    f"{bad}x")
            elif _came_in_by(ex, obs, here, key, dest_map):
                c.status = "came_in_by"
            else:
                c.status = "taken"
                if (c.n or 0) == 0:
                    c.note = c.note or ("you arrived through it; never taken "
                                        "from this side")
            if walked and not bad:
                c.beyond = beyond(ex, walked, target)
        else:
            # NEVER WALKED: no destination — the frontage words at most
            c.status = "untried"
            face = ex._frontage(dest_map)
            if face:
                c.note = face
        # a door's twin tile that is the arrival door is the same door
        if c.status == "untried" and _came_in_by(ex, obs, here, key, dest_map):
            c.status = "came_in_by"
        out.append(c)

    # ---- exits: seams -------------------------------------------------
    for d in (m.get("connections") or {}):
        rec = taken.get(d) or {}
        walked = ex._walked_dest(mid, d)
        c = Candidate(key=d, kind="seam", dest=walked)
        oc = outcomes.get(d) or {}
        c.n = int(oc.get("n") or rec.get("n") or 0)
        if oc.get("last"):
            c.note = str(oc["last"])
        if d in sealed:
            c.status = "sealed"
            c.note = c.note or ("proven uncrossable from THIS part of the "
                                "map as things stand — the connection is on "
                                "the far side of a barrier")
        elif d in spent:
            c.status = "spent"
            c.n = spent[d]
        elif d in taken:
            bad = ex.dead_for(target, rec.get("to") or "") if target else 0
            if bad:
                c.status = "dead"
                c.note = c.note or f"this goal has already failed beyond it {bad}x"
            else:
                c.status = "taken"
                if walked:
                    c.beyond = beyond(ex, walked, target)
        else:
            c.status = "untried"
        out.append(c)

    # ---- things and people --------------------------------------------
    # ONE ENTRY PER NAME. Two bushes are both called CUT_TREE and interact
    # by name reaches the first; listing both is the same choice twice.
    seen_names: dict = {}
    for o in (m.get("objects") or []):
        name = o.get("name")
        if not name:
            continue
        if name in seen_names:
            if "more than one of these here" not in (seen_names[name].note or ""):
                seen_names[name].note = _join(seen_names[name].note,
                                              "more than one of these here")
            continue
        kind = o.get("kind") or "thing"
        c = Candidate(key=name, kind=kind, x=o.get("x"), y=o.get("y"),
                      reachable=bool(o.get("reachable")))
        seen_names[name] = c
        oc = outcomes.get(name) or {}
        c.n = int(oc.get("n") or 0)
        if oc.get("last"):
            c.note = str(oc["last"])
        if kind == "cut_tree":
            # A BUSH IS NOT PRESSED, IT IS CUT. Interact by name never
            # reaches one (they come from the tileset scan), so "never
            # pressed" would be true for ever and explore would reach for
            # it first every round. It is a way on once CUT is known.
            c.status = ("unreachable" if not o.get("reachable")
                        else "cuttable" if knows_cut else "bush")
            # ...and one you cut before has grown back (reload does that
            # in this recomp): say it is the same bush.
            _cut = (getattr(ex, "_cut_bushes", {}) or {}).get(mid) or []
            if f"{o.get('x')},{o.get('y')}" in _cut:
                c.note = _join(c.note, "you CUT this bush before and it has "
                                       "grown back — a bush comes back when "
                                       "the game reloads; it cuts again")
        elif not o.get("reachable") and kind != "item":
            c.status = "unreachable"
        elif name in inert and snap is not None and inert.get(name) == snap:
            c.status = "inert"
            c.note = c.note or "pressed; the world did not change and has not since"
        elif name in tried:
            # the status words already say "when the world was different";
            # the note is kept for what it actually SAID, if that is known
            c.status = "worth_a_word" if name in again else "touched"
        else:
            c.status = "unspoken" if kind in ("npc", "trainer") else "untouched"
            if not o.get("reachable"):
                c.note = "an item you cannot walk to right now"
        out.append(c)

    # ---- rank ---------------------------------------------------------
    for c in out:
        # untried before taken; among untried, an exit into a map never
        # SEEN before one back into a seen map (unopened before known);
        # among taken, fewest takes first; then key for determinism
        into_seen = bool(c.dest) and _map_of(c.dest) in seen_maps
        # what can be acted on NOW first: an item you cannot walk to is
        # still never-pressed (items do not move) but it is not a move
        c.rank = (not c.reachable, STATUS_RANK.get(c.status, 9), into_seen,
                  c.n, c.kind, c.key)
    out.sort(key=lambda c: c.rank)

    # ---- explore ------------------------------------------------------
    if want_explore:
        out.insert(0, Candidate(key="explore", kind="op", status="op",
                                note=plan_explore(ex, obs, out)))
    return out


def plan_explore(ex, obs: dict, cands: list[Candidate] | None = None) -> str:
    """What one `explore` step WOULD do from here, in words. Nothing runs.

    The order is the sweep's, made explicit: press what is untouched here
    (items, then fixtures, then people, then signs), else take the best
    untried exit here, else walk over walked ground to the nearest area that
    still has an exit never taken and take it, else say so."""
    here = ex._where(obs)
    cands = cands if cands is not None else build(ex, obs, want_explore=False)
    order = {"item": 0, "fixture": 1, "cut_tree": 1, "npc": 2, "trainer": 2,
             "sign": 3}
    things = sorted((c for c in cands
                     if c.status in ("untouched", "unspoken", "cuttable")
                     and c.reachable
                     and c.kind not in ("door", "seam", "op")),
                    key=lambda c: (order.get(c.kind, 4), c.key))
    if things:
        if things[0].status == "cuttable":
            return (f"CUT the bush at ({things[0].x},{things[0].y}) — a "
                    f"party Pokemon knows CUT and it is a way on")
        return (f"press {things[0].key} here ({things[0].kind}); "
                f"{len(things)} thing(s) here are untouched")
    exits = [c for c in cands if c.status == "untried"
             and c.kind in ("door", "seam")]
    if exits:
        return f"take {exits[0].label()} — untried from here"
    # nearest area with something never taken OR never pressed, over
    # walked ground — leaving worked ground for ground that still has
    # something is the whole idea, so both kinds of "something" count
    best = None
    regions = set(list(getattr(ex, "frontier", {}) or {})
                  + list(getattr(ex, "sightings", {}) or {}))
    for region in regions:
        if region == here:
            continue
        left = ex._frontier_left(region)
        things = untouched_in(ex, region)
        if not (left or things):
            continue
        path = ex._route(here, region)
        if not path:
            continue
        r = (len(path), -(len(left) + len(things)), region)
        if best is None or r < best[0]:
            best = (r, region, left, things, path)
    if best:
        _, region, left, things, path = best
        fk, fd = path[0]
        first = f"walk {fk}" if not fk[0].isdigit() else f"door ({fk})"
        what = []
        if left:
            what.append(f"take one of {', '.join(sorted(left)[:3])}")
        if things:
            what.append(f"press {', '.join(things[:3])}")
        return (f"THIS AREA IS FULLY WORKED — every exit taken, everything "
                f"pressed; nothing new can be found by staying. The nearest "
                f"ground with something never tried is {region} "
                f"({len(path)} leg(s), first {first} to {fd}); explore "
                f"walks there to " + " and ".join(what))
    return ("THIS AREA IS FULLY WORKED and so is everywhere you can walk to "
            "— something you have done must be undone or something you "
            "carry must be used to open new ground")


# ------------------------------------------------------------------- lookup

def lookup(cands: list[Candidate], step: dict) -> Candidate | None:
    """The ledger entry an op addresses, or None = OFF-LEDGER.

    use_warp x,y -> door key; cross dir -> seam key; interact name -> the
    thing (an interact by x,y is a tile press and is always on-ledger: the
    scenery is not listed and the rule says a coordinate is the only way to
    reach it). Ops that address nothing spatial (buy, heal, use_item, menu,
    wait, grind, ...) return a permissive dummy so the guard never refuses
    them on this ground."""
    op = (step or {}).get("op")
    by_key = {c.key: c for c in cands}
    if op == "use_warp":
        return by_key.get(f"{step.get('x')},{step.get('y')}")
    if op == "cross":
        return by_key.get(str(step.get("dir")))
    if op == "interact":
        if step.get("name"):
            return by_key.get(step["name"])
        return Candidate(key=f"{step.get('x')},{step.get('y')}", kind="tile",
                         status="untouched")
    if op == "explore":
        return by_key.get("explore")
    return Candidate(key=str(op), kind="op", status="op")


def untried_keys(cands: list[Candidate]) -> set:
    """The set _untried_exits must agree with (tests/untried.py's law:
    when a concept has two implementations, one of them is wrong)."""
    return {c.key for c in cands
            if c.kind in ("door", "seam") and c.status in ("untried", "reopened")}


# ------------------------------------------------------------------- render

_STATUS_WORDS = {
    "untried": "never taken from here",
    "reopened": "turned you back once, but the world has moved since",
    "taken": "taken {n}x",
    "came_in_by": "the door you came in by; taken {n}x",
    "spent": "reached for {n}x and never once got through",
    "shut": "SHUT — walked into {n}x and turned back every time",
    "sealed": "proven uncrossable from this area",
    "dead": "KNOWN DEAD END for this goal",
    "unreachable": "you cannot walk to it from where you stand",
    "untouched": "never pressed",
    "unspoken": "never spoken to",
    "touched": "pressed {n}x",
    "worth_a_word": "pressed {n}x, when you were carrying different things "
                    "— people here say different things once the world moves",
    "inert": "pressed {n}x; nothing changed",
    "cuttable": "a bush — CUT clears it, and a party Pokemon knows CUT",
    "bush": "a bush — CUT clears it; nobody in the party knows CUT yet",
}

NOTE_CHARS = 140


def render(cands: list[Candidate], ex, obs: dict, target: str = "",
           limit: int = 24) -> str:
    """The ledger as the model reads it: numbered, local, ranked, bounded.

    Position is the budget (the model takes the first-listed 54% of the
    time), so the order is the rank and the list is cut, saying how much
    went. Everything an entry knows is on its own line: status, count,
    destination if walked, the last outcome verbatim."""
    obs = obs or {}
    m = obs.get("map") or {}
    here = ex._where(obs)
    sides = sorted((m.get("connections") or {}).keys())
    been = (getattr(ex, "visits", {}) or {}).get(here, 0)
    head = f"WHERE YOU STAND: {here}"
    head += (" — indoors, no edges; the doors are the only ways out"
             if not sides else
             f" — this map has an edge on its {', '.join(sides)} side(s) "
             f"and nowhere else")
    if been:
        head += f"; you have been in this exact area {been}x"
    _sh = shelf_of(ex, here)
    if _sh:
        head += f". This mart sells: {', '.join(_sh[:10])}"
    if fully_worked(cands):
        head += (". FULLY WORKED: nothing here is untried or unpressed — "
                 "staying finds nothing new; leaving for ground that still "
                 "has something is how the search goes on")
    elif switches(cands) and not any(c.status in UNWORKED for c in cands
                                     if c.kind != "op"):
        head += (". Everything here has been pressed at least once, but "
                 f"the fixtures ({', '.join(c.key for c in switches(cands)[:6])}) "
                 "can be pressed AGAIN — a room like this can be a puzzle "
                 "about which, rather than about finding one more thing")
    lines = [head + "."]
    # EXITS ARE NEVER CUT. The cap is for the long tail of things and
    # people; a door or a seam is a way out and every one is shown.
    exits = [c for c in cands if c.kind in ("door", "seam", "op")]
    rest = [c for c in cands if c.kind not in ("door", "seam", "op")]
    keep = rest[:max(0, limit - len(exits))]
    shown = [c for c in cands if c in exits or c in keep]
    # ONE LINE FOR THE WEAK LEADS. Things pressed before the world moved
    # are the same fact eleven times over in a town square; they keep
    # their entries (lookup still finds each) but read as one line at the
    # rank of the first, names listed, so they cannot bury the doors.
    weak = [c for c in shown if c.status == "worth_a_word"]
    weak_done = False
    i = 0
    for c in shown:
        if c in weak and len(weak) > 2:
            if not weak_done:
                weak_done = True
                i += 1
                lines.append(
                    f" {i}. also pressed here before, when you were carrying "
                    f"different things — people say different things once "
                    f"the world moves: "
                    + ", ".join(w.key + (" (more than one)" if "more than one"
                                         in (w.note or "") else "")
                                for w in weak))
            continue
        i += 1
        if c.kind == "op":
            lines.append(f" {i}. explore — {c.note}")
            continue
        words = _STATUS_WORDS.get(c.status, c.status).format(n=c.n)
        if c.kind == "fixture" and c.key != "PC" and c.status in (
                "touched", "inert", "worth_a_word"):
            words += " — a fixture; it can be pressed again"
        # AN ITEM IS FREE STUFF. Renamed to ITEM_x_y (its contents are not
        # on the screen), "never pressed" undersells it: it is a thing lying
        # on the ground that pressing A picks up, at no cost. Say that.
        if c.kind == "item" and c.status == "untouched":
            words = ("lying on the ground, never picked up — pressing A "
                     "takes it and it costs nothing"
                     + ("" if c.reachable else "; not walkable-to right now"))
        # NO COUNT IS NOT ZERO. Until _run_traced writes the outcomes
        # ledger, a pressed thing has no per-subgoal count; "pressed 0x"
        # would be a lie in the other direction.
        if c.n == 0 and c.status in ("touched", "worth_a_word", "inert",
                                     "taken", "came_in_by"):
            words = words.replace(" {0}x".format(0), "").replace(
                "pressed 0x", "pressed").replace("taken 0x", "taken before")
        arrow = f" -> {c.dest}" if c.dest else ""
        if c.kind in ("door", "seam") and not c.dest and c.status in (
                "untried", "reopened", "spent", "shut", "unreachable"):
            arrow = " -> UNKNOWN"
        kind = ("" if c.kind in ("door", "seam") else
                f" ({c.kind}" + (f" at {c.x},{c.y}" if c.x is not None
                                 else "") + ")")
        note = ""
        if c.note:
            n = c.note.strip()
            if len(n) > NOTE_CHARS:
                n = n[:NOTE_CHARS - 1] + "…"
            note = f" — {n}"
        # what lies beyond is never cut: it is the fact the ideal turns on
        if c.beyond:
            note += f" — {c.beyond}"
        lines.append(f" {i}. {c.label()}{kind}{arrow} — {words}{note}")
    cut = [c for c in rest if c not in keep]
    if cut:
        by = {}
        for c in cut:
            by[c.status] = by.get(c.status, 0) + 1
        lines.append(f" … and {len(cut)} more thing(s) not shown: "
                     + ", ".join(f"{n} {s}" for s, n in sorted(by.items())))
    lines.append("Every entry above may be taken; the ones marked never "
                 "taken / never pressed are the only ones that can find "
                 "anything new here. Which matters is your call.")
    return "\n".join(lines)
