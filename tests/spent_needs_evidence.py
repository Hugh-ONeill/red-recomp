"""A macro is spent when it FAILED, not when it merely did not finish.

`ok` from _run_traced means the SUBGOAL was satisfied. Under REDO a macro
can do exactly what it said and still return False — warping to B1F does
not satisfy `map == POKEMON_MANSION_1F` — so a use_warp the trace records
as "ok (map->POKEMON_MANSION_B1F, moved, warped)" was filed as a spent
failure with no reason, and the gate then refused the ONLY exit out of
POKEMON_MANSION_1F's sealed half (2026-08-23).
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


def records(ok, trace):
    """The guard, exactly as executor.py applies it."""
    _why = next((str(t) for t in reversed(trace)
                 if "FAILED" in str(t) or "REFUSED" in str(t)), "")
    _did = any(w in str(t) for t in trace
               for w in ("map->", "moved", "warped"))
    return bool(not ok and (_why or not _did))


warped = ["use_warp(x=21,y=23): ok (map->POKEMON_MANSION_B1F, moved, warped)"]
failed = ["use_warp(x=21,y=23): FAILED — couldn't reach the warp tile"]
nothing = ["interact(x=2,y=5): ok"]
mixed = ["use_warp(x=21,y=23): ok (map->POKEMON_MANSION_B1F, moved, warped)",
         "interact(name=FOO): FAILED — no such thing here"]

ck("it worked and moved you, subgoal unmet: NOT spent",
   not records(False, warped))
ck("it failed: spent", records(False, failed))
ck("nothing happened at all: spent", records(False, nothing))
ck("moved but something in it failed: spent", records(False, mixed))
ck("subgoal satisfied: never spent", not records(True, failed))

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
