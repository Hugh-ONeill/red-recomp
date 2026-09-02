#!/usr/bin/env python3
"""Move an outline leg LATER, when it is right but not yet.

The inverse of pull_leg, and the commoner case. An outline's ordering
errors are overwhelmingly TOO EARLY — a model writing a playthrough puts
down what it knows about when it thinks of it — and until now the ladder
had four ways to say "something else first" and no way to say "this, but
later". Watched live: "the party holds a WATER or GRASS type" placed
before Vermilion, where wild water Pokemon need a rod nobody has yet; the
Master Ball at position 3; "Defeat Giovanni for the Earth Badge" at 19.
The first of those was dropped for good by the upkeep rule, which saved
the chain and lost the objective. Deferring it is the better answer.

Recorded by TEXT as well as position (run/outline_pushes,
"from<TAB>after<TAB>text"), same as pull_leg and for the same reason:
positions shift under the sweep and the insert rung, and the text is what
survives.

Usage: push_leg.py <from> <after>     # move leg <from> to sit after <after>
"""
import sys
from pathlib import Path

OUT = Path("plans/outline.txt")
PUSHES = Path("run/outline_pushes")


def read_outline() -> list:
    return [l for l in OUT.read_text().splitlines() if l.strip()]


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: push_leg.py <from> <after>")
    try:
        frm, after = int(argv[0]), int(argv[1])
    except ValueError:
        sys.exit("push_leg: both arguments are outline positions")
    lines = read_outline()
    n = len(lines)
    if not 1 <= frm <= n:
        sys.exit(f"push_leg: {frm} is off the list of {n}")
    # LATER MEANS LATER. A push that lands at or before where the leg
    # already sits is not a deferral, it is a no-op or a pull wearing the
    # wrong name, and the chain would re-run the same leg immediately.
    if after <= frm:
        sys.exit(f"push_leg: {after} is not after {frm}")
    # A PREREQUISITE MAY NOT BE PUSHED PAST WHAT IT UNBLOCKS. The blocker
    # rung inserted "Clear Rock Tunnel" before "Reach Lavender Town"
    # because Route 12 is shut by the Snorlax; authoring the tunnel leg
    # then failed, the failure pushed it two places on — past Lavender —
    # and the run went straight back to the Vermilion/Route 12 loop the
    # insert existed to break (2026-08-29, user: "its not clearing rock
    # tunnel, its just doing the same verm to rt12 pingponging"). The
    # inserts ledger says what each insert was FOR; a push that would
    # cross that leg is refused, and the caller falls through to the
    # ladder (which may reword, void, or stop for a person) instead of
    # silently undoing the insert.
    INSERTS = Path("run/outline_inserts")
    _riders: list = []
    try:
        _ins = INSERTS.read_text().splitlines()
    except OSError:
        _ins = []
    _text = lines[frm - 1]
    for _row in _ins:
        if not _row.startswith("LEG=") or "|" not in _row:
            continue
        _dep, _pre = _row[4:].split("|", 1)
        if _pre.strip() != _text.strip():
            continue
        try:
            _dep_at = lines.index(_dep.strip()) + 1
        except ValueError:
            continue
        if after >= _dep_at > frm:
            _riders.append((_dep_at, _dep.strip()))
    # ...SO THE DEPENDENT TRAVELS WITH IT. Refusing outright threw the
    # model's answer away and, exiting non-zero under `set -e`, took the
    # whole chain down with it — the caller was written to "fall through to
    # the ladder" and never could. Leg 19 is the case: the model said
    # "'Obtain Fresh Water' moves to after leg 25 — Fresh Water is only
    # sold at the Celadon Department Store, which requires reaching Celadon
    # City first", which is exactly right, and the leg it unblocks
    # ("Retrieve the Gold Teeth from Celadon City") is in Celadon too and
    # wants the same move. The insert says A comes BEFORE B; it does not
    # say where B sits. Moving them as a block keeps A before B, which is
    # the whole of what the insert recorded, and honours the deferral the
    # model asked for. Nothing new is decided here: both halves are things
    # the model said.
    # ...AND SO DOES A LEG THAT HAPPENS INSIDE THE PLACE THIS ONE REACHES.
    # 2026-09-02: "Reach Lavender Town" was pushed 22 -> 26 while "Cleanse
    # the Pokemon Tower" and "Retrieve the Pokemon Flute from Mr. Fuji"
    # stayed at 22 and 23 — both of which happen INSIDE Lavender Town, and
    # the Flute is the very item the push's own stated reason named as the
    # prerequisite for reaching it. So the run was set to spend its
    # attempts authoring a walk into a town it had never once entered, and
    # the model noticed before the harness did: the tower plan it wrote
    # opened with go_to_lavender_town.
    #
    # The inserts ledger above could not catch this. Nothing had been
    # inserted, and the dependency is a PLACE, not an item or a flag —
    # which is also why the prerequisite guard did not fire.
    #
    # Same answer as the inserts case, for the same reason: the deferral is
    # the model's and is kept, and what cannot happen before it travels
    # with it. Nothing new is decided here — the outline already said these
    # legs happen in that place, and the engine's own warp table says the
    # place has those rooms.
    try:
        import author as _a
        _ids = set(_a._map_dims()) | set(_a._map_warps())
        _places = set(_a.maps_named(_text, _ids))
        _here = (_places | _a.rooms_of(_places)) if _places else set()
        if _here:
            _have = {t for _, t in _riders} | {_text}
            for _k in range(frm, min(after, n)):
                _t2 = lines[_k]
                if _t2 in _have:
                    continue
                if set(_a.maps_named(_t2, _ids)) & _here:
                    _riders.append((_k + 1, _t2))
                    _have.add(_t2)
    except Exception:
        pass          # ordering help, never a reason the push cannot happen
    after = min(after, n)
    _riders.sort()
    _texts = [lines[frm - 1]] + [t for _, t in _riders]
    for t in _texts:
        lines.remove(t)
    _at = after - len(_texts)          # the removals shifted the target down
    for k, t in enumerate(_texts):
        lines.insert(_at + k, t)
    OUT.write_text("\n".join(lines) + "\n")
    with PUSHES.open("a") as f:
        for t in _texts:
            f.write(f"{frm}\t{after}\t{t}\n")
    text = _texts[0]
    if len(_texts) > 1:
        print(f"pushed {text!r} from {frm} to {after}, and with it "
              + ", ".join(repr(t) for t in _texts[1:])
              + " — each was recorded as needing it first, so they move "
                "together and stay in that order")
    else:
        print(f"pushed {text!r} from {frm} to {after}")


if __name__ == "__main__":
    main(sys.argv[1:])
