"""A grind is the one op whose point is repetition.

`grind` paces this ground until DONE_WHEN is met, and what it earns —
experience — is invisible to the world mark, which counts badges, flags and
bag kinds and nothing else. So a second identical grind reads as "same ops,
same world, same answer" when the answer was several levels. Worse, whether
it was banned came down to whether its trace happened to mention movement:

    ok (party changed, moved, turn resolved ...)   -> survived
    ok (turn resolved (timeout advancing text))    -> filed as SPENT

Six grinds were refused on ROUTE_22 that way (user, 2026-08-24: "we
shouldnt be refusing repeated grinds").
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "planner"))

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


def grinds(macro):
    return any(isinstance(st, dict) and st.get("op") == "grind"
               for st in macro)


def records(ok, trace, macro):
    """The recording guard, as executor.py applies it."""
    _why = next((str(t) for t in reversed(trace)
                 if "FAILED" in str(t) or "REFUSED" in str(t)), "")
    _did = any(w in str(t) for t in trace
               for w in ("map->", "moved", "warped"))
    _dry = any("earned 0 exp" in str(t) for t in trace)
    return bool(not ok and (_why or not _did) and (not grinds(macro) or _dry))


G = [{"op": "grind", "intent": "train"}]
quiet = ["grind(intent=train): ok (turn resolved (timeout advancing text))"]
moved = ["grind(intent=train): ok (party changed, moved, turn resolved)"]

ck("a quiet grind is not spent", not records(False, quiet, G))
ck("a moving grind is not spent", not records(False, moved, G))
ck("a failed grind is not spent either",
   not records(False, ["grind: FAILED — nothing wild lives here"], G))

# ...BUT A GRIND THAT EARNED NOTHING IS SPENT. The blanket exemption was
# the right shape and the wrong test: on ground with no wilds it would let
# a grind repeat for ever. Party exp is in the observation, so the trace
# carries the number and the gate reads it (user, 2026-08-24: "can we add
# up exp and see if we can distinguish productive from non-productive").
paid = ["grind(intent=train) earned 3480 exp: ok (moved, battle ended)"]
dry = ["grind(intent=train) earned 0 exp: ok (turn resolved)"]
ck("a grind that PAID is not spent", not records(False, paid, G))
ck("a grind that earned 0 exp IS spent", records(False, dry, G))
ck("...and the zero is what gets recorded as the reason",
   "earned 0 exp" in next((str(t) for t in dry if "earned 0" in str(t)), ""))

# a macro that merely travels is still gated
W = [{"op": "use_warp", "x": 1, "y": 2}]
ck("a non-grind that did nothing is still spent",
   records(False, ["interact(x=1,y=2): ok"], W))
ck("a non-grind that moved is still not spent",
   not records(False, ["use_warp(x=1,y=2): ok (map->X, moved, warped)"], W))

# a grind bundled with travel still counts as a grind
GW = [{"op": "walk_to", "x": 5, "y": 5}, {"op": "grind"}]
ck("a grind bundled with a walk is still exempt", grinds(GW))
ck("...and is not recorded", not records(False, quiet, GW))

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
