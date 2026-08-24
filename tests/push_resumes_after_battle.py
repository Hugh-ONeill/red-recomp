"""A push interrupted by a battle comes back "ok", and it is not done.

Victory Road is wild ground end to end and a solved shove route is dozens of
walking steps, so a battle lands mid-route almost every time. The executor
fights it and marks the step ok — the party moved, the battle was fled — so
the trace reads `push(...): ok (moved, fled)` with the boulder halfway and
the run believing the switch was pressed (user, 2026-08-24: "not continuing
after battle"; EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH was never set and 2F
was never entered).

So the op's own verdict is not the test. Whether a boulder is standing on
the cell it was sent to is in the observation, and that is the only thing
this op was for.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
src = (ROOT / "planner" / "executor.py").read_text()
shim = (ROOT / "harness" / "shim.lua").read_text()

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


# the executor half: decide from the floor
i = src.find("DO NOT ASK THE OP WHETHER IT WORKED")
block = src[i:i + 3200] if i > 0 else ""
ck("the executor checks the floor, not the op", i > 0)
ck("...by looking for a boulder on the target cell",
   'get("kind") == "boulder"' in block)
ck("...and no longer trusts r['ok'] to decide",
   'not (r or {}).get("ok")' not in block)
ck("it resumes rather than abandoning partial progress",
   "resumed" in block)
ck("it fights what interrupted before resuming",
   "handle_battle" in block)
ck("and it is bounded", "_tries < 4" in block)

# the shim half: ok means arrived
j = shim.find("SAY OK ONLY IF IT IS ACTUALLY THERE")
sblock = shim[j:j + 900] if j > 0 else ""
ck("the shim verifies the boulder arrived", j > 0)
ck("...comparing against the cell it was sent to",
   "rock.cellX ~= _to_x" in sblock)
ck("...and reports how many shoves banked", "shove(s) went in" in sblock)

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
