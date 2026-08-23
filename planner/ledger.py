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
    "untouched": 0,     # a thing / person here never pressed
    "unspoken": 0,      # a person here never spoken to (alias of untouched)
    "reopened": 1,      # a shut door, now that the world has moved
    "taken": 2,         # walked before; count and destination known
    "lift_door": 2,     # a car's doorway: never fresh, never a discovery
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
    twins: list = field(default_factory=list)
                                 # doors: the other tiles of this doorway —
                                 # a doorway spans up to four warp tiles
                                 # and is ONE door (_door_groups)

    def label(self) -> str:
        if self.kind == "seam":
            return f"walk {self.key}"
        if self.kind == "door":
            _l = getattr(self, "look", "door") or "door"
            _tw = "".join(f"+({t})"
                          for t in (getattr(self, "twins", None) or []))
            if _l == "pad":
                return f"warp pad ({self.key}){_tw}"
            if _l == "hole":
                return f"hole ({self.key}){_tw}"
            if _l == "stairs":
                return f"stairs/ladder ({self.key}){_tw}"
            if _l == "threshold":        # an older shim's word for a door
                return f"door ({self.key}){_tw}"
            return f"door ({self.key}){_tw}"
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
    parts = []
    if left:
        parts.append(f"{len(left)} exit(s) never taken")
    if things:
        parts.append(f"{len(things)} thing(s) never pressed "
                     f"({', '.join(things[:3])})")
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
        return f"{dest} sells: {', '.join(_shelf[:8])}"
    parts = _left_parts(ex, dest)
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
            if p2:
                found = (nxt, n + 1, p2)
                break
            q.append((nxt, n + 1))
    worked = dest in worked_regions(ex, target)
    if found:
        nxt, n, p2 = found
        return ((f"{dest} is fully worked itself" if worked
                 else f"{dest} has nothing untried itself")
                + f", but {n} more leg(s) on through it {nxt} still has "
                + " and ".join(p2))
    if worked:
        return (f"{dest} is fully worked and so is everything you have "
                f"walked beyond it — nothing new that way as far as you "
                f"have walked")
    return ""


UNWORKED = ("untried", "untouched", "unspoken", "reopened", "cuttable",
            "pushable")


def switches(cands: list) -> list:
    """Reachable fixtures other than a PC: pressable AGAIN by nature. The
    Vermilion gym's cans re-randomise on a miss and pressing again is the
    only way through; a PC is a service with its own ops."""
    return [c for c in cands if c.kind == "fixture" and c.key != "PC"
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
    return not any(c.status in UNWORKED for c in cands if c.kind != "op")


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
                _pass += ("\nTHIS MAP HOLDS MORE THAN ONE ROOM: the door(s) "
                          + _others + " are on it but not reachable from "
                          "where you stand — walls, not obstacles. A room "
                          "you cannot walk to from inside the same building "
                          "is entered by its OWN door from outside.")
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
        c.rank = (_bucket, not c.reachable, STATUS_RANK.get(c.status, 9),
                  1 if _refused(c) else 0,
                  0 if c.kind in _goal_kinds else 1, into_seen,
                  c.n, c.kind, c.key)
    out.sort(key=lambda c: c.rank)

    # ---- explore ------------------------------------------------------
    if want_explore:
        out.insert(0, Candidate(key="explore", kind="op", status="op",
                                note=plan_explore(ex, obs, out,
                                                  target=target)))
    return out


def _refused(c) -> bool:
    """Has this candidate turned the run back? The status cannot say: a
    crossing that failed never completed, so it stays "untried"."""
    n = str(getattr(c, "note", "") or "")
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
        found.append((r, region, left, things, path))
    found.sort(key=lambda f: f[0])
    best = found[0] if found else None
    if best:
        _, region, left, things, path = best
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
        _more, _legs_seen = [], {path[0][0]}
        for _r2, _reg2, _left2, _things2, _path2 in found[1:]:
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
    "reopened": "turned you back once, but the world has moved since",
    "taken": "taken {n}x",
    "came_in_by": "the door you came in by; taken {n}x",
    "spent": "reached for {n}x and never once got through",
    "shut": "SHUT — walked into {n}x and turned back every time",
    "sealed": "proven uncrossable from this area",
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
    "recut": "a bush you have CUT before, grown back (every bush regrows "
             "when the game reloads) — cutting it reopens the SAME way it "
             "opened before, not new ground",
    "bush": "a bush — CUT clears it; nobody in the party knows CUT yet",
    # the braces are doubled because this table is .format()ed for {n}
    "pushable": "a BOULDER — it is pushed, not pressed, and a party Pokemon "
                "knows STRENGTH. Switch STRENGTH on from the party menu "
                "first ({{\"op\":\"field_move\",\"move\":\"STRENGTH\"}})"
                " — the game turns it off again on every map load — then "
                "push with {{\"op\":\"push\",\"x\":N,\"y\":N,"
                "\"dir\":\"up|down|left|right\"}}",
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
        head += (". EVERYTHING YOU CAN REACH HERE IS DONE — but "
                 + str(len(_uw)) + " way(s) out of this area have never "
                 "been taken and no walk from here reaches them ("
                 + ", ".join(c.label()
                              + (" — no WALK reaches it, but the water does"
                                 if getattr(c, "by_water", False) else "")
                              for c in _uw[:4])
                 + "), so this area is NOT finished: what is missing is a "
                 "way to where they stand, and that is on this same floor")
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
        head += (". EVERYTHING YOU CAN REACH HERE IS DONE — but "
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
        for _nm in (c.key for c in _stuck):
            for _reg, _names in (getattr(ex, "sightings", {}) or {}).items():
                if (_reg != here and str(_reg).split("|")[0] == _mymap
                        and _nm in (_names or [])
                        and int((getattr(ex, "visits", {}) or {})
                                .get(_reg) or 0) > 0):
                    _seen_in.setdefault(_reg, []).append(_nm)
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
                               .get(_reg) or 0)) + "x")
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
    elif fully_worked(cands):
        head += (". FULLY WORKED: nothing here is untried or unpressed — "
                 "staying finds nothing new; leaving for ground that still "
                 "has something is how the search goes on")
    elif switches(cands) and not any(c.status in UNWORKED for c in cands
                                     if c.kind != "op"):
        head += (". Everything here has been pressed at least once, but "
                 f"the fixtures ({', '.join(c.key for c in switches(cands)[:6])}) "
                 "can be pressed AGAIN — a room like this can be a puzzle "
                 "about which, rather than about finding one more thing")
    _holes = m.get("holes") if isinstance(m.get("holes"), list) else []
    if _holes:
        # A HOLE IS NOT IN THE WARP TABLE, so it was in no doorway list and
        # could not be chosen. It is taken by WALKING ONTO IT.
        _hr = [h for h in _holes if h.get("reachable")]
        _hx = ", ".join(f"({h.get('x')},{h.get('y')})" for h in _holes[:6])
        head += (f". THIS FLOOR HAS {len(_holes)} HOLE(S) IN IT, at {_hx}"
                 + (f" — {len(_hr)} of them you can walk to"
                    if _hr and len(_hr) != len(_holes) else "")
                 + ". A hole is not a doorway and takes no use_warp: you "
                 "step ONTO it and DROP to the floor below, and there is no "
                 "climbing back up it. {\"op\":\"walk_to\",\"x\":N,"
                 "\"y\":N} onto one is how it is taken")
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
        words = _STATUS_WORDS.get(c.status, c.status).format(n=c.n)
        # A WAY THAT HAS REFUSED YOU IS NOT "NEVER TAKEN". The status stays
        # "untried" because the crossing never completed, but printing
        # "never taken from here" beside its own FAILED note called a
        # proven wall fresh ground — and the closing line then blessed it
        # as one of the only entries that could find anything new here.
        if c.status == "untried" and c.kind in ("door", "seam") \
                and _refused(c):
            words = "never crossed — trying it has turned you back before"
        if c.kind == "fixture" and c.key != "PC" and c.status in (
                "touched", "inert", "worth_a_word"):
            words += " — a fixture; it can be pressed again"
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
            words = ("a CLOSED DOOR, drawn shut across the way — "
                     + _STATUS_WORDS.get(c.status, c.status).format(n=c.n))
        if c.kind == "item" and c.status == "untouched":
            # ...AND "CANNOT WALK TO" MUST NOT OUTLIVE ITS TRUTH. Since the
            # pad recall (2026-08-22), a press at an unwalkable item is
            # answered by riding pads the run has already ridden onto its
            # map and pressing again from where they set you down — so the
            # old bare verdict ("an item you cannot walk to right now")
            # told the model the press was wasted, and it walked past the
            # Card Key twice on the strength of our own stale words. Say
            # the ops contract instead; which pad, if any, stays unsaid.
            words = ("lying on the ground, never picked up — pressing A "
                     "takes it and it costs nothing"
                     + ("" if c.reachable else
                        "; not walkable-to right now, but pressing it is "
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
        kind = ("" if c.kind in ("door", "seam") else
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
