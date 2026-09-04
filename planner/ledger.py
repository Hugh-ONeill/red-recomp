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

import re as _re
from dataclasses import dataclass, field

# status vocabulary — the order here IS the rank order within a kind
STATUS_RANK = {
    "untried": 0,       # a door / seam never taken from here
    "unlooked": 0,      # a spot where the seen ground ends (frontier)
    "untouched": 0,     # a thing / person here never pressed
    "unspoken": 0,      # a person here never spoken to (alias of untouched)
    "reopened": 1,      # a shut door, now that the world has moved
    "taken": 2,         # walked before; count and destination known
    "lift_door": 2,     # a car's doorway: never fresh, never a discovery
    "touched": 2,       # pressed before; count and last words known
    "worth_a_word": 3,  # pressed when the world was different (weak lead:
                        # a sign says the same thing for ever)
    "came_in_by": 3,    # the door you arrived through (also "taken")
    "back": 3,          # a seam's reverse: you came onto this map across it
    "spent": 4,         # reached for 2+ times in this world, never through
    "shut": 4,          # walked into, turned back
    "inert": 4,         # pressed, world unchanged, same world now
    "sealed": 5,        # seam proven uncrossable from this area (as of now)
    "dead": 5,          # this goal has provably failed beyond it
    "unreachable": 6,   # visible, cannot be walked to right now
    "cuttable": 0,      # a bush, and a party Pokemon knows CUT: a way on
    "recut": 2,         # a bush cut before, regrown: reopens WALKED ground
    "bush": 3,          # a bush, and nobody knows CUT yet
    "pushable": 0,      # a boulder, and STRENGTH is known: a way on
    "boulder": 3,       # a boulder, and nobody knows STRENGTH yet
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
    look: str = "door"           # door | stairs | pad | hole
    by_water: bool = False       # doors/things the swum reach touches and
                                 # the walk does not — water is not a wall
                                 # while the party carries SURF
    spoke: str = ""              # what the game said when this exit was
                                 # last tried — a locked door answers in
                                 # words, and that answer is evidence
    twins: list = field(default_factory=list)
                                 # doors: the other tiles of this doorway —
                                 # a doorway spans up to four warp tiles
                                 # and is ONE door (_door_groups)

    def label(self) -> str:
        if self.kind == "seam":
            return f"walk {self.key}"
        if self.kind == "door":
            _l = getattr(self, "look", "door") or "door"
            # "(4,7)+(5,7)" read to the model as two doors, and it took the
            # twin as "the other door in this room" (2026-08-25): say it is one
            # "(4,7)+(5,7) — ONE doorway, two tiles wide" still read as two
            # doors: in the forest gate the run said "I see two doors; one
            # leads back to Route 2, the other is untried", took the other
            # tile of the door it came in by, and walked back out
            # (2026-08-29, user watching). Say it as one door with a width,
            # and name the other tiles as the SAME door.
            _tws = [t for t in (getattr(self, "twins", None) or []) if t]
            _tw = ""
            if _tws:
                _tw = (f" [ONE door, {len(_tws) + 1} tiles wide: "
                       + " and ".join(f"({t})" for t in _tws)
                       + (" is" if len(_tws) == 1 else " are")
                       + " the SAME door, not another]")
            if _l == "pad":
                return f"warp pad ({self.key}){_tw}"
            if _l == "hole":
                return f"hole ({self.key}){_tw}"
            if _l == "lift":
                return f"lift door ({self.key}){_tw}"
            if _l == "stairs":
                return f"stairs/ladder ({self.key}){_tw}"
            if _l == "threshold":        # an older shim's word for a door
                return f"door ({self.key}){_tw}"
            return f"door ({self.key}){_tw}"
        if self.kind == "frontier":
            if getattr(self, "look", "") == "arrow":
                return f"arrow tile ({self.key}) slides onto unseen ground"
            return f"seen ground ends at ({self.key})"
        if self.kind == "op":
            return self.key
        return f"{self.key}"


# ------------------------------------------------------------------ helpers

def _map_of(region: str | None) -> str:
    return str(region or "").split("|")[0]


def _stem(key: str | None) -> str:
    """A name with its trailing number taken off: SLOT_MACHINE_18 and
    SLOT_MACHINE_19 are two of the same thing, and the game names them
    that way itself."""
    return _re.sub(r"\d+$", "", str(key or ""))


def _goal_kinds_of(target: str | None) -> set:
    """The kind of thing that answers this goal. An item goal is answered
    by items; an event by the fixtures that fire them (a switch, a machine,
    a lever) — not by whoever is standing near."""
    t = str(target or "")
    return ({"item"} if t.startswith("item:")
            # A MAP IS ANSWERED BY A WAY OUT. With no kind preferred, a
            # walked door tied on status with pressed people and then LOST
            # the tiebreak to `into_seen`, which exists to rank exits among
            # themselves — so Route 20 listed a sign and two trainers it
            # had already pressed above the Seafoam door, the only entry on
            # the page that can change which map you are on (user,
            # 2026-08-23: "the seafoam door is rated 5th"). plan_explore
            # already reads the way out first for a map goal; the list it
            # sits above did not.
            else {"door", "seam"} if t.startswith("map:")
            else {"fixture"} if t.startswith("flag:")
            else set())


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


def _left_parts(ex, region: str) -> list:
    # A LIFT CAR IS NEVER "STILL HAS EXITS NEVER TAKEN". Its one doorway is
    # re-pointed by the panel, so it counts as unwalked from every angle —
    # and this is the line that hangs off a door as "SILPH_CO_ELEVATOR|0,1
    # still has 1 exit(s) never taken", which is what the run kept crossing
    # floors to act on after the other two sites were fixed. Third and last
    # place that arithmetic is done.
    if str(region).split("|")[0].endswith("_ELEVATOR"):
        return []
    left = ex._frontier_left(region)
    things = untouched_in(ex, region)
    # ...AND GROUND IN THERE NOBODY HAS LOOKED AT. This counted exits and
    # things only, so the row for a door already taken read "still has 1
    # thing(s) never pressed" about CERULEAN_TRASHED_HOUSE — a room the
    # run had stepped into twice and left, with EIGHT spots of unseen
    # ground inside it and the city's only way south behind them (user,
    # 2026-08-29: "so the trashed house was simply entered for a second
    # and then not looked at further since it couldnt see the exit from
    # the start"; "search the whole room youre in because its cheap when
    # youre there already"). A room half unlooked-at is unfinished, and
    # the door into it is where that is worth saying.
    unseen = int((getattr(ex, "region_seen", None) or {}).get(region, 0) or 0)
    _unr = [k for k in ((getattr(ex, "unreached_at", None) or {}).get(region)
                        or [])
            if k not in set(ex._taken_here(region) or {})]
    parts = []
    if left:
        parts.append(f"{len(left)} exit(s) never taken")
    if things:
        parts.append(f"{len(things)} thing(s) never pressed "
                     f"({', '.join(things[:3])})")
    if unseen:
        parts.append(f"{unseen} spot(s) of ground in there never on screen")
    if _unr:
        parts.append(f"{len(_unr)} way(s) out of it never taken that no "
                     f"walk reached")
    return parts


def something_beyond(ex, dest: str, here: str | None = None):
    """The nearest region reachable THROUGH `dest` over walked edges that
    still has an untried exit or an unpressed thing — (region, legs, parts)
    or None. One walk, used by the beyond clause and by the dead-end brand,
    because both were asking a one-hop question of a multi-hop world (the
    department store: every floor spent, the roof two legs on holding the
    only thing that mattered)."""
    from collections import deque
    parts0 = _left_parts(ex, dest)
    if parts0:
        return (dest, 0, parts0)
    seen = {dest} | ({here} if here else set())
    q = deque([(dest, 0)])
    while q:
        cur, n = q.popleft()
        for _k, e in (ex.explored.get(cur) or {}).items():
            nxt = (e or {}).get("to")
            if not nxt or nxt in seen or (e or {}).get("shut"):
                continue
            seen.add(nxt)
            p2 = _left_parts(ex, nxt)
            if p2:
                return (nxt, n + 1, p2)
            q.append((nxt, n + 1))
    return None


def beyond(ex, dest: str, target: str, here: str | None = None) -> str:
    """What lies past a walked exit, in one clause: how much is still
    untried there, or — when the area itself is worked — the nearest ground
    THROUGH it that still has something, over walked edges, not doubling
    back through here. THIS is the fact the ideal turns on — leave a worked
    area for ground that still has something, and do not go back into
    ground that has nothing.

    One hop was a lie by overreach: the Route 8 stairs down read "the
    Underground Path is fully worked — nothing new that way" while Route 7's
    west edge, three walked legs on through that very door, had never been
    taken; the run sat in Lavender for a leg on the strength of it."""
    _shelf = shelf_of(ex, dest)
    if _shelf:
        # a shop's shelf is what lies beyond its door, and it is the fact
        # a re-supposed purchase keeps missing
        # ...AND A VENDING MACHINE IS NOT A COUNTER. Same store, same
        # sentence shape, but "buy" does not read a machine: it is pressed
        # and its rows are picked. Saying "sells" without saying which
        # would send a buy at a wall.
        if _map_of(dest) in (getattr(ex, "_shelf_machine", None) or set()):
            return (f"{dest} has a VENDING MACHINE selling: "
                    f"{', '.join(_shelf[:8])}")
        return f"{dest} sells: {', '.join(_shelf[:8])}"
    parts = _left_parts(ex, dest)
    # ground never on screen counts as something left, for the region
    # itself and for the regions walked on through it: a dark tunnel lists
    # no things and its exits have never been on screen, so eleven entries
    # read "taken 11x" with nothing beyond (2026-08-25)
    _rs = getattr(ex, "region_seen", None) or {}
    if not parts and int(_rs.get(dest, 0) or 0) > 0:
        parts = [f"{int(_rs[dest])} spot(s) where its seen ground ends"]
    if parts:
        return f"{dest} still has " + " and ".join(parts)
    # transitive, over walked ground, never back through here
    from collections import deque
    seen = {dest} | ({here} if here else set())
    q = deque([(dest, 0)])
    found = None
    while q and found is None:
        cur, n = q.popleft()
        for _k, e in (ex.explored.get(cur) or {}).items():
            nxt = (e or {}).get("to")
            if not nxt or nxt in seen or (e or {}).get("shut"):
                continue
            seen.add(nxt)
            p2 = _left_parts(ex, nxt)
            if not p2 and int(_rs.get(nxt, 0) or 0) > 0:
                p2 = [f"{int(_rs[nxt])} spot(s) where its seen ground ends"]
            if p2:
                found = (nxt, n + 1, p2)
                break
            q.append((nxt, n + 1))
    worked = dest in worked_regions(ex, target)
    _other = other_part_note(ex, dest, here or "")
    if found:
        nxt, n, p2 = found
        return ((f"{dest} is fully worked itself" if worked
                 else f"{dest} has nothing untried itself")
                + f", but {n} more leg(s) on through it {nxt} still has "
                + " and ".join(p2) + _other)
    if worked:
        return (f"{dest} is fully worked and so is everything you have "
                f"walked beyond it — nothing new that way as far as you "
                f"have walked" + _other)
    return _other.lstrip("; ").capitalize() if _other else ""


def other_part_note(ex, dest: str, here: str) -> str:
    """Another walked part of the SAME map that still has untried ways.

    beyond()'s search deliberately refuses to double back through `here`,
    which is right for "what is new that way" and leaves it blind to the
    rest of the map. Crossing west from Saffron lands in ROUTE_7|18,12, a
    pocket whose ONE recorded exit is back east, so the row read
    "ROUTE_7|18,12 is fully worked and so is everything you have walked
    beyond it — nothing new that way". Every word true, and it reads as
    "Route 7 is done" — while ROUTE_7|0,2, the half holding the Underground
    Path and the Route 7 gate, still had untried ways. The run crossed west
    three times in a row, landing in the same nine cells each time, before
    it reached for go (user, 2026-08-26: "it kept trying to cross west
    again and landing itself in the same area").

    Recall of ground already walked, and the one fact that decides it: the
    two parts are joined only by LEAVING the map. Which to do stays the
    model's."""
    mid = _map_of(dest)
    if not mid:
        return ""
    rows = []
    for reg in (getattr(ex, "explored", {}) or {}):
        if reg in (dest, here) or _map_of(reg) != mid:
            continue
        parts = _left_parts(ex, reg)
        if not parts:
            continue
        try:
            path = ex._route(dest, reg)
        except Exception:
            path = None
        rows.append((len(path) if path is not None else 99, reg, parts))
    if not rows:
        return ""
    rows.sort()
    n, reg, parts = rows[0]

    def _joined_on_map(a: str, b: str) -> bool:
        """Is there a walked route from a to b that never leaves this map?"""
        from collections import deque
        seen, q = {a}, deque([a])
        while q:
            cur = q.popleft()
            for _k, e in ((getattr(ex, "explored", {}) or {}).get(cur)
                          or {}).items():
                t = (e or {}).get("to")
                if not t or t in seen or _map_of(t) != mid:
                    continue
                if t == b:
                    return True
                seen.add(t)
                q.append(t)
        return False

    if _joined_on_map(dest, reg):
        return ""            # one map, one walk — nothing to warn about
    return (f"; {reg} is ANOTHER PART of {mid} you have walked and it still "
            f"has " + " and ".join(parts)
            + f", and no walk on {mid} joins the two"
            + (f" — the route you have walked between them is {n} leg(s) "
               f"and leaves this map" if n < 99
               else ", and no walked route between them is recorded"))


UNWORKED = ("untried", "untouched", "unspoken", "reopened", "cuttable",
            "pushable", "unlooked")


def switches(cands: list) -> list:
    """Reachable things pressable AGAIN by nature: fixtures other than a
    PC, and closed doors. The Vermilion gym's cans re-randomise on a miss
    and pressing again is the only way through; a PC is a service with its
    own ops.

    A CARD-KEY SHUTTER IS THE SAME KIND OF THING, and was not in this list.
    Pressing one without the key says "Darn! It needs a CARD KEY!", which
    is a real reply, so it banked a touch — and the floor then read FULLY
    WORKED with the door still drawn shut across the way. The same tile,
    the same press, answers "Bingo! The CARD KEY opened the door!" once the
    key is in the bag; both replies are in this run's own journal for
    DOOR_SILPH_CO_8F_7_8 (user, 2026-08-26: "are the shutters counting as
    'touched' because we might want to make them fixtures so they dont
    count like that"). And the shim only MINTS a shut door while its tile
    is still a door tile, so a shut_door in the observation is proof the
    thing is still closed, whatever was pressed at it. A floor holding one
    is not finished; whether it is worth going back for is the model's."""
    return [c for c in cands
            if (c.kind == "fixture" and c.key != "PC"
                or c.kind == "shut_door")
            and c.status not in ("unreachable",)]


def unreached_ways(cands: list) -> list:
    """Ways out NEVER TAKEN that no walk from here reaches right now.

    They are filed `unreachable`, not `untried`, so every "is this area
    finished" test looked straight past them: Seafoam B2F announced
    "THIS AREA IS FULLY WORKED — every exit taken" with two exits on the
    floor that had never once been taken, listed four lines below it
    (user, 2026-08-23: "it sees the current area as fully worked despite
    the untaken hole"). An exit you cannot reach is not an exit you have
    used; the ground is unfinished, and how to get to it stays the
    model's."""
    return [c for c in cands
            if c.kind in ("door", "seam") and c.status == "unreachable"
            and not c.dest]


def fully_worked(cands: list) -> bool:
    """Nothing here is untried, untouched, unspoken, reopened or cuttable —
    and nothing here is a switch. (A bush nobody can cut yet is not
    unfinished business here; a room with switches is never finished, it
    is a puzzle about which and when.)"""
    if switches(cands) or unreached_ways(cands):
        return False
    # ...and a WATER frontier row does not block the claim: "done on foot"
    # is exactly what the header's water branch needs to be allowed to say
    # ("Everything you can reach ON FOOT here is done, but the WATER you
    # can ride has N spot(s)...") — counting it here silenced that very
    # sentence. An ON-FOOT unlooked spot still blocks: ground you can walk
    # to has not been looked at, so nothing here is finished.
    return not any(c.status in UNWORKED for c in cands
                   if c.kind != "op"
                   and not (c.kind == "frontier"
                            and getattr(c, "by_water", False)))


# -------------------------------------------------------------------- build

LAST_PASS_NOTE = ""      # geometry note from the last build(), for render()


def build(ex, obs: dict, target: str = "", outcomes: dict | None = None,
          want_explore: bool = True) -> list[Candidate]:
    """Every exit and every thing where the party stands, with a status."""
    obs = obs or {}
    m = obs.get("map") or {}
    mid = m.get("id")
    here = ex._where(obs)
    outcomes = outcomes or {}
    now = getattr(ex, "_mark_now", None)
    in_car = (str(mid).endswith("_ELEVATOR")
              or bool((obs.get("map") or {}).get("lift_floors")))

    taken = ex._taken_here(here)
    spent = ex._spent_exits(here)
    sealed = ex._sealed(here)
    # A PERSON YOU HAVE SPOKEN TO ON THIS FLOOR IS SPOKEN TO, WHEREVER YOU
    # STAND ON IT. Touch records are keyed per REGION, and a floor split
    # into components by its own walls has several: Silph 2F's worker was
    # pressed from |1,1 (that is where TM_SELFDESTRUCT came from) and read
    # "never spoken to" from |20,0 on the other side of the card-key glass,
    # so explore went on offering someone the run had already emptied and
    # interact failed five times over. Names are unique per map, so the
    # union across this map's regions is the honest set — it says the
    # person was pressed, never that you can reach them from here (the
    # unreachable branch above still decides that).
    _same_map = set()
    for _r, _names in (getattr(ex, "_tried_objs", {}) or {}).items():
        if str(_r).split("|")[0] == str(mid):
            _same_map |= set(_names or ())
    tried = ex._untaken(m, _same_map)
    inert = ex._inert_objs.get(here, {}) if hasattr(ex, "_inert_objs") else {}
    again = set(ex._worth_another_word(here, obs, backfill=False)
                if hasattr(ex, "_worth_another_word") else [])
    # A NAMED THING IS INERT WHEREVER YOU PRESSED IT FROM. See
    # Executor._snapshot_anywhere: keying this on the player's tile kept
    # ROUTE12_SNORLAX "worth another word" through nineteen presses of the
    # same sentence, because each was made from a slightly different cell.
    snap = (ex._snapshot_anywhere(obs)
            if hasattr(ex, "_snapshot_anywhere")
            else (ex._snapshot(obs) if hasattr(ex, "_snapshot") else None))
    seen_maps = {_map_of(a) for a in ex.visits}
    def _party_knows(move: str) -> bool:
        return any(move in [str(mv.get("id") if isinstance(mv, dict) else mv)
                            for mv in (mon.get("moves") or [])]
                   for mon in (obs.get("party") or []))

    knows_cut = _party_knows("CUT")
    knows_strength = _party_knows("STRENGTH")

    out: list[Candidate] = []
    # A ROOM WITH DOORS ON OPPOSITE WALLS IS A CORRIDOR. What a player sees
    # of a route gate is one small room with a door on each side — it is a
    # way THROUGH, not a dead room — and the ledger only ever listed the
    # doors one by one, so a building whose whole purpose is to join two
    # halves of a route read as four unrelated exits. Geometry of the room
    # you are standing in: on screen, claimed from nothing else.
    global LAST_PASS_NOTE
    LAST_PASS_NOTE = ""
    _pass = ""
    try:
        _w = int((m.get("width") or 0))
        _xs = [int(w0.get("x") or 0) for w0 in (m.get("warps") or [])]
        if _w and len(_xs) >= 2:
            _left = sorted({x for x in _xs if x <= 1})
            _right = sorted({x for x in _xs if x >= _w - 2})
            if _left and _right:
                _pass = ("\nTHIS ROOM HAS DOORS ON BOTH SIDES (x="
                         + ",".join(str(x) for x in _left) + " and x="
                         + ",".join(str(x) for x in _right)
                         + "): a room like this is a way THROUGH — going in "
                           "one side and out the other puts you somewhere "
                           "the outside of it could not reach.")
            # ...AND ONE BUILDING CAN HOLD SEVERAL SEPARATE ROOMS. The
            # Route 16 gate is two corridors on one map with no way between
            # them: doors listed here as unreachable are not "blocked", they
            # are in the OTHER room, entered by its own door from outside
            # (user, 2026-08-19: "specify that they're two separate rooms").
            _unreach = [w0 for w0 in (m.get("warps") or [])
                        if not w0.get("reachable")]
            if _unreach and (m.get("warps") or []):
                _others = ", ".join(f"({w0.get('x')},{w0.get('y')})"
                                    for w0 in _unreach[:6])
                # ...BUT HOW THE OTHER ROOM IS ENTERED IS NOT RECORDED.
                # This said "is entered by its OWN door from outside" — one
                # true observation about Route 16's gate, promoted into a
                # rule about every building in the game. In the Pokemon
                # Mansion it is false: 1F's sealed room, the one holding the
                # stairs down to B1F, has no outside door and is entered by
                # FALLING INTO IT from 3F. The run read that sentence at 1F,
                # walked out to Cinnabar to look for the door it promised,
                # found none, came back, and did it again (2026-08-23).
                # Say the shape of the fact and stop at the edge of it.
                _pass += ("\nTHIS MAP HOLDS MORE THAN ONE ROOM: the door(s) "
                          + _others + " are on it but not reachable from "
                          "where you stand — walls, not obstacles. HOW that "
                          "other room is entered is NOT RECORDED. Some are "
                          "entered by their own door from OUTSIDE the "
                          "building; some are only entered from ANOTHER "
                          "FLOOR, by stairs that land inside them, by a "
                          "hole that drops you in, or by a WARP PAD whose "
                          "twin stands inside them — a pad is one of the "
                          "things this page names when it is on screen. "
                          "Which of those this is, this ledger does not "
                          "know.")
    except (TypeError, ValueError):
        _pass = ""
    LAST_PASS_NOTE = _pass

    # ---- exits: doors -------------------------------------------------
    for w in (m.get("warps") or []):
        key = f"{w.get('x')},{w.get('y')}"
        rec = taken.get(key) or {}
        walked = ex._walked_dest(mid, key)
        dest_map = w.get("dest")
        c = Candidate(key=key, kind="door", dest=walked)
        # what it is DRAWN as, straight from the tile under it (shim
        # warp_look): a door, a stairway, a teleport pad, a hole. A player
        # tells these apart at a glance and the ledger called them all
        # "door", so eleven floors of Silph pads read like eleven doors.
        c.look = str(w.get("look") or "door")
        c.by_water = bool(w.get("by_water"))
        oc = outcomes.get(key) or {}
        c.n = int(oc.get("n") or rec.get("n") or 0)
        if oc.get("last"):
            c.note = str(oc["last"])
        # A DOOR THE GAME HAS ANSWERED IN WORDS IS NOT AN UNTRIED DOOR.
        # The sentence was already kept — against the region, under the
        # bare op name — so the page could quote "The door is locked..."
        # in one paragraph and call the door that said it "never taken
        # from here — untried" three lines above, which is where explore
        # kept walking back to (2026-08-23).
        _said_here = ""
        for _h in (getattr(ex, "hints", None) or {}).get(here, ()):
            _pre = f"use_warp ({key}): "
            if str(_h).startswith(_pre):
                _said_here = str(_h)[len(_pre):]
        if _said_here:
            # ...AND A REFUSAL OUTLIVES THE THING THAT LIFTED IT. The
            # people-said block dates every line ("said before N event(s)
            # that have fired since"); a DOOR's quoted refusal carried no
            # stamp at all. Inside ROUTE_5_GATE the row for the south door
            # read: trying it said: "I'm on guard duty. Gee, I'm thirsty,
            # though! Oh wait there, the road's closed." — with the drink
            # long since handed over and the guard, one row below, saying
            # "Hi, thanks for the cool drinks!". Two sentences from the
            # same gate, one stale, and the stale one sat on the row where
            # the door is chosen (user, 2026-08-26). Same stamp, same
            # source (hints_at), same rule: say when it was said; whether
            # it still holds is the model's.
            c.spoke = _said_here
            try:
                _line = f"use_warp ({key}): {_said_here}"
                _then = ((getattr(ex, "hints_at", {}) or {})
                         .get(here) or {}).get(_line)
                _now = len((obs.get("flags") or []))
                if _then is not None and _now > _then:
                    c.spoke = (f"{_said_here}  (said before {_now - _then} "
                               f"event(s) that have fired since)")
            except Exception:
                pass
        # A DOOR INTO A LIFT IS A LIFT. The op rides door to door from
        # where you stand — walks in, presses the floor, walks out — but
        # nothing outside the car ever said so, so the run kept working
        # the lift by hand: warp into the car, then try to warp out again
        # (user: "it didnt use the elevator op, its using it manually").
        # The destination is already walked knowledge; this only names the
        # op that uses it.
        if str(walked or "").split("|")[0].endswith("_ELEVATOR"):
            c.note = _join(c.note,
                           "this door is a LIFT CAR — you do not have to "
                           "walk in and out of it: {\"op\":\"elevator\","
                           "\"floor\":\"5F\"} from where you stand rides "
                           "it door to door and leaves you on that floor")
        if in_car:
            # INSIDE A CAR EVERY DOOR IS THE SAME DOOR: the exit warps are
            # rewritten by the panel, so a destination learned last ride is
            # a lie this ride, and picking a different door changes nothing.
            # ...AND IT IS NEVER "UNTRIED". A car's doorway is not a way
            # you have failed to explore, it is the only way out, and the
            # panel decides where it lands. Read as untried it drew the run
            # in every round: warp into the car, warp out onto 10F, back
            # in, out again — with the ledger calling (2,3) an untried exit
            # "leading to the 1st floor" while it opened onto the tenth.
            c.status = "lift_door"
            c.dest = None
            c.note = _join(c.note,
                           "a door of this CAR — it opens onto whichever "
                           "floor the panel was last set to; where you come "
                           "out is chosen with {\"op\":\"elevator\","
                           "\"floor\":\"F\"}, never by picking another door")
        elif not w.get("reachable"):
            c.status = "unreachable"
            # the nearest person is context, never the cause
            # WHAT STANDS NEAREST IT ON YOUR SIDE, and whether it has been
            # pressed. This said "nearest person MTMOONB2F_DOME_FOSSIL"
            # about the fossil standing in the corridor to Mt Moon's exit
            # ladder — not a person, and the one thing on the floor that
            # had never been pressed (2026-08-29, user: "it didnt try to
            # pick up the fossil"). Say the kind, the distance and the
            # press count; what is beside the way is not claimed to be the
            # cause, the same rule as the walk refusal's fence line.
            folk = [(abs((o.get("x") or 0) - (w.get("x") or 0))
                     + abs((o.get("y") or 0) - (w.get("y") or 0)),
                     o.get("name"), str(o.get("kind") or "thing"),
                     o.get("name") in tried)
                    for o in (m.get("objects") or [])
                    if o.get("reachable") and o.get("name")
                    and o.get("x") is not None]
            # an unpressed thing outranks a pressed one at the same distance
            near = min(folk, key=lambda f: (f[0], f[3]), default=None)
            if near and near[0] <= 8:
                _kind = ("a fossil" if "FOSSIL" in str(near[1]).upper()
                         else "a person" if near[2] in ("npc", "trainer")
                         else "an item" if near[2] == "item"
                         else f"a {near[2]}")
                c.note = _join(c.note,
                               f"{near[1]} ({_kind}, "
                               f"{'pressed before' if near[3] else 'NEVER pressed'}) "
                               f"stands {near[0]} cell(s) from it on your side — "
                               f"what is beside the way, not a claim it is what "
                               f"stops you; a thing standing in a corridor "
                               f"sometimes is, and pressing it is how you find out")
            # WHICH PART OF THIS FLOOR REACHES IT, IF ANY. The shim floods
            # the seen ground from every other part the run has stood in
            # (the head's seen_unreached rule, applied to this door). Bare
            # "you cannot walk to it from where you stand" left the run
            # climbing back up the ladder it came down, five times, to find
            # a way the harness already knew none of B2F's stood-in parts
            # had (Mt Moon, 2026-08-29). Recall only: where an unwalked way
            # starts is still not claimed.
            _fr = [str(x) for x in (w.get("from") or []) if x]
            _sp = int(w.get("stood_parts") or 0)
            if _fr:
                c.note = _join(c.note, "the ground you stood on in "
                               + ", ".join(_fr[:2]) + " DOES reach it")
            elif _sp:
                c.note = _join(c.note,
                               f"nor does any of the {_sp} other part(s) of "
                               f"this floor you have stood in — its way in "
                               f"is ground you have not stood on: unseen "
                               f"ground on this floor, or another floor")
        elif key in spent:
            c.status = "spent"
            c.n = spent[key]
            c.note = c.note or ("reached for and never once got through — "
                                "something stops you before the doorway")
        # A DOOR YOU STOOD ON THAT DID NOTHING IS NOT AN UNTRIED DOOR. The
        # crossing never completes, so nothing marks it and it stays
        # "never taken from here" for ever — and it is the only untried
        # exit on the floor, so the run goes back to it every round. Silph
        # 1F's pad at (16,10): "stepped through but no warp fired", three
        # attempts, three rounds. What we know is that it was tried and did
        # not open, which is what `spent` already means.
        elif "no warp fired" in str(c.note or ""):
            c.status = "spent"
            c.note = _join(c.note, "you have stood on this one and it did "
                                   "not fire; something has to change "
                                   "before it will")
        elif rec.get("shut"):
            reopened = (now is not None and rec.get("shut_at") != now) or \
                       (w.get("reachable") and not rec.get("shut_reach", True))
            c.status = "reopened" if reopened else "shut"
            c.n = int(rec.get("n") or 0)
            c.note = c.note or ("walked into and turned back; nothing is "
                                "known about what is beyond it")
        elif key in taken:
            bad = ex.dead_for(target, rec.get("to") or "") if target else 0
            # A DEAD END IS NOT A DOOR WITH UNTRIED GROUND BEHIND IT. The
            # brand is written when an ATTEMPT of this goal failed while
            # over there, which says where the attempt ran out of rounds,
            # not that the ground is spent: Celadon 4F called the stairs to
            # 5F a "KNOWN DEAD END" while the roof one floor further up —
            # the only place in the building that sells a drink — had six
            # things never pressed. Keep the count (it is true and it is
            # evidence), drop the verdict when the far side demonstrably
            # still has something.
            _dest = rec.get("to") or ""
            # transitive: the roof is two legs beyond the stairs
            _bey = something_beyond(ex, _dest, here) if _dest else None
            if bad and _bey:
                c.status = "taken"
                c.note = _join(c.note, f"this goal has failed beyond it "
                                       f"{bad}x — but that is where the "
                                       f"attempt ran out, not proof the "
                                       f"ground is spent")
            elif bad:
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
                c.beyond = beyond(ex, walked, target, here)
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

    # ONE DOORWAY, ONE LINE (_door_groups; untried.py's law). Adjacent
    # warp tiles leading to the same place are one opening — the Safari
    # rest house read as "door (2,7)" and "door (3,7)", two entries with
    # separate counts for one doorway (user, 2026-08-22: "functionally
    # the same warp"). The most-walked tile speaks for the doorway, the
    # counts combine, and the label shows every tile it spans.
    _groups = (ex._door_groups(m.get("warps") or [])
               if hasattr(ex, "_door_groups") else {})
    if any(len(g) > 1 for g in _groups.values()):
        _pref = {"unreachable": 2, "untried": 1}
        _byk = {c.key: c for c in out}
        _folded, _seen_g = [], set()
        for c in out:
            g = _groups.get(c.key) or (c.key,)
            if len(g) == 1:
                _folded.append(c)
                continue
            if g in _seen_g:
                continue
            _seen_g.add(g)
            members = [_byk[k] for k in g if k in _byk]
            members.sort(key=lambda cc: (-(cc.n or 0),
                                         _pref.get(cc.status, 0),
                                         tuple(int(v) for v
                                               in cc.key.split(","))))
            surv = members[0]
            surv.n = sum(cc.n or 0 for cc in members)
            surv.twins = [cc.key for cc in members[1:]]
            if not surv.note:
                surv.note = next((cc.note for cc in members[1:]
                                  if cc.note), "")
            _folded.append(surv)
        out = _folded

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
        elif d in taken and rec.get("inferred") and not int(rec.get("n") or 0):
            # the reverse of a crossing made from the far side (executor
            # note_transition): its destination is the map you came from
            c.status = "back"
            c.dest = c.dest or rec.get("to")
        elif d in taken:
            bad = ex.dead_for(target, rec.get("to") or "") if target else 0
            _dest2 = rec.get("to") or ""
            if bad and (something_beyond(ex, _dest2, here) if _dest2 else None):
                c.status = "taken"
                c.note = _join(c.note, f"this goal has failed beyond it "
                                       f"{bad}x — that is where the attempt "
                                       f"ran out, not proof it is spent")
            elif bad:
                c.status = "dead"
                c.note = c.note or f"this goal has already failed beyond it {bad}x"
            else:
                c.status = "taken"
                if walked:
                    c.beyond = beyond(ex, walked, target, here)
        else:
            c.status = "untried"
        # ...AND A SEAM YOU CANNOT WALK TO IS NOT AN EXIT FROM HERE. The
        # shim publishes, per side, whether any cell a walk from here
        # reaches lies on that edge. Doors and objects have carried "you
        # cannot walk to it from where you stand" for months; a seam
        # carried nothing, so the nine-cell pocket at the top of Route 6
        # advertised "walk south -> VERMILION_CITY|18,0 — never taken from
        # here" and the run decided the gate guard was blocking a road it
        # simply could not get to (user, 2026-08-26). Only the NEGATIVE is
        # claimed: no reached cell touches that side at all. Touching it
        # is not proof the crossing is there, and cross() still decides.
        _cr = (m.get("connections_reach") or {}) if isinstance(
            m.get("connections_reach"), dict) else {}
        if _cr and not _cr.get(d) and c.status in ("untried", "back"):
            c.status = "unreachable"
            c.note = _join(c.note, "no ground you can walk to from here "
                                   "touches that side of this map")
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
        # a wide fixture (Silph's two-tile card-key shutters) is ONE thing
        # minted at its first tile; the rest of it rides along as twins so
        # the tiles on screen are not read as doors gone missing
        c.twins = [f"{t.get('x')},{t.get('y')}"
                   for t in (o.get("twins") or []) if isinstance(t, dict)]
        seen_names[name] = c
        oc = outcomes.get(name) or {}
        c.n = int(oc.get("n") or 0)
        if oc.get("last"):
            c.note = str(oc["last"])
        if kind == "boulder":
            # A BOULDER IS IN THE WAY AND STAYS THERE. Same shape as the
            # bush: not something you press, something one field move
            # moves — and only after STRENGTH has been switched on from
            # the party menu on THIS map, because the engine clears that
            # on every map load. Never "spoken to", never "untouched".
            c.status = ("unreachable" if not o.get("reachable")
                        else "pushable" if knows_strength else "boulder")
            out.append(c)
            continue
        if kind == "cut_tree":
            # A BUSH IS NOT PRESSED, IT IS CUT. Interact by name never
            # reaches one (they come from the tileset scan), so "never
            # pressed" would be true for ever and explore would reach for
            # it first every round. It is a way on once CUT is known.
            # ...and one you cut before has grown back (reload does that
            # in this recomp). A REGROWN BUSH IS NOT A FRESH WAY ON: the
            # first cut already opened that ground, so cutting it again
            # reopens what was open — but ranked "a way on" it sat at the
            # top of explore every round for ever, and the run spent six
            # attempts of leg 33 cutting the same Fuchsia bush between
            # Center trips while three never-walked seams out of the city
            # sat below it (user: "it says its going to exit the city
            # then doesnt").
            _cut = (getattr(ex, "_cut_bushes", {}) or {}).get(mid) or []
            _again = f"{o.get('x')},{o.get('y')}" in _cut
            # ...UNLESS IT GREW BACK ACROSS THE ONLY WAY OUT. "recut" is
            # right when the first cut already opened that ground — but a
            # bush is only "already open" from where you can still stand.
            # ROUTE_9|0,8 is a nine-cell pocket whose east seam is the bush
            # at (5,8): it regrew, the ledger retired it as a recut, the
            # pocket read FULLY WORKED, and explore walked at a wall it had
            # been told nothing about (2026-08-30). The shim says whether
            # felling one reaches walkable ground no walk from here does;
            # when it would, this is a way on whether or not it was cut
            # before.
            if _again and o.get("opens"):
                _again = False
                c.note = _join(c.note,
                               "you cut this one before and it grew back — "
                               "and it is across the only way out of the "
                               "ground you can reach from here now")
            c.status = ("unreachable" if not o.get("reachable")
                        else ("recut" if _again else "cuttable")
                        if knows_cut else "bush")
        elif not o.get("reachable") and kind != "item":
            c.status = "unreachable"
            # ...AND WATER IS NOT A WALL WHEN THE PARTY CARRIES SURF. The
            # shim marks by_water on a thing the swum reach touches; the
            # bare verdict ranked Articuno with the furniture.
            if o.get("by_water"):
                c.note = _join(c.note,
                               "no walk from here reaches it, but the WATER "
                               "does: a party Pokemon knows SURF, and from "
                               "the water, water is walkable")
            # WHY, when the tile beside it says so. "you cannot walk to it"
            # is a verdict; "a warp pad is beside it" is a way in.
            if o.get("why"):
                c.note = _join(c.note, str(o["why"]))
        elif kind == "fixture" and o.get("gate") == "open":
            # AN ANSWERED QUIZ MACHINE IS DONE: its gate stands open on
            # screen, and pressing it again only repeats the rules.
            c.status = "inert"
            c.note = "its gate is OPEN — answered; pressing it again changes nothing"
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
                # the verdict lives in the rendered words (with the pad
                # recall's ops contract beside it); the note keeps only
                # the WHY, when the screen gave one
                c.note = _join(c.note, str(o.get("why") or ""))
        out.append(c)

    # ---- the edges of the seen ground ---------------------------------
    # Footprint leftover (b): the frontier reached the model only as head
    # TEXT, never as candidates, so the one thing the footprint calls
    # unfinished here never competed with the doors in the ranked list —
    # and position is the budget. A frontier cell is minted fresh from
    # THIS observation on every build: it vanishes by itself the moment
    # the ground past it comes on screen, which is exactly why a STORED
    # door-style status would mean nothing. Its status is computed, never
    # remembered. The shim orders spots nearest-first; n carries that
    # walked distance so the rank keeps the order. A frontier key can
    # never collide with a door's: seen_reach excludes warp tiles from
    # its frontier.
    for f in (m.get("frontier") or [])[:4]:
        if f.get("x") is None or f.get("y") is None:
            continue
        c = Candidate(key=f"{f['x']},{f['y']}", kind="frontier",
                      x=f["x"], y=f["y"], status="unlooked")
        c.n = int(f.get("d") or 0)
        if f.get("slide"):
            # an ARROW whose slide ends on ground never on screen: you
            # cannot stand on it, you step on and are carried (leftover (c))
            c.look = "arrow"
            c.note = (f"{c.n} step(s) from you; an ARROW tile — stepping "
                      "onto it carries you onto ground that has never been "
                      "on screen: {\"op\":\"walk_to\",\"x\":%d,\"y\":%d} "
                      "steps on and reports where the slide put you"
                      % (f["x"], f["y"]))
        else:
            c.note = (f"{c.n} step(s) from you over seen ground; "
                      "{\"op\":\"walk_to\",\"x\":%d,\"y\":%d} stands there"
                      % (f["x"], f["y"]))
        out.append(c)
    # ...and the spots only a swim reaches (the shim lists these only
    # while a party Pokemon knows SURF and you are on foot)
    for f in (m.get("frontier_water") or [])[:2]:
        if f.get("x") is None or f.get("y") is None:
            continue
        c = Candidate(key=f"{f['x']},{f['y']}", kind="frontier",
                      x=f["x"], y=f["y"], status="unlooked", by_water=True)
        c.n = int(f.get("d") or 0)
        c.note = ("across the WATER — no walk reaches it, but a party "
                  "Pokemon knows SURF: {\"op\":\"walk_to\",\"x\":%d,"
                  "\"y\":%d,\"surf\":true} rides there, and explore "
                  "rides and sweeps it for you" % (f["x"], f["y"]))
        out.append(c)

    # ---- rank ---------------------------------------------------------
    _goal_kinds = _goal_kinds_of(target)
    for c in out:
        # untried before taken; among untried, an exit into a map never
        # SEEN before one back into a seen map (unopened before known);
        # among taken, fewest takes first; then key for determinism
        into_seen = bool(c.dest) and _map_of(c.dest) in seen_maps
        # THE KIND OF THING THAT ANSWERS THIS GOAL COMES FIRST. On the
        # Celadon roof, with the subgoal "has_item FRESH_WATER", the top
        # entry was `press CELADONMARTROOF_LITTLE_GIRL` — an NPC, ranked
        # ahead of three untouched vending machines, and the girl is the
        # one who WANTS a drink. Ranked BELOW status, so untried still
        # beats taken and nothing spent gets promoted: this only orders
        # things that are equally fresh. Which to take is still the
        # model's; this decides what to read first, not what to do.
        # A WAY OUT YOU CANNOT REACH YET STILL BEATS A PERSON YOU HAVE
        # ALREADY SPOKEN TO. Reachability led the tuple, so on Route 16 the
        # five doors toward the HM02 house — including the house's own door
        # and both upper-corridor doors — sorted BELOW six bikers the run
        # had already beaten, at positions 15-19 of the list, while the
        # only reachable untried exit walked away from the goal. An
        # unreachable door is still the map telling you where it has not
        # been; a pressed trainer is finished business. Fresh-and-reachable
        # first, then a fresh way out you cannot reach yet, then everything
        # already done (user's call, 2026-08-19).
        _fresh = STATUS_RANK.get(c.status, 9) <= 1
        _way = c.kind in ("door", "seam")
        if c.reachable:
            _bucket = 0 if _fresh else 2
        else:
            _bucket = 1 if (_fresh and _way) else 3
        # FOR A MAP GOAL, ONLY A WAY OUT CAN CHANGE THE MAP. A door taken
        # twice sat at item 14 under three unpressed signs while the goal
        # was PEWTER_CITY, and the run pressed the signs (Viridian Forest,
        # 2026-08-25). Same rule plan_explore already follows in words.
        if (_bucket == 2 and _way and c.status in ("taken", "came_in_by", "back")
                and str(target or "").startswith("map:")):
            _bucket = 1
        c.rank = (_bucket, not c.reachable, STATUS_RANK.get(c.status, 9),
                  1 if _refused(c) else 0,
                  0 if c.kind in _goal_kinds else 1,
                  0 if c.kind == "frontier" else 1, into_seen,
                  c.n, c.kind, c.key)
    out.sort(key=lambda c: c.rank)

    # ---- explore ------------------------------------------------------
    if want_explore:
        out.insert(0, Candidate(key="explore", kind="op", status="op",
                                note=plan_explore(ex, obs, out,
                                                  target=target)))
    return out


def _asking(c) -> bool:
    """Is this thing waiting on a yes or no it has already asked for?

    An interact with no answer holds the box open (the Dome Fossil rule)
    and the touch is retracted, so the thing reads "never pressed" — and
    explore, which presses without an answer, offered the same Pewter
    Super Nerd first eighteen times while he asked "Did you check out the
    MUSEUM?" (2026-08-29). Pressing again only re-asks; what is missing is
    the answer, and that is the model's to give.
    """
    return "is ASKING something and the box is STILL OPEN" in str(
        getattr(c, "note", "") or "")


def _refused(c) -> bool:
    """Has this candidate turned the run back? The status cannot say: a
    crossing that failed never completed, so it stays "untried"."""
    n = str(getattr(c, "note", "") or "")
    # A FOOTPRINT STOP IS NOT A REFUSAL. "cannot be reached over the ground
    # you have SEEN" says the search ended where the looking ended, and
    # explore's next sweep may open it — but the note carries the
    # executor's FAILED prefix, so this called it "turned you back before"
    # and Viridian's north road read as a wall (2026-08-29, user watching:
    # "the north exit ... is blocked by bushes").
    if "cannot be reached over the ground" in n:
        return False
    return ("FAILED" in n or "cannot be walked to" in n
            or "no walkable path" in n)


def plan_explore(ex, obs: dict, cands: list[Candidate] | None = None,
                 target: str | None = None) -> str:
    """What one `explore` step WOULD do from here, in words. Nothing runs.

    The order is the sweep's, made explicit: press what is untouched here
    (items, then fixtures, then people, then signs), else take the best
    untried exit here, else walk over walked ground to the nearest area that
    still has an exit never taken and take it, else say so."""
    here = ex._where(obs)
    cands = cands if cands is not None else build(ex, obs, want_explore=False)
    # ...AND A LIFT CAR IS NEVER "FULLY WORKED" HERE EITHER. The header
    # says so now; this line is item 1, the most prominent thing on the
    # page, and it was still telling the model to leave a car whose panel
    # is the only reason to be in it.
    if (str((obs.get("map") or {}).get("id") or "").endswith("_ELEVATOR")
            or (obs.get("map") or {}).get("lift_floors")):
        return ("press the panel and ride: {\"op\":\"elevator\","
                "\"floor\":\"<a floor as the panel spells it>\"} — the "
                "car's one door opens onto whichever floor you rode to")
    # THE WORDS FOLLOW THE DEED. With the footprint, explore's first act
    # on a floor with unseen ground is the SWEEP (executor _explore_step),
    # and this line said "press the GIRL here" while the deed walked to
    # the edge of seen ground — the same words/deed split the ledger has
    # paid for before (Viridian Forest gate, 2026-08-25: the north door
    # had never been on screen, and item 1 named a person).
    _m0 = obs.get("map") or {}
    _fr0 = _m0.get("frontier") or []
    if _fr0:
        _f = _fr0[0]
        _n0 = int(((_m0.get("seen") or {}).get("frontier_n")) or len(_fr0))
        # the deed sweeps nearest a way out never taken that no walk from
        # here reaches (executor _explore_step); say so
        _uw0 = [c for c in unreached_ways(cands) if c.kind == "door"]
        if _uw0:
            return (f"walk to the unseen ground nearest {_uw0[0].label()} — "
                    f"a way out never taken that no walk from here reaches — "
                    f"and keep going until something new comes into view; "
                    f"{_n0} such spot(s) on this floor; nothing past them is "
                    f"known yet")
        if _f.get("slide"):
            return (f"step onto the ARROW tile at ({_f.get('x')},"
                    f"{_f.get('y')}) — it carries you onto ground that has "
                    f"never been on screen — and see what comes into view; "
                    f"{_n0} such spot(s) on this floor; nothing past them "
                    f"is known yet")
        return (f"walk to the nearest edge of the ground you have seen, "
                f"({_f.get('x')},{_f.get('y')}), and keep going until "
                f"something new comes into view — {_n0} such spot(s) on "
                f"this floor; nothing past them is known yet")
    # ...THEN THE FRONTIER ACROSS THE WATER, when someone can ride it (the
    # deed rides there and sweeps; see executor _explore_step, 2026-08-28)
    _fw0 = _m0.get("frontier_water") or []
    if _fw0 and any(str(mv.get("id") if isinstance(mv, dict) else mv) == "SURF"
                    for mon in (obs.get("party") or [])
                    for mv in (mon.get("moves") or [])):
        _f = _fw0[0]
        _nw = int(((_m0.get("seen") or {}).get("frontier_water_n")) or len(_fw0))
        return (f"ride the water to the nearest edge of the ground you have "
                f"seen across it, ({_f.get('x')},{_f.get('y')}), and sweep "
                f"from there — {_nw} such spot(s) on this floor that only a "
                f"swim reaches; nothing past them is known yet")
    order = {"item": 0, "fixture": 1, "cut_tree": 1, "boulder": 1,
             "shut_door": 1, "npc": 2, "trainer": 2, "sign": 3}
    # THIRTY-SIX OF A THING IS ONE THING. The kind order above is fixed —
    # fixtures before people, always — and in the Rocket Game Corner that
    # meant item 1 read "press SLOT_MACHINE_18 here (fixture); 31 thing(s)
    # here are untouched" while the way down to the hideout is a Rocket you
    # talk to. Pressing the twenty-second slot machine cannot teach you
    # what the first twenty-one did not. How MANY of a thing there are is
    # on the screen and it is worth something: a room's one strange person
    # is a lead in a way its thirty-sixth identical machine is not, so
    # among things equally untouched the rarer name goes first. Rooms where
    # everything is unique are unaffected (user, watching the casino: "its
    # only looking at the slot machines instead of talking to anyone").
    # FURNITURE ONLY. People with numbered names are different people who
    # say different things — ROUTE3_COOLTRAINER_F1 and F2 are two trainers,
    # not one seen twice — so a crowd is only ever a crowd of fixtures.
    _crowd: dict = {}
    for c in cands:
        if c.kind == "fixture":
            _crowd[_stem(c.key)] = _crowd.get(_stem(c.key), 0) + 1
    # ...AND THE SAME FOR THINGS, WHICH I ONLY FIXED FOR EXITS. A press
    # that came back "no reachable tile adjacent to target" leaves the
    # thing "never spoken to", so explore kept offering it: Silph 2F's
    # worker is behind the card-key glass, the interact failed, and item 1
    # said "press SILPHCO2F_SILPH_WORKER_F here" with the refusal printed
    # directly underneath it.
    things = sorted((c for c in cands
                     if c.status in ("untouched", "unspoken", "cuttable")
                     and c.reachable and not _refused(c)
                     and not _asking(c)
                     and c.kind not in ("door", "seam", "op")),
                    key=lambda c: (0 if c.kind in _goal_kinds_of(target) else 1,
                                   _crowd.get(_stem(c.key), 1),
                                   order.get(c.kind, 4), c.key))
    def _thing_line():
        if not things:
            return None
        if things[0].status == "cuttable":
            return (f"CUT the bush at ({things[0].x},{things[0].y}) — a "
                    f"party Pokemon knows CUT and it is a way on")
        return (f"press {things[0].key} here ({things[0].kind}); "
                f"{len(things)} thing(s) here are untouched")

    _stood_aside = []          # live-beyond exits _way_line deferred on

    def _way_line():
        # A WAY THAT JUST REFUSED YOU IS NOT AN UNTRIED WAY. The crossing
        # stays "untried" because it never completed, and the refusal lives
        # only in the note — so explore kept recommending "take walk west"
        # in a four-cell Route 14 nook whose west seam cannot be reached
        # from it, and the run stood in that pocket 1181 times. Prefer an
        # exit nothing has turned us back from; fall back to the refused
        # one only if it is all there is, since the world does change.
        exits = [c for c in cands if c.status == "untried"
                 and c.kind in ("door", "seam")]
        _fresh = [c for c in exits if not _refused(c)]
        if _fresh:
            return f"take {_fresh[0].label()} — untried from here"
        # WHEN EVERY WAY OUT HAS BEEN TAKEN, TAKE THE LEAST-TAKEN ONE. A
        # door walked twice has had less of a look than one walked fifty
        # times, and where a run circles it is usually circling the SAME
        # two exits — Silph 3F's pads were taken 15 and 31 times while
        # others sat on 1. This does not claim anything is behind it; it
        # orders what is already here by how little of it has been used
        # (user's idea, 2026-08-20).
        # ...AND IT OUTRANKS A WAY THAT IS PROVEN SHUT. This sat BELOW the
        # refused-exit fallback, so on Route 4 — whose east seam is on the
        # far side of the mountain and can never be walked to from the
        # entrance side — item 1 read "take walk east, though it turned you
        # back last time" while two doors the run had walked sat unnamed. A
        # door used once has more left in it than a wall.
        _used = sorted((c for c in cands
                        if c.kind in ("door", "seam") and c.reachable
                        and c.status in ("taken", "came_in_by")
                        and not _refused(c)),
                       key=lambda c: (c.n, c.key))
        # WHERE A WAY LEADS OUTRANKS HOW OFTEN IT WAS USED. Counting bare
        # uses put "walk east (1x)" at item 1 on Route 20 — a road back
        # into worked ground — while the Seafoam door beside it (8x)
        # carries, in this very ledger, "4 more leg(s) on through it
        # SEAFOAM_ISLANDS_B4F still has 1 exit(s) never taken". Both facts
        # are already computed; the one that says something is LEFT that
        # way is the stronger one, and least-used still breaks the tie
        # among equals (user, 2026-08-23). Where it leads is stated, so
        # the reason is on the page and the choice stays the model's.
        # ...so when one of them leads somewhere with something left, this
        # line STANDS ASIDE: the nearest-area recall below says the same
        # fact better — it names the region, how many legs, the first leg
        # to take, and what is still there — and it was being preempted by
        # a bare use-count for want of this check.
        _live = [c for c in _used
                 if c.beyond and "nothing new that way" not in c.beyond]
        if _live:
            _stood_aside.extend(_live)
            return None
        if _used and _used[0].n < (_used[-1].n if len(_used) > 1 else 0):
            _c = _used[0]
            return (f"everything here has been taken at least once; the "
                    f"least-used way out is {_c.label()} ({_c.n}x, against "
                    f"{_used[-1].n}x for the most-used) — going back "
                    f"through the one you have leaned on least is how a "
                    f"circuit breaks")
        # A WAY THAT REFUSED YOU IS NEVER ITEM 1 WHILE ANYTHING ELSE IS
        # LEFT ANYWHERE. This used to return "take walk west — untried
        # from here, though it turned you back last time", endorsing a
        # proven wall over the nearest-area recall two steps below — on
        # Route 20 the Seafoam door the run had walked through sat unnamed
        # while item 1 sent it at the wall a 30th time. Fall through; the
        # world-exhausted line owns the "world does change" retry.
        return None

    # A PERSON IS NOT A WAY OUT. The kind of thing that answers the goal
    # comes first in the ledger's ranking already; item 1 ignored it and
    # always offered a press before a door. With the step's target a MAP,
    # standing in Mt Moon 1F, it read "press MTMOON1F_COOLTRAINER_F2 here;
    # 6 thing(s) here are untouched" on all 48 arrivals, while the run was
    # trying to find the ladder out of the mountain and had four of them
    # in the same list. Talking to somebody cannot put you on another map;
    # for a map goal the way out is read first, and the people are still
    # right there in the list underneath (live, 2026-08-20).
    if str(target or "").startswith("map:"):
        _line = _way_line()
        if _line:
            return _line
    _line = _thing_line()
    if _line:
        return _line
    _line = _way_line()
    if _line:
        return _line
    # ...AND SAY THE SAME THING THE HEADER SAYS. The header learned that a
    # floor holding something no walk reaches is not finished; this line,
    # two lines below it, still announced "THIS AREA IS FULLY WORKED —
    # nothing new can be found by staying". Same split as the lift car:
    # header fixed, plan_explore left behind.
    _stuck = [c for c in cands if c.status == "unreachable"
              and c.kind not in ("op", "door", "seam")]
    # nearest area with something never taken OR never pressed, over
    # walked ground — leaving worked ground for ground that still has
    # something is the whole idea, so both kinds of "something" count
    # EVERY GROUND THAT STILL HAS SOMETHING, NOT ONLY THE CLOSEST ONE.
    # Printing a single winner hid places with far more left one door away:
    # on Route 20 the recall named FUCHSIA_CITY (2 legs, two untried doors)
    # and never mentioned Seafoam at all, whose floors hold untried exits
    # three to five legs down through a door the party has already walked
    # (user, 2026-08-23: "should be promoting seafoam as its got unwalked
    # stuff inside"). The leg count keeps meaning what it says — a floor is
    # a leg — and the choice between near-and-thin and far-and-rich is the
    # model's to make, which it cannot do about a place it is not told
    # about.
    found = []
    regions = set(list(getattr(ex, "frontier", {}) or {})
                  + list(getattr(ex, "sightings", {}) or {}))
    _reach_from = {}
    for _f in ((obs.get("map") or {}).get("seen_unreached") or {}).get("from") or []:
        if isinstance(_f, dict) and _f.get("region"):
            _reach_from[str(_f["region"])] = int(_f.get("n") or 0)
    regions |= {r for r in _reach_from
                if r in (getattr(ex, "visits", {}) or {})
                or r in (getattr(ex, "explored", {}) or {})}
    for region in regions:
        if region == here:
            continue
        left = ex._frontier_left(region)
        things = untouched_in(ex, region)
        unseen = int((getattr(ex, "region_seen", None) or {})
                     .get(region, 0) or 0)
        unseen = max(unseen, _reach_from.get(region, 0))
        # ways out never taken that no walk reached from there (executor
        # note_frontier keeps them apart from the frontier)
        _unr = [k for k in ((getattr(ex, "unreached_at", None) or {})
                            .get(region) or [])
                if k not in set(ex._taken_here(region) or {})]
        if not (left or things or unseen or _unr):
            continue
        path = ex._route(here, region)
        if not path:
            continue
        # THE WORDS FOLLOW THE DEED (executor _explore_step): for a map
        # goal, an untried exit or unseen ground first, things-only areas
        # after; distance decides within a tier.
        _pri = ((0 if (left or unseen or _unr) else 1)
                if str(target or "").startswith("map:") else 0)
        # two explore walks there that saw nothing new: last (executor rule)
        if int((getattr(ex, "_dry_walks", None) or {}).get(region, 0) or 0) >= 2:
            _pri = 3
        # same order as the deed (_explore_step): finish the area you are
        # in first (this map, or a room whose door you took from here),
        # then distance, then a way out before ground to look at
        _rooms = {(e or {}).get("to")
                  for k, e in (((getattr(ex, "explored", {}) or {})
                                .get(here) or {}).items())
                  if str(k)[:1].isdigit() and (e or {}).get("to")}
        _local = 0 if (region.split("|")[0] == here.split("|")[0]
                       or region in _rooms) else 1
        r = (_pri, _local, len(path), 0 if (left or _unr) else 1,
             -(len(left) + len(things) + unseen + len(_unr)), region)
        found.append((r, region, left, things, path, unseen, _unr))
    found.sort(key=lambda f: f[0])
    best = found[0] if found else None
    if best:
        _, region, left, things, path, unseen, _unrb = best
        fk, fd = path[0]
        first = f"walk {fk}" if not fk[0].isdigit() else f"door ({fk})"
        # THE NEAREST-AREA RECALL OUTRANKS THE UNREACHABLES NOTE. That note
        # used to take item 1 whenever anything unreachable sat on the
        # floor — and Route 20 always has sea trainers no walk reaches, so
        # the one line naming walked ground that still has an exit never
        # taken (Seafoam B4F, legs through the door already walked) could
        # never be said there. Both facts fit; the walk leads.
        what = []
        if left:
            # name a seam as an EDGE and a door as a DOOR: "take one of
            # west" read as a typo; the untried thing on Route 7 was its
            # west edge — the road to the next town.
            def _word(k):
                return (f"the {k} edge" if k in ("north", "south", "east",
                                                "west") else f"door ({k})")
            what.append("take " + " or ".join(_word(k)
                                              for k in sorted(left)[:3])
                        + " (never taken)")
        if things:
            what.append(f"press {', '.join(things[:3])}")
        if unseen:
            what.append(f"sweep — {unseen} spot(s) where its seen ground ends")
        if _unrb:
            what.append("look for the way to " + ", ".join(_unrb[:2])
                        + " — a way out never taken that no walk reached "
                          "when you last stood there")
        _uw = unreached_ways(cands)
        _head = ("EVERYTHING YOU CAN REACH HERE IS DONE, but "
                 + ", ".join(c.label() for c in _uw[:3])
                 + " on this floor "
                 + ("has" if len(_uw) == 1 else "have")
                 + " never been taken and no walk from here reaches "
                 + ("it" if len(_uw) == 1 else "them") + "."
                 if _uw else
                 "THIS AREA IS FULLY WORKED — every exit taken, "
                 "everything pressed; nothing new can be found by staying."
                 if not _stuck else
                 "Everything you can REACH here is done ("
                 + ", ".join(c.key for c in _stuck[:3])
                 + " sits where no walk from here goes — the way in is "
                 "what is missing, not the thing).")
        # ONE PER FIRST LEG. Ranked purely by distance, all three slots
        # went to places behind the SAME first step — Safari Zone Gate,
        # the Fuchsia Center and Route 18, every one of them "first walk
        # east" — so the page listed three ways of saying east and Seafoam,
        # the only other direction with anything left, still never
        # appeared. The first leg is the choice actually being made; list
        # each one once, nearest example first.
        # ONE PER FIRST LEG, AND THE RICHEST OF THEM — not the nearest.
        # `found` is sorted by distance, so the first entry behind a door
        # won its slot by being closest: behind Mt Moon's entrance that is
        # 1F's unpressed items, while THREE floors deeper sat 11 spots of
        # ground never on screen and two ways out never taken. The run read
        # "MT_MOON_1F has 12 thing(s) never pressed", concluded it had
        # explored the mountain, and ping-ponged between Pewter and Route 4
        # for a dozen rounds (user, 2026-08-29). The leg is the choice
        # being made; what is worth the walk is decided by what is back
        # there, so name the most there is behind each door.
        _by_leg = {}
        for _e in found[1:]:
            _fk0 = _e[4][0][0]
            _n0 = len(_e[2]) + len(_e[3]) + _e[5] + len(_e[6])
            if _fk0 not in _by_leg or _n0 > _by_leg[_fk0][0]:
                _by_leg[_fk0] = (_n0, _e)
        _ranked = [e for _, (_, e) in sorted(_by_leg.items(),
                                             key=lambda kv: -kv[1][0])]
        _more, _legs_seen = [], {path[0][0]}
        for _r2, _reg2, _left2, _things2, _path2, _unseen2, _unr2 in _ranked:
            if len(_more) >= 3:
                break
            _fk2, _fd2 = _path2[0]
            if _fk2 in _legs_seen:
                continue
            _legs_seen.add(_fk2)
            _first2 = (f"walk {_fk2}" if not _fk2[0].isdigit()
                       else f"door ({_fk2})")
            _has = []
            if _left2:
                _has.append(f"{len(_left2)} exit(s) never taken")
            if _things2:
                _has.append(f"{len(_things2)} thing(s) never pressed")
            if _unseen2:
                _has.append(f"{_unseen2} spot(s) of ground never on screen")
            if _unr2:
                _has.append(f"{len(_unr2)} way(s) out never taken that no "
                            f"walk reached from there")
            _more.append(f"{_reg2} ({len(_path2)} leg(s), first {_first2}"
                         f" to {_fd2}) has " + " and ".join(_has))
        return (_head + f" The nearest "
                f"ground with something never tried is {region} "
                f"({len(path)} leg(s), first {first} to {fd}); explore "
                f"walks there to " + " and ".join(what)
                + (". Other ground you have walked that still has "
                   "something: " + "; ".join(_more)
                   + ". Nearest is not always most: which of these is "
                   "worth the walk is yours."
                   if _more else ""))
    if _stood_aside:
        # The recall above could not put a walked route together (an edge
        # it needs is blocked this world-mark, or the graph is split), but
        # the exit itself and what lies past it are still facts.
        _c = _stood_aside[0]
        return (f"everything here has been taken at least once, and no "
                f"walked route to that ground could be put together right "
                f"now. The way out that leads toward something never taken "
                f"is {_c.label()} ({_c.n}x): {_c.beyond}")
    if _stuck:
        return ("everything you can REACH here is done, but "
                + ", ".join(c.key for c in _stuck[:3])
                + " sits on this floor where no walk from here goes — the "
                "way in is what is missing, not the thing")
    _refd = [c for c in cands if c.status == "untried"
             and c.kind in ("door", "seam") and _refused(c)]
    if _refd:
        return ("THIS AREA IS FULLY WORKED and so is everywhere you can "
                "walk to — all that remains here is a way that has refused "
                f"you before: {_refd[0].label()}. The world does change, so "
                "retrying it costs only a step; otherwise something you "
                "have done must be undone or something you carry must be "
                "used to open new ground")
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
        k = f"{step.get('x')},{step.get('y')}"
        # a step aimed at any tile of a folded doorway is on-ledger
        return by_key.get(k) or next(
            (c for c in cands if k in (getattr(c, "twins", None) or [])),
            None)
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
    "unlooked": "the ground PAST it has NEVER BEEN ON SCREEN — standing "
                "there brings it into view; {{\"op\":\"sweep\"}} walks "
                "every such spot on this floor and stops at the first "
                "new thing",
    "reopened": "turned you back once, but the world has moved since",
    "taken": "taken {n}x",
    "came_in_by": "the door you came in by; taken {n}x",
    "back": "the way back: you came onto this map across this edge, and "
            "have not crossed it from this side",
    "spent": "reached for {n}x and never once got through",
    "shut": "SHUT — walked into {n}x and turned back every time",
    # HOW MANY TIMES IT HAS BEEN REACHED FOR IS THE POINT. Every other
    # entry on the page carries a count -- "taken 14x", "pressed 7x" -- and
    # this one, the most-repeated action in the run, carried none, because n
    # counts times TAKEN and a way that never once worked has n=0. So the
    # page numbered everything the run had managed and went silent on
    # everything it had failed at, and `walk west` looked no more worn than
    # an untried door while the outcomes ledger held 184 attempts from this
    # very spot against this very goal (user: "tried this so many times i
    # have a hard time believing it can see that clearly and still choose to
    # do the same thing with no caveats"). The count is ours, it is about
    # the run's own actions, and it was being kept back. "spent" beside it
    # has said it this way all along.
    "sealed": "reached for {n}x from here and never once got through — "
              "proven uncrossable from this area",
    "sealed_untried": "proven uncrossable from this area",
    "dead": "KNOWN DEAD END for this goal",
    "unreachable": "you cannot walk to it from where you stand",
    "lift_door": "the way out of this car — always open, and where it lets "
                 "you out is set by the panel, not by which door you pick",
    "untouched": "never pressed",
    "unspoken": "never spoken to",
    "touched": "pressed {n}x",
    "worth_a_word": "pressed {n}x, when you were carrying different things "
                    "— people here say different things once the world moves",
    "inert": "pressed {n}x; nothing changed",
    "cuttable": "a bush — CUT clears it, and a party Pokemon knows CUT",
    # "when the game reloads" read as a process restart, and the run cut a
    # bush, crossed off its map, and wrote "I have already cleared the bush"
    # for rounds after (2026-09-03). The engine's rule, OverworldController
    # setMap: a cut tree grows back whenever its MAP is re-entered.
    "recut": "a bush you have CUT before, grown back (a cut bush grows back "
             "the moment you leave its map and come back, so cut it and go "
             "THROUGH in the same visit) — cutting it reopens the SAME way "
             "it opened before, not new ground",
    "bush": "a bush — CUT clears it; nobody in the party knows CUT yet",
    # the braces are doubled because this table is .format()ed for {n}
    "pushable": "a BOULDER — it is pushed, not pressed, and a party Pokemon "
                "knows STRENGTH. Switch STRENGTH on from the party menu "
                "first ({{\"op\":\"field_move\",\"move\":\"STRENGTH\"}})"
                " — the game turns it off again on every map load — then "
                "say where it should END UP and the shoving is worked out "
                "for you: {{\"op\":\"push\",\"x\":N,\"y\":N,"
                "\"to_x\":N,\"to_y\":N}}. A bare "
                "{{\"dir\":\"up|down|left|right\"}} instead shoves it "
                "one single cell",
    "boulder": "a BOULDER — it is pushed, not pressed, and STRENGTH is what "
               "pushes it; nobody in the party knows STRENGTH yet",
}

NOTE_CHARS = 140
# A FAILURE NOTE IS MOSTLY THE DIAGNOSIS, and the diagnosis lives at the
# END of it. Route 14 stranded the party in a four-cell pocket for 93
# rounds while the ledger printed "BFS from 19,6 walked 4 cells …" — the
# very next clause, cut by the ellipsis, named a person standing in the
# one-tile gap. The op knew. The prompt hid it. Failure notes get a wider
# budget, and the sentence naming what stopped the walk is never cut.
FAIL_CHARS = 460
_STOP_MARK = "Right where the walk stopped:"


def _reached_before(obs, ex, name) -> str:
    """Which statue setting the run has REACHED this thing in, if any.

    The mirror of the door line. Standing where no walk reaches a thing,
    the page said only "not walkable-to right now" — true, and silent about
    the eight pages on which the very same ball was walkable. The run read
    the silence as a wall and left the Mansion to look for the Secret Key
    somewhere else (2026-08-24)."""
    try:
        mid = str(((obs or {}).get("map") or {}).get("id") or "")
        _here = ex._where(obs)
        _rs = getattr(ex, "reach_settings", None) or {}
        seen = ((_rs.get(_here) or {}).get(str(name))
                or (_rs.get(mid) or {}).get(str(name)) or [])
        if not seen:
            return ""
        return (" — BUT YOU HAVE REACHED IT BEFORE, with the statues "
                + " and ".join(w.upper() for w in seen)
                + ("; it is the setting that moves, not the thing"
                   if len(seen) < 2 else
                   "; so no walk reaching it now is about where you STAND, "
                   "not about the thing"))
    except Exception:
        return ""


def _spent_both_note(obs, ex) -> str:
    """What pressing again can still answer HERE — nothing, once every way
    out of this floor that no walk reaches has been seen in both settings.
    Only the doors this floor actually shows as unreachable count, and only
    settings the run itself recorded."""
    try:
        m = (obs or {}).get("map") or {}
        mid = str(m.get("id") or "")
        seen = (getattr(ex, "shut_settings", None) or {}).get(mid) or {}
        shut = [w for w in (m.get("warps") or [])
                if w.get("x") is not None and not w.get("reachable")]
        if not shut:
            return ""
        both = [w for w in shut
                if len(seen.get(f"{w.get('x')},{w.get('y')}") or ()) > 1]
        if len(both) != len(shut):
            return ""
        return (". EVERY way out of this floor that no walk reaches — "
                + ", ".join(f"({w.get('x')},{w.get('y')})" for w in shut[:4])
                + " — has ALREADY been looked at with this setting BOTH "
                  "ways, and no walk reached any of them either way, so "
                  "pressing it again cannot answer anything about THEM")
    except Exception:
        return ""


# A MAP WITH NO EDGES IS NOT THEREBY INDOORS. The engine's own outside test
# (Map.isOutside, the one wLastMap reads) counts only OVERWORLD and PLATEAU,
# so SAFARI_ZONE_WEST — tall grass under open sky, walled by fences — read
# "indoors, no edges" to a model standing in it (leg 36, 2026-08-26). The
# tileset says which it is: FOREST is Viridian Forest and the four Safari
# areas, walled ground you can see the sky from; OVERWORLD/PLATEAU ground
# simply has no neighbour on any side; anything else is a building.
OPEN_SKY_TILESETS = {"OVERWORLD", "PLATEAU"}
FOREST_TILESETS = {"FOREST"}


def no_edge_words(m: dict) -> str:
    """Why this map has no seams, said only as far as the tileset allows."""
    ts = str((m or {}).get("tileset") or "").upper()
    if ts in FOREST_TILESETS:
        return ("walled ground under open sky, like a forest or a park — "
                "no edge of this map connects anywhere; its gates and "
                "doors are the only ways out")
    if ts in OPEN_SKY_TILESETS:
        return ("no edge of this map connects anywhere; its doors are "
                "the only ways out")
    if ts:
        return "indoors, no edges; the doors are the only ways out"
    return "no edges; the doors are the only ways out"


def printed_roads_words(map_id: str, seen_sides, unseen_sides, edges: dict) -> str:
    """What the TOWN MAP in the bag draws for the map you stand on, side by
    side, each marked seen or never on screen.

    THE FOOTPRINT WAS STRICTER THAN THE GAME. A seam is listed only once a
    cell of its side has been on screen — right, for ground — but the
    printed map in the bag names a map's roads whether or not you have
    looked that way, and the page said nothing of them for the map you
    stood on. On Route 7 the head read "no edge of this map has been on
    screen yet (north, west, east never looked at)"; the model went for the
    gate east, was told the guard was thirsty, and formed "Celadon is past
    the thirsty guard" — with Celadon one seam WEST, drawn on the map it
    held, never mentioned (2026-09-04, user: "its already been on the other
    side via the underground path"). The layout of a held map is the
    holder's to read; which roads are open stays what walking finds.
    """
    roads = (edges or {}).get(str(map_id)) or {}
    if not roads:
        return ""
    seen = {str(x) for x in (seen_sides or [])}
    unseen = {str(x) for x in (unseen_sides or [])}
    parts = []
    for d, nb in sorted(roads.items()):
        tag = ("seen" if d in seen else
               "that side never on screen" if d in unseen else "")
        parts.append(f"{d} -> {nb}" + (f" ({tag})" if tag else ""))
    return (" The printed map you hold draws this map's roads: "
            + ", ".join(parts)
            + ". The map draws the LAYOUT, not which roads are open.")


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
    # NO MAP, NO VERDICT. An observation taken while a box is up carries no
    # map, and this page then said "WHERE YOU STAND: None|None — FULLY
    # WORKED: nothing here is untried" with three starter balls standing
    # untouched on Oak's table; the model, told the room was finished,
    # reached for a menu that was not there (2026-08-25, leg 1, attempt
    # 1). What is on screen is the only fact available; say that.
    if "None" in str(here) and obs.get("ending"):
        return ("THE HALL OF FAME SEQUENCE IS ON SCREEN — the induction, "
                "then the credits. It is not a menu to close: the harness "
                "presses on through it, and when the save's Hall of Fame "
                "count has risen the game is finished.")
    if "None" in str(here):
        _said = str(obs.get("recent_text") or obs.get("last_text") or "").strip()
        # THE ROWS ON SCREEN ARE ON THE PAGE. At the Celadon roof machine
        # the game window showed FRESH WATER / SODA POP / LEMONADE and
        # this line said only "a box is up, saying: 'Hi there! May I help
        # you?' ... tap b to close it" — and the run closed it, standing
        # on the one thing its next step was for (2026-09-04, user: "the
        # vending machine page is literally just a display of fresh water,
        # lemonade, soda pop"). The rows, numbered as they read, and the op
        # that picks one; which row, if any, is not said.
        _ui = obs.get("ui") or {}
        _rows = [str(r) for r in (_ui.get("rows") or []) if str(r).strip()]
        if _rows:
            _title = str(_ui.get("title") or "").strip()
            return ("THE SCREEN IS NOT THE OVERWORLD RIGHT NOW — a LIST is up"
                    + (f" ({_title})" if _title else "")
                    + (f', under a box saying: "{_said[-120:]}"' if _said else "")
                    + ". Its rows, as they read on screen: "
                    + ", ".join(_rows)
                    + ". {\"op\":\"menu\",\"index\":N} picks row N; "
                      "{\"op\":\"tap\",\"btn\":\"b\"} closes it without "
                      "picking. Where you stand and what is untried cannot "
                      "be read until it closes; which row, if any, is yours.")
        return ("THE SCREEN IS NOT THE OVERWORLD RIGHT NOW"
                + (f' — a box is up, saying: "{_said[-160:]}"' if _said else
                   " — a box, menu or transition is up")
                + ". Where you stand and what is untried cannot be read "
                  "until it closes: answer it if it is asking, or "
                  "{\"op\":\"tap\",\"btn\":\"b\"} to close it.")
    sides = sorted((m.get("connections") or {}).keys())
    been = (getattr(ex, "visits", {}) or {}).get(here, 0)
    head = f"WHERE YOU STAND: {here}"
    # "AND NOWHERE ELSE" IS NOT KNOWN UNDER THE FOOTPRINT. A seam is listed
    # once a cell on that edge has been on screen, so the sides that have
    # never been looked at are simply absent — and Cerulean read "east,
    # north, west and nowhere else" with its south edge row never seen
    # (2026-08-25). Say what was seen, and which sides never were.
    _unseen_sides = [str(x) for x in (m.get("sides_unseen") or [])]
    _unseen_sides = [x for x in _unseen_sides if x not in sides]
    if not sides and not _unseen_sides:
        head += " — " + no_edge_words(m)
    elif not sides:
        head += (" — no edge of this map has been on screen yet ("
                 + ", ".join(_unseen_sides) + " never looked at)")
    else:
        head += (f" — this map has an edge on its {', '.join(sides)} side(s)"
                 + (" that you have seen; its "
                    + ", ".join(_unseen_sides)
                    + " side(s) have never been on screen"
                    if _unseen_sides else " and nowhere else"))
    if been:
        head += f"; you have been in this exact area {been}x"
    # ...AND WHAT THE PRINTED MAP DRAWS FOR THIS MAP, while it is held.
    # (the executor runs as __main__, so its module is found through the
    # executor object, never by the name "executor" — the first cut looked
    # it up by name and the line never rendered)
    try:
        import sys as _sys
        _E = _sys.modules.get(type(ex).__module__)
        if _E is not None and ex._holding_town_map(obs):
            head += printed_roads_words(m.get("id"), sides, _unseen_sides,
                                        getattr(_E, "MAP_EDGES", {}) or {})
    except Exception:
        pass
    # UNSEEN GROUND IS SAID IN THE HEAD LINE, not only at the foot of the
    # page (executor coverage_text): the first-listed thing is taken 54%
    # of the time, and a page that opened "FULLY WORKED" over a floor with
    # a door never on screen sent the run back out the way it came.
    _su = m.get("seen_unreached")
    if isinstance(_su, dict) and int(_su.get("n") or 0) > 0:
        _near = ", ".join(f"({c.get('x')},{c.get('y')})"
                          for c in (_su.get("near") or [])[:3])
        _from = [f for f in (_su.get("from") or []) if f.get("region")]
        head += (f". GROUND YOU HAVE SEEN BUT CANNOT WALK TO FROM HERE: "
                 f"{int(_su['n'])} cell(s), nearest {_near}"
                 + ("; ground you have stood on in "
                    + ", ".join(f"{f['region']} (reaches {f.get('n')} of them)"
                                for f in _from[:2])
                    + " does reach it" if _from else
                    "; no part of this map you have stood in reaches it — "
                    "the way onto it is not known"))
    _fr = m.get("frontier") or []
    if _fr:
        _fn = int(((m.get("seen") or {}).get("frontier_n")) or len(_fr))
        # how far the farthest listed spot is, in walked steps: "6 spots"
        # reads like work, and in a house it is four steps (user,
        # 2026-08-25: "why not check out the full house?")
        _far = max((int(f.get("d") or 0) for f in _fr), default=0)
        head += (f". NOT ALL OF THIS FLOOR HAS BEEN ON SCREEN: the ground "
                 f"you have looked at ends at ({_fr[0].get('x')},"
                 f"{_fr[0].get('y')})"
                 + (f" and {_fn - 1} more spot(s)" if _fn > 1 else "")
                 + (f", the farthest {_far} step(s) from you"
                    if _far and _fn <= len(_fr) else
                    f", the nearest {int(_fr[0].get('d') or 0)} step(s) from you")
                 + "; what is past them is not known")
    # NO "EVERYTHING YOU CAN REACH IS DONE" OVER GROUND NEVER ON SCREEN.
    # Rocket Hideout B4F, elevator side: the page said NOT ALL OF THIS
    # FLOOR HAS BEEN ON SCREEN (15 steps away) and, in the same breath,
    # EVERYTHING YOU CAN REACH HERE IS DONE — and the run rode the lift
    # back up, Giovanni's room a screen north of where its looking ended
    # (user, 2026-08-25: "juuuust missing where giovanni is"). Under the
    # footprint, done is only claimable over what has been on screen.
    # ...AND DONE ON FOOT IS NOT DONE when the water can be ridden: the
    # shim lists the spots across it where seen ground ends (Route 23,
    # 2026-08-28).
    _fw = m.get("frontier_water") or []
    _knows_surf = any(str(mv.get("id") if isinstance(mv, dict) else mv) == "SURF"
                      for mon in (obs.get("party") or [])
                      for mv in (mon.get("moves") or []))
    _done_lead = (". EVERYTHING YOU CAN REACH HERE IS DONE — but " if not _fr and not (_fw and _knows_surf)
                  else (f". Everything you can reach ON FOOT here is done, but the "
                        f"WATER you can ride from here has "
                        f"{int((m.get('seen') or {}).get('frontier_water_n') or len(_fw))} "
                        f"spot(s) where its seen ground ends, the nearest at "
                        f"({_fw[0].get('x')},{_fw[0].get('y')}) — explore rides "
                        f"to the nearest and sweeps from there — and ")
                  if not _fr else ". Everything ON SCREEN here has been worked, and "
                       "ground you can walk to from here has NEVER BEEN ON "
                       "SCREEN (the spot(s) above; explore walks to the "
                       "nearest) — and ")
    _sh = shelf_of(ex, here)
    if _sh:
        if _map_of(here) in (getattr(ex, "_shelf_machine", None) or set()):
            head += (". THE VENDING MACHINE(S) HERE SELL: "
                     + ", ".join(_sh[:10])
                     + " — a machine is not a counter and takes no buy: "
                       "press one and pick a row with "
                       "{\"op\":\"menu\",\"index\":N}")
        else:
            head += f". This mart sells: {', '.join(_sh[:10])}"
    # A LIFT CAR IS NEVER FINISHED, AND IT IS NOT A ROOM. Its panel is the
    # whole point of it: the floors it serves are on the panel, and one of
    # them is where you want to be. Filed as an ordinary room with a sign
    # and one door, it read "FULLY WORKED — nothing new can be found by
    # staying", so the run stepped into Silph's car and straight back out
    # 31 times while its own plan said "go to the 1st floor via the
    # elevator and use the PC". Nothing here says which floor to pick.
    _car = (str((obs.get("map") or {}).get("id") or "").endswith("_ELEVATOR")
            or bool((obs.get("map") or {}).get("lift_floors")))
    if _car:
        head += (". THIS IS A LIFT CAR: the panel on the wall lists the "
                 "floors this lift serves, and riding is "
                 "{\"op\":\"elevator\",\"floor\":\"5F\"} (the label as "
                 "it reads on the panel — 1F, 5F, B4F, ROOF). The door here "
                 "is one doorway; where it opens depends on the floor you "
                 "rode to, so this car is never finished with")
    elif unreached_ways(cands):
        _uw = unreached_ways(cands)
        head += (_done_lead
                 + str(len(_uw)) + " way(s) out of this area have never "
                 "been taken and no walk from here reaches them ("
                 + ", ".join(c.label()
                              + (" — no WALK reaches it, but the water does"
                                 if getattr(c, "by_water", False) else "")
                              for c in _uw[:4])
                 + "), so this area is NOT finished: what is missing is a "
                 "way to where they stand. WHERE THAT WAY STARTS IS NOT "
                 "RECORDED — it may be a corner of this floor you have not "
                 "walked, and it may be another floor entirely")
    elif fully_worked(cands) and [c for c in cands
                                  if c.status == "unreachable"
                                  and c.kind not in ("op", "door", "seam")]:
        # NOT FINISHED WHILE SOMETHING SITS HERE YOU CANNOT REACH. "FULLY
        # WORKED: nothing here is untried or unpressed" was printed on
        # Silph 5F with two never-picked-up items on the floor, both marked
        # "not walkable-to right now" a few lines below it — one of them
        # the CARD KEY the run had spent the whole leg looking for.
        # Unreachable is not pressed. A floor with something on it you
        # cannot get to is not finished; it is a floor you have not found
        # the way into, which is a different thing to do next. How to get
        # in stays the model's.
        _stuck = [c for c in cands if c.status == "unreachable"
                  and c.kind not in ("op", "door", "seam")]
        head += (_done_lead
                 + str(len(_stuck)) + " thing(s) sit on this floor that no "
                 "walk from here reaches ("
                 + ", ".join(c.key for c in _stuck[:4])
                 + "), so this is not finished ground, it is ")
        # ...AND "NOT FOUND THE WAY IN" MUST NOT OUTLIVE ITS TRUTH either.
        # The run rode 7F's pad into 11F's boss pocket, stood beside
        # Giovanni, and this header went on saying "ground you have not
        # found the way into" from the entrance strip — the graph held the
        # walked way while the page denied it existed (user: "does it
        # specifically get something like 'alternate area reached from 7F
        # warp'? only since its already been there of course"). Same
        # recall standard as the interact advice: sighted there, visited
        # there, route walked before — say so; going is still its call.
        _mymap = str(here).split("|")[0]
        _seen_in: dict = {}
        # A THING ALREADY PRESSED OVER THERE IS NOT A REASON TO WALK BACK.
        # On SILPH_CO_11F|1,1 the four unreachable things were the PC, the
        # BEAUTY, the PRESIDENT and ROCKET2 — and of those, only ROCKET2
        # had ever been sighted anywhere the run had walked (in
        # SILPH_CO_11F|9,0), where it had ALREADY been fought. The page
        # still offered "ground you HAVE stood in before ... {"op":"go",
        # "to":"SILPH_CO_11F|9,0"} walks the whole walked route for you",
        # and the run took that route twice, to a room that cannot reach
        # the president, while the one thing that could work — explore,
        # entry 1, toward ground never on screen seven steps away — sat
        # unread (user, 2026-08-26: "its been here twice and used the go
        # command to go to the other part of 11F which CANT reach the
        # door"). A route whose whole payoff is a thing already touched
        # buys nothing; offering it is the harness recommending a walk it
        # has itself already proven spent.
        _tried = getattr(ex, "_tried_objs", {}) or {}
        for _nm in (c.key for c in _stuck):
            for _reg, _names in (getattr(ex, "sightings", {}) or {}).items():
                if (_reg != here and str(_reg).split("|")[0] == _mymap
                        and _nm in (_names or [])
                        and _nm not in (_tried.get(_reg) or set())
                        and int((getattr(ex, "visits", {}) or {})
                                .get(_reg) or 0) > 0):
                    _seen_in.setdefault(_reg, []).append(_nm)
        # ...AND THE ONES NO WALKED GROUND HAS EVER REACHED. The sentence
        # named all four and then answered for one, so "it is ground you
        # HAVE stood in before" read as true of the list. Three of those
        # four had never been reachable from anywhere this run has stood.
        _named = {n for ns in _seen_in.values() for n in ns}
        _nowhere = [c.key for c in _stuck if c.key not in _named]
        if _seen_in:
            _reg = max(_seen_in, key=lambda r: len(_seen_in[r]))
            try:
                _path = ex._route(here, _reg)
            except Exception:
                _path = None
            # A ROUTE WITH ONE HOP DOWN IS STILL A ROUTE YOU WALKED. _route
            # skips hops stamped blocked in THIS world state, which is
            # right, and then this said "no walked route from here is
            # known" — the harness denying its own record. Leg 42's chain
            # out of Seafoam is eight walked hops, and ONE of them
            # (B3F|1,0 --25,14--> B2F|23,10, the swim across B3F) had
            # failed once and carried the stamp; the page told the model it
            # had never found a way there, about ground it had crossed
            # twice that day. `go`'s own refusal has said the honest
            # version all along ("or a hop on it has failed in this world
            # state"). Say which it is: nothing known, or something known
            # that would not land just now.
            _stale = None
            if not _path:
                try:
                    _stale = ex._route(here, _reg, ignore_blocked=True)
                except Exception:
                    _stale = None
            head += ("ground you HAVE stood in before: "
                     + ", ".join(_seen_in[_reg][:4]) + f" are in {_reg}, "
                     "which you have visited "
                     + str(int((getattr(ex, "visits", {}) or {})
                               .get(_reg) or 0)) + "x"
                     + (f" — but {', '.join(_nowhere[:4])} "
                        + ("has" if len(_nowhere) == 1 else "have")
                        + " never been reachable from any ground you have "
                          "stood on, so that route does not answer for "
                        + ("it" if len(_nowhere) == 1 else "them")
                        if _nowhere else ""))
            if _path:
                _k, _dest = _path[0]
                _ks = str(_k)
                _leg = (f"the door at ({_ks})" if _ks[:1].isdigit()
                        else "the lift to " + _ks.split(":", 1)[1]
                        if _ks.startswith("lift:") else f"walk {_ks}")
                # ...AND THE OP THAT WALKS IT WHOLE. Named leg-by-leg, the
                # first leg ended in the lift car, whose panel re-derived
                # "he is on 11F" every visit — the model cannot hold a
                # 4-leg route across rounds, and go already replays walked
                # routes end to end.
                head += (f"; you have walked a route there before: start "
                         f"by taking {_leg} to {_dest} "
                         f"({len(_path)} leg(s) total), or "
                         "{\"op\":\"go\",\"to\":\"" + str(_reg)
                         + "\"} walks the whole walked route for you")
            elif _stale:
                _sk = str(_stale[0][0])
                _sleg = (f"the door at ({_sk})" if _sk[:1].isdigit()
                         else "the lift to " + _sk.split(":", 1)[1]
                         if _sk.startswith("lift:") else f"walk {_sk}")
                head += (f"; you HAVE walked a route there — {len(_stale)} "
                         f"leg(s), starting with {_sleg} to {_stale[0][1]} — "
                         "but a hop on it would not land the last time it "
                         "was tried in this world state, so it is not being "
                         "replayed for you. Walking it a leg at a time is "
                         "still yours to do, and what stopped that hop is "
                         "what has to change")
            else:
                head += ("; no walked route from here is known — how you "
                         "got in before is in your own record")
        else:
            head += "ground you have not found the way into"
    elif fully_worked(cands) and not _fr:
        # "FULLY WORKED" IS ABOUT A REGION AND READS AS A MAP. Route 13's
        # west crossing lands in ROUTE_14|16,6, a four-cell nook, and the
        # page opened "FULLY WORKED: nothing here is untried or unpressed"
        # in the same breath as "its north, south, west side(s) have never
        # been on screen" and "38 cell(s) seen but cannot be walked to"
        # (user, 2026-08-26: "uh oh its in the rt 14 pocket"). Both true;
        # together they say a route nobody has looked at is finished. The
        # frontier branch above already has the honest wording for a floor
        # with unseen ground you can WALK to; a sealed corner has none you
        # can walk to and is exactly as unfinished. Say what is known: this
        # is a corner, and where the rest is entered from is not recorded.
        if _fw and _knows_surf:
            head += (". Nothing here is untried or unpressed ON FOOT, but "
                     "the WATER you can ride from here has "
                     f"{int((m.get('seen') or {}).get('frontier_water_n') or len(_fw))} "
                     f"spot(s) where its seen ground ends, the nearest at "
                     f"({_fw[0].get('x')},{_fw[0].get('y')}) — explore rides "
                     "to the nearest and sweeps from there")
        head += ((". NOTHING HERE IS UNTRIED OR UNPRESSED" if not (_fw and _knows_surf) else "")
                 + (" — and this is a CORNER of "
                    + str((m.get("id") or "this map")) + ": "
                    + (", ".join(_unseen_sides)
                       + " side(s) of it have never been on screen"
                       if _unseen_sides else "part of it cannot be reached "
                                             "from here")
                    + ". Where the rest of this map is entered from is not "
                      "recorded — it may be another cell of the same edge "
                      "you crossed, and it may be another map entirely"
                    if _unseen_sides else "")
                 + ". Staying finds nothing new; leaving for ground that "
                   "still has something is how the search goes on")
    elif switches(cands) and not any(c.status in UNWORKED for c in cands
                                     if c.kind != "op"):
        _sw = switches(cands)
        _shut = [c for c in _sw if c.kind == "shut_door"]
        head += (". Everything here has been pressed at least once, but "
                 + ("the closed doors" if _shut and len(_shut) == len(_sw)
                    else "the fixtures and closed doors" if _shut
                    else "the fixtures")
                 + f" ({', '.join(c.key for c in _sw[:6])}) "
                 "can be pressed AGAIN — a room like this can be a puzzle "
                 "about which, rather than about finding one more thing")
    _holes = m.get("holes") if isinstance(m.get("holes"), list) else []
    if _holes:
        # A HOLE IS NOT IN THE WARP TABLE, so it was in no doorway list and
        # could not be chosen. It is taken by WALKING ONTO IT.
        # ONE DROP CAN BE WIDER THAN ONE CELL: the shim stamps adjacent
        # same-destination drop cells with one group id (drop=N); the
        # tiles of it that have been SEEN fold into one label, the way a
        # two-tile doorway does (user, 2026-08-29: "if there are two on
        # the first floor they should count as one if theyre next to
        # eachother").
        _grp: dict = {}
        for h in _holes:
            _grp.setdefault(h.get("drop") or f"_{h.get('x')},{h.get('y')}",
                            []).append(h)
        _drops = []
        for hs in _grp.values():
            hs = sorted(hs, key=lambda h: (h.get("y") or 0, h.get("x") or 0))
            _drops.append({
                "label": "+".join(f"({h.get('x')},{h.get('y')})" for h in hs),
                "reachable": any(h.get("reachable") for h in hs),
                "boulder": any(h.get("boulder") for h in hs),
                "wide": len(hs), "y": hs[0].get("y") or 0, "x": hs[0].get("x") or 0})
        _drops.sort(key=lambda d: (d["y"], d["x"]))
        _holes = _drops
        _hr = [h for h in _holes if h.get("reachable")]
        _hx = ", ".join(h["label"] for h in _holes[:6])
        # ALL ONE-WAY; TWO PLACEMENTS. The Mansion's drops sit where a
        # doorway would and are exits to another floor (3F's go to 1F and
        # 2F, so "the floor below" was an over-claim); Seafoam's and Victory
        # Road 3F's sit mid-floor and are also the holes a boulder is sent
        # down (user, 2026-08-29). The shim flags the boulder ones from the
        # boulder-hole data; nothing here is keyed on a map name.
        _hb = [h for h in _holes if h.get("boulder")]
        head += (f". THIS FLOOR HAS {len(_holes)} ONE-WAY DROP(S) IN IT, at "
                 f"{_hx}"
                 + (" (a + joins the tiles of ONE drop wider than one cell)"
                    if any(h["wide"] > 1 for h in _holes) else "")
                 + (f" — {len(_hr)} of them you can walk to"
                    if _hr and len(_hr) != len(_holes) else "")
                 + ". A drop is not a doorway and takes no use_warp: you "
                 "step ONTO it and are taken to another floor, and there is "
                 "no climbing back up it. {\"op\":\"walk_to\",\"x\":N,"
                 "\"y\":N} onto one is how it is taken"
                 + ((". " + ", ".join(h["label"] for h in _hb[:4])
                     + (" is" if len(_hb) == 1 else " are")
                     + " also a HOLE in the floor a BOULDER can be sent "
                       "down"
                     + (" — the rest are exits like a doorway you cannot "
                        "come back through"
                        if len(_hb) < len(_holes) else ""))
                    if _hb else
                    " — an exit like a doorway you cannot come back through"))
    _w = (m.get("water") or {}) if isinstance(m.get("water"), dict) else {}
    if _w.get("cells"):
        _knows = any("SURF" in [str(x.get("id") if isinstance(x, dict) else x)
                                for x in (mon.get("moves") or [])]
                     for mon in (obs.get("party") or []))
        head += (f". THIS FLOOR HAS WATER: {_w['cells']} cell(s)")
        if _w.get("mount_x") is not None:
            head += (f", and ground you can reach touches it at "
                     f"({_w['mount_x']},{_w['mount_y']})")
        else:
            head += (f", the nearest at ({_w.get('x')},{_w.get('y')}), but "
                     f"no ground you can reach touches any of it")
        head += (". A walk will not cross water"
                 + (" — but a party Pokemon knows SURF: {\"op\":"
                    "\"field_move\",\"move\":\"SURF\",\"x\":N,"
                    "\"y\":N} beside a water tile steps onto it, and from "
                    "the water, water is walkable; walk_to and cross also "
                    "take surf=true"
                    if _knows else "; nobody in the party knows SURF"))
    # ...AND WHETHER THIS FLOOR'S WATER STAYS PUT. Seafoam's currents
    # carry a rider along a scripted sweep, and B4F's pool edge bumps one
    # straight back off the two doors at (20,17)/(21,17) — so every list
    # called those doors reachable, use_warp answered "no path", and the
    # run aimed at them sixteen times in one subgoal. The engine's own
    # current table says which cells do it; that they stop doing it once
    # the plug boulders are down is the game's business, not ours to
    # point at.
    # A STATUE YOU CAN PRESS IS ON THE SCREEN AND WAS IN NO LIST. The
    # Mansion's doors are opened by pressing one while FACING UP, the Super
    # Nerd says so out loud, and the page carried objects and signs — which
    # a switch statue is neither. The run read the hint, said "switches
    # toggle sets of doors" for a whole leg, and had nothing to press.
    # Where they are is on the screen; which to press, and when, stays the
    # model's — a room with switches is never "finished", which this
    # ledger has said for a long time about switches it could not see.
    # A SWITCH IN THE FLOOR IS NOT A STATUE: nothing presses it, a BOULDER
    # has to come and sit on it. Said here for the same reason the statues
    # are — it is on the screen and was in no list — and the barrier it
    # opens is said with it, because a player watches that wall go.
    _bsw = m.get("boulder_switches") or []
    if _bsw:
        def _one_bsw(c):
            _at = f"({c['x']},{c['y']})"
            _op = ("" if c.get("opens_x") is None else
                   f", which opens the way at ({c['opens_x']},{c['opens_y']})"
                   + ("" if c.get("open_now") is None else
                      " — THAT WAY IS OPEN RIGHT NOW" if c["open_now"]
                      else " — that way is SHUT right now"))
            if c.get("held"):
                return _at + _op + " — a BOULDER IS ON IT NOW"
            # WHETHER *YOU* CAN STAND THERE IS THE WRONG TEST. A boulder
            # has to arrive on it; you never do. Saying "no walk from here
            # reaches that cell" about a switch reads as "this one is out
            # of play" and sends the run looking elsewhere, when the only
            # question is whether some sequence of shoves gets a boulder
            # there — which push to_x/to_y answers for real.
            return (_at + _op
                    + ("" if c.get("reachable") else
                       " — no walk from here reaches that cell, which does "
                       "not matter: it is the BOULDER that has to end up "
                       "on it, not you"))
        head += (f". THIS FLOOR HAS {len(_bsw)} SWITCH(ES) IN THE FLOOR: "
                 + ", ".join(_one_bsw(c) for c in _bsw[:6])
                 + ". Nothing presses one: a BOULDER has to be shoved onto "
                   "it. WHAT HAPPENS THEN IS NOT 'IT STAYS OPEN WHILE THE "
                   "BOULDER SITS THERE' — that is what this line used to "
                   "say and it is not what the game does: the moment the "
                   "boulder lands, something is SET, and the way stays open "
                   "after the boulder has gone (VICTORY_ROAD_1F, measured "
                   "2026-08-24: the barrier opened, the floor reloaded, the "
                   "boulders were back where they started and the way was "
                   "still open). What UNSETS it again, if anything, is not "
                   "recorded here. NAME THE CELL IT SHOULD END UP ON and the "
                   "shoving is worked out for you: {\"op\":\"push\","
                   "\"x\":N,\"y\":N,\"to_x\":N,\"to_y\":N} — which "
                   "side to stand on for each shove and in what order, and "
                   "it answers plainly if no sequence of shoves can get it "
                   "there. STRENGTH has to be on for this map first. WHICH "
                   "boulder, and where, is yours")
    # ...AND WHERE THEY WERE WHEN YOU WALKED IN. A shove cannot be undone,
    # and a boulder parked in the wrong cell can make a floor unsolvable —
    # so what the floor looked like on arrival is the one fact that says
    # whether that is recoverable.
    _now_rocks = sorted(f"{o.get('x')},{o.get('y')}"
                        for o in (m.get("objects") or [])
                        if isinstance(o, dict) and o.get("kind") == "boulder")
    _was_rocks = list((getattr(ex, "boulder_start", None) or {})
                      .get(str(m.get("id") or "")) or [])
    if _now_rocks and _was_rocks and _now_rocks != _was_rocks:
        head += (". THE BOULDERS HERE HAVE MOVED SINCE YOU WALKED IN: they "
                 "were at " + ", ".join(f"({c})" for c in _was_rocks[:6])
                 + " and they are at "
                 + ", ".join(f"({c})" for c in _now_rocks[:6])
                 + " now. A shove cannot be taken back, and this floor put "
                   "them back where they started the last time you walked "
                   "onto it")
    _bh = m.get("boulder_holes") or []
    if _bh:
        head += (". A BOULDER CAN BE SENT DOWN A HOLE ON THIS FLOOR: "
                 + ", ".join(f"({c['x']},{c['y']})" for c in _bh[:4])
                 + ". Shove one onto it and it goes down to the floor "
                   "below — the same hole you would fall through yourself. "
                   "Where it lands, and whether that is any use, is not "
                   "recorded here")
    _sw = m.get("switch_statues") or []
    if _sw:
        # REACHABLE MEANS THE CELL YOU PRESS FROM. The statue itself is a
        # solid tile, so it is never in the walkable component and the old
        # test called every statue on every floor unreachable — printed
        # one clause after telling the model to walk below it and press.
        # It read that and left the Mansion floor by floor.
        _reach = [c for c in _sw if c.get("reachable")]

        # EVERY STATUE GETS ITS OWN OP, and the reachable ones come first.
        # The op form was minted from _sw[0] alone, and on POKEMON_MANSION_
        # B1F that is (20,3) — whose press cell no walk reaches. So the one
        # runnable line on the page aimed at the statue the party CANNOT
        # use, while (18,25), three cells from where it stood, was named
        # and left without an op; the run sent interact at (18,26), the
        # cell it stands on, and went back to hunting for stairs (user,
        # watching, 2026-08-23: "its obsessed with getting to the
        # second/third floors when its already where it needs to be in the
        # basement it just needs to recognize and flip the second statues
        # lock").
        _sw = sorted(_sw, key=lambda c: (0 if c.get("reachable") else 1,
                                         c.get("y") or 0, c.get("x") or 0))

        def _one(c):
            if c.get("press_x") is None:
                return f"({c['x']},{c['y']})"
            return (f"({c['x']},{c['y']}), pressed from "
                    f"({c['press_x']},{c['press_y']})"
                    + ('{"op":"interact","x":%d,"y":%d,"answer":"yes"}'
                       % (c["x"], c["y"])).join((" with ", ""))
                    + ("" if c.get("reachable") else " — BUT NO WALK FROM "
                       "WHERE YOU STAND REACHES THAT PRESS CELL RIGHT NOW"))

        head += (f". THIS FLOOR HAS {len(_sw)} SWITCH STATUE(S): "
                 + ", ".join(_one(c) for c in _sw[:6])
                 + (f" (+{len(_sw) - 6} more)" if len(_sw) > 6 else "")
                 + ". A switch is PRESSED, and only while you are FACING "
                   "UP at it, which is why the cell below it is the one "
                   "that has to be walkable. The statue's own cell is "
                   "SOLID — drawn S, never stood on. AN INTERACT NAMES "
                   "THE TILE YOU PRESS A AT, NEVER THE TILE YOU STAND ON, "
                   "and it walks and faces you itself — each op above "
                   "presses the statue beside it. What "
                   "it changes is elsewhere on this floor or another"
                 # ...AND WHETHER PRESSING IT AGAIN CAN STILL ANSWER
                 # ANYTHING HERE. This paragraph hands the model a
                 # ready-to-run op, and it is the only one the header
                 # offers on a floor that is otherwise "done" — so it kept
                 # being sent, long after both settings had been looked at
                 # for every way out of this floor. That fact lived far
                 # down the page beside the doors; say it where the op is.
                 + (_spent_both_note(obs, ex))
                 + (". THEY ALL SHARE ONE SETTING, which is currently "
                    + ("PRESSED" if m.get("switches_on") else "UNPRESSED")
                    + " — pressing ANY of them flips that one setting for "
                      "every floor, so pressing a second one puts the "
                      "first back"
                    if m.get("switches_on") is not None else "")
                 + ("" if _reach else
                    " — no statue on this floor has a press cell you can "
                    "walk to from where you stand right now"))
    _cur = (m.get("currents") or {}) if isinstance(m.get("currents"), dict) \
        else {}
    _pushed, _carried = _cur.get("pushed") or [], _cur.get("carried") or []
    if _pushed or _carried:
        head += ". THIS FLOOR'S WATER MOVES YOU"
        if _carried:
            head += (": riding onto "
                     + ", ".join(f"({c['x']},{c['y']})" for c in _carried[:6])
                     + (" and more" if len(_carried) > 6 else "")
                     + " sweeps you off along the current")
        if _pushed:
            head += ((", and " if _carried else ": ")
                     + ", ".join(f"({c['x']},{c['y']})" for c in _pushed[:6])
                     + (" and more" if len(_pushed) > 6 else "")
                     + " pushes you straight back the way you came, so you "
                     "cannot stand there while you are riding")
    # THIS FLOOR HAS ANOTHER PART YOU HAVE WALKED. The page tells you about
    # other MAPS with unfinished ground and about things sighted elsewhere,
    # and never once about the rest of the floor under your feet. Standing
    # in SEAFOAM_ISLANDS_1F|3,2 the ledger HELD 1F|21,12 — stood in 3x,
    # whose door the run had taken twice onto the far shore of Route 20 —
    # and said nothing, so every round re-derived the idea from the map and
    # lost it at the next load (user, watching it: "it has the right idea
    # but doesnt move from there, or worse, it leaves and forgets until it
    # notices the east side leads west"). Recall of walked ground is ours
    # to execute; where those doors go is the run's OWN record, the same
    # rule this floor's own exits already follow. Which of them is worth
    # the walk stays the model's.
    _mymap2 = str(here).split("|")[0]
    _kin = []
    for _r3, _ex3 in sorted((getattr(ex, "explored", {}) or {}).items()):
        if _r3 == here or str(_r3).split("|")[0] != _mymap2 or not _ex3:
            continue
        _went = sorted({str(_e3.get("to")) for _e3 in _ex3.values()
                        if (_e3 or {}).get("to")
                        and str(_e3.get("to")) != _r3}
                       )
        if not _went:
            continue
        _kin.append((_r3,
                     int((getattr(ex, "visits", {}) or {}).get(_r3) or 0),
                     _went))
    if _kin:
        _bits = []
        for _r3, _v3, _went in _kin[:3]:
            _bits.append(f"{_r3}" + (f", stood in {_v3}x" if _v3 else "")
                         + ", whose ways out you have taken led to "
                         + ", ".join(_went[:3]))
        head += (". THIS FLOOR HAS ANOTHER PART YOU HAVE WALKED: "
                 + "; ".join(_bits)
                 + (f" (and {len(_kin) - 3} more)" if len(_kin) > 3 else "")
                 # GO DOES NOT LEVITATE. This said "no walk from here
                 # need reach it", which is true of the DESTINATION and
                 # false of the route's first door — go's first move is a
                 # walk to that door. The run read the two sentences
                 # together and drew the conclusion we had written for it:
                 # "because i cannot walk from here ill use the go
                 # command" (user, 2026-08-23), sending go into 1F's
                 # sealed half round after round.
                 + ". You need no walk from here to the PLACE — "
                 "{\"op\":\"go\",\"to\":\"AREA\"} replays a route "
                 "you have walked. But its first move is a WALK to the "
                 "first door of that route, so it can only start if a "
                 "walk from where you stand reaches THAT door")
    lines = [head + "."]
    # EXITS ARE NEVER CUT. The cap is for the long tail of things and
    # people; a door or a seam is a way out and every one is shown.
    exits = [c for c in cands if c.kind in ("door", "seam", "op")]
    rest = [c for c in cands if c.kind not in ("door", "seam", "op")]
    # A CROWD IS FOLDED BEFORE THE PAGE IS CUT, or the fold saves nothing.
    # The Game Corner's thirty-six slot machines filled the cap and pushed
    # every person in the room off the end — "…and 28 more thing(s) not
    # shown: … 10 unspoken", the Rocket standing in front of the way down
    # among them. Counted as one entry, the room fits.
    _mob: dict = {}
    for c in rest:
        if c.kind == "fixture" and c.status == "untouched":
            _mob.setdefault(_stem(c.key), []).append(c)
    _mob = {k: v for k, v in _mob.items() if len(v) > 3}
    _folded, _first = [], set()
    for c in rest:
        _st = _stem(c.key)
        if c.kind == "fixture" and _st in _mob and c.status == "untouched":
            if _st in _first:
                continue
            _first.add(_st)
        _folded.append(c)
    keep = _folded[:max(0, limit - len(exits))]
    shown = [c for c in cands if c in exits or c in keep]
    # ONE LINE FOR THE WEAK LEADS. Things pressed before the world moved
    # are the same fact eleven times over in a town square; they keep
    # their entries (lookup still finds each) but read as one line at the
    # rank of the first, names listed, so they cannot bury the doors.
    weak = [c for c in shown if c.status == "worth_a_word"]
    weak_done = False
    # ...AND ONE LINE FOR A CROWD OF THE SAME THING. Same rule as the weak
    # leads, for the other way a page gets buried: the Rocket Game Corner
    # has thirty-six slot machines and the ledger spent lines 2 through 22
    # on them, cut the page at the limit, and ended "…and 28 more thing(s)
    # not shown: … 10 unspoken" — every person in the room, including the
    # Rocket who is standing in front of the way down, off the page behind
    # a wall of furniture (user: "its only looking at the slot machines
    # instead of talking to anyone"). They keep their entries and lookup
    # still finds each; they read as one line at the rank of the first,
    # which is all thirty-six of them are worth saying.
    i = 0
    for c in shown:
        _herd = (_mob.get(_stem(c.key))
                 if (c.kind == "fixture" and c.status == "untouched")
                 else None)
        if _herd:
            i += 1
            _names = ", ".join(x.key for x in _herd[:4])
            lines.append(
                f" {i}. {len(_herd)} x {_stem(c.key).rstrip('_')} "
                f"({_herd[0].kind}) — none of them pressed; they are the "
                f"same thing over and over, so whatever one of them does, "
                f"all of them do: {_names}"
                + (f" and {len(_herd) - 4} more" if len(_herd) > 4 else ""))
            continue
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
        _st = c.status
        if _st == "sealed" and not c.n:
            _st = "sealed_untried"
        words = _STATUS_WORDS.get(_st, _st).format(n=c.n)
        # A WAY THAT HAS REFUSED YOU IS NOT "NEVER TAKEN". The status stays
        # "untried" because the crossing never completed, but printing
        # "never taken from here" beside its own FAILED note called a
        # proven wall fresh ground — and the closing line then blessed it
        # as one of the only entries that could find anything new here.
        if c.status == "untried" and c.kind in ("door", "seam") \
                and _refused(c):
            words = "never crossed — trying it has turned you back before"
        elif (c.status == "untried" and c.kind in ("door", "seam")
                and "cannot be reached over the ground" in str(c.note or "")):
            words = ("never taken from here — no walk over ground you have "
                     "SEEN has reached it yet; ground never on screen may "
                     "join it (explore looks there)")
        # ...AND UNREACHABLE IS ONLY EVER TRUE OF A SETTING, where the
        # world has a lever that puts the walls back. The run had already
        # looked at this door in both statue settings and been turned away
        # by both; the line said only "you cannot walk to it from where
        # you stand", so every cycle read as new and six subgoals went
        # round the same circuit (2026-08-23).
        if c.status == "unreachable" and c.kind in ("door", "seam"):
            _seen_in = []
            try:
                # keyed by REGION (this part of the floor) since 2026-08-28;
                # an older map-keyed entry is still read, as it was written
                _ss_all = getattr(ex, "shut_settings", None) or {}
                _mid_now = str((obs.get("map") or {}).get("id") or "")
                _seen_in = list((_ss_all.get(here) or {}).get(c.key)
                                or (_ss_all.get(_mid_now) or {}).get(c.key)
                                or [])
            except Exception:
                _seen_in = []
            if len(_seen_in) > 1:
                words += (" — and you have looked at it with the statues "
                          "PRESSED and with them UNPRESSED, and no walk "
                          "reached it either way")
            elif _seen_in:
                words += (" — looked at only with the statues "
                          + _seen_in[0].upper()
                          + "; the other setting has never been tried "
                            "from here")
        if c.status == "unreachable" and c.kind not in ("door", "seam"):
            words += _reached_before(obs, ex, c.key)
        if _asking(c):
            words += (" — and it is WAITING ON YOUR ANSWER: it asked, the "
                      "box is still open, and pressing it again only asks "
                      "the same question. Answer it with {\"op\":\"menu\","
                      "\"index\":1} for YES or 2 for NO")
        if getattr(c, "spoke", ""):
            words += (" — trying it said: \"" + str(c.spoke)[:120] + "\"")
        # ONLY A TOGGLE IS "PRESSABLE AGAIN". The line was written for the
        # Mansion's statue switches and it invited re-pressing Blaine's
        # quiz machines, which answer once (2026-08-28).
        if c.kind == "fixture" and c.status in ("touched", "inert", "worth_a_word") \
                and str(c.key).upper().startswith(("SWITCH", "TRASH_CAN")):
            words += " — a fixture; it can be pressed again"
        if c.kind == "shut_door" and c.status in ("touched", "inert",
                                                  "worth_a_word"):
            words += (" — IT IS STILL DRAWN SHUT, so nothing pressed at it "
                      "has opened it yet; a door answers differently once "
                      "the world has moved, and pressing it again is how "
                      "you find out")
        # AN ITEM IS FREE STUFF. Renamed to ITEM_x_y (its contents are not
        # on the screen), "never pressed" undersells it: it is a thing lying
        # on the ground that pressing A picks up, at no cost. Say that.
        # A SHUT DOOR IS FURNITURE, NOT SCENERY. It is drawn closed on the
        # screen; what pressing it does is the game's own conversation.
        # A HOLE IS ONE-WAY AND THE LIST NEVER SAID SO. The blocker text
        # says it when a hole happens to sit beside a thing ("you drop to
        # the floor below and cannot climb back up it"); the doorways
        # list, which is where the choice is actually made, called it a
        # hole and stopped. A player sees the drop; the model was told a
        # label (user, 2026-08-23: "it doesnt see them correctly").
        if getattr(c, "by_water", False) and c.status == "unreachable":
            words = ("no walk from here reaches it, but the WATER does: a "
                     "party Pokemon knows SURF, and from the water, water "
                     "is walkable")
        if c.kind == "door" and getattr(c, "look", "") == "hole":
            words = ("a HOLE in the floor: stepping on it DROPS you to the "
                     "floor below and there is no climbing back up it, so "
                     "it is a way DOWN and never a way back — " + words)
        if c.kind == "shut_door" and c.status in ("untouched", "touched",
                                                  "inert", "worth_a_word"):
            # A SHUTTER IS ONE DOOR AND IT IS WIDE. The shim now mints it
            # once at its first tile and carries the rest, the same
            # convention an ordinary two-tile doorway has used since
            # 2026-08-25 — say the width for the same reason: so the tiles
            # the model can see on screen are not read as separate doors it
            # has failed to find.
            _tw = [t for t in (getattr(c, "twins", None) or []) if t]
            words = ("a CLOSED DOOR, drawn shut across the way"
                     + (f" — ONE shutter, {len(_tw) + 1} tiles wide, also "
                        f"at {', '.join(str(t) for t in _tw)}" if _tw else "")
                     + " — "
                     + _STATUS_WORDS.get(
                         "sealed_untried" if (c.status == "sealed"
                                              and not c.n) else c.status,
                         c.status).format(n=c.n))
        if c.kind == "item" and c.status == "untouched":
            # ...AND "CANNOT WALK TO" MUST NOT OUTLIVE ITS TRUTH. Since the
            # pad recall (2026-08-22), a press at an unwalkable item is
            # answered by riding pads the run has already ridden onto its
            # map and pressing again from where they set you down — so the
            # old bare verdict ("an item you cannot walk to right now")
            # told the model the press was wasted, and it walked past the
            # Card Key twice on the strength of our own stale words. Say
            # the ops contract instead; which pad, if any, stays unsaid.
            # ...UNLESS THE BAG IS FULL, in which case pressing it takes
            # NOTHING. gen 1 answers "No more room for items!" and leaves
            # the ball where it is. This line said "pressing A takes it and
            # it costs nothing" and then quoted that refusal three words
            # later, in one breath — the same shape as the statue line that
            # said walk below it and then that it could not be walked to.
            # Two balls on the Mansion's B1F, one of them the Secret Key,
            # were pressed and re-pressed against a 20-of-20 bag
            # (2026-08-23).
            _bagfull = len((obs.get("bag") or {})) >= 20
            words = ("lying on the ground, never picked up — "
                     + ("the BAG IS FULL (20 of 20 kinds), so pressing it "
                        "now takes NOTHING and answers \"No more room for "
                        "items!\" — a slot has to be free FIRST"
                        if _bagfull else
                        "pressing A takes it and it costs nothing")
                     + ("" if c.reachable else
                        _reached_before(obs, ex, c.key)
                        + "; not walkable-to right now, but pressing it is "
                        "still WORTH SENDING — if a pad or door you have "
                        "ridden before arrives on this map, the press "
                        "rides it again and tries from where it sets "
                        "you down"))
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
        kind = ("" if c.kind in ("door", "seam", "frontier") else
                f" ({c.kind}" + (f" at {c.x},{c.y}" if c.x is not None
                                 else "") + ")")
        note = ""
        if c.note:
            n = c.note.strip()
            # THE WORD "FAILED" IS IN THE NOTE, NOT IN `words` — keying
            # the wider budget off `words` meant only notes that happened
            # to carry the stop-clause escaped the ellipsis, and Route 6's
            # north seam still rendered as "walked 432…" with every reason
            # cut off. Any failure note gets the room.
            # AN OP EXAMPLE CUT IN HALF IS WORSE THAN NO EXAMPLE. The
            # lift-car note came through as {"op":"elevator","floor":"5…
            # — unusable, and it is the one line telling the model it need
            # not walk in and out of a car by hand.
            _fail = ("FAILED" in n or "cannot be walked to" in n
                     or "no walkable path" in n or "FAILED" in words
                     or '{"op"' in n)
            _cap = FAIL_CHARS if (_STOP_MARK in n or _fail) else NOTE_CHARS
            if len(n) > _cap:
                if _STOP_MARK in n:
                    _head, _stop = n.split(_STOP_MARK, 1)
                    # what stopped you, whole; the crowd standing near the
                    # edge but not in the way can go
                    _stop = _stop.split("Also near", 1)[0].strip(" .;")
                    _head = _head.strip()
                    if len(_head) > _cap // 2:
                        _head = _head[:_cap // 2 - 1] + "…"
                    n = f"{_head} {_STOP_MARK} {_stop}."
                else:
                    n = n[:_cap - 1] + "…"
            note = f" — {n}"
        # what lies beyond is never cut: it is the fact the ideal turns on
        if c.beyond:
            note += f" — {c.beyond}"
        lines.append(f" {i}. {c.label()}{kind}{arrow} — {words}{note}")
    # a crowd folded into one line is SHOWN, not cut — counting its
    # members here would contradict the line that just named them
    cut = [c for c in _folded if c not in keep]
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
