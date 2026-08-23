"""A door you can now reach is not the door that refused you.

The repeat gate says "same ops, same world, same answer". For a warp whose
recorded answer was "couldn't reach the warp tile", that is checkable
against the observation instead of assumed — POKEMON_MANSION_1F's two
halves share one region name, so a failure from the walled-off half was
replayed at the sealed half while the party stood three cells from the
door with it reported reachable (2026-08-23).
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


def gate(seen_why, warps, macro):
    """The exemption, exactly as executor.py applies it."""
    _seen = {"why": seen_why} if seen_why is not None else None
    if _seen and any(w in str(_seen.get("why") or "").lower()
                     for w in ("reach the warp tile", "no path")):
        _want = {(st.get("x"), st.get("y")) for st in macro
                 if isinstance(st, dict)
                 and st.get("op") in ("use_warp", "walk_to")
                 and st.get("x") is not None}
        if any((w.get("x"), w.get("y")) in _want and w.get("reachable")
               for w in warps):
            _seen = None
    return _seen is not None          # True == still refused


shut = [{"x": 21, "y": 23, "reachable": False}]
open_ = [{"x": 21, "y": 23, "reachable": True}]
mac = [{"op": "use_warp", "x": 21, "y": 23}]

ck("unreachable-then, reachable-now: allowed",
   not gate("FAILED — couldn't reach the warp tile (no path)", open_, mac))
ck("unreachable-then, still shut: refused",
   gate("FAILED — couldn't reach the warp tile (no path)", shut, mac))
ck("a different failure is not excused by reachability",
   gate("FAILED — the door is locked", open_, mac))
ck("a different door being open does not excuse it",
   gate("FAILED — couldn't reach the warp tile", 
        [{"x": 5, "y": 10, "reachable": True}], mac))
ck("no record: nothing to refuse", not gate(None, open_, mac))

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
