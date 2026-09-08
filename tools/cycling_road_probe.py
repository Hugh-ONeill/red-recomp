#!/usr/bin/env python3
"""Boot a COPY of a checkpoint under the test identity, ride from Fuchsia to
the bottom of Cycling Road, and try to climb it. Prints each op's verdict and
the player's cell so the slope mechanics can be seen, not guessed."""
import os, sys, time, shutil, json
from pathlib import Path
ROOT = Path.home() / "Developer/red-recomp"
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import contract as C
save = ROOT / "run/saves/leg_30_reach_fuchsia_city.20260908-121253/slot1.lua"
run_dir = ROOT / "run/slopeprobe"
run_dir.mkdir(parents=True, exist_ok=True)
for f in ("seen.json", "seen_walk.json"):        # the shim's own seen mask
    shutil.copy(ROOT / "run" / f, run_dir / f)
proc = C.start_game(run_dir, save, sys.argv[1] if len(sys.argv) > 1 else "200")
try:
    os.environ["RED_BRIDGE_DIR"] = str(run_dir)
    from bridge import Bridge
    from executor import bootstrap
    b = Bridge(run_dir); bootstrap(b, cont=True)
    def where():
        o = b.obs() or {}; m = (o.get("map") or {}); p = o.get("player") or {}
        return f"{m.get('id')} ({p.get('x')},{p.get('y')}) mode={o.get('mode')}"
    def op(name, **kw):
        t0 = time.time(); r = (b.send(name, **kw) or {}).get("result") or {}
        print(f"  {name}({kw}) -> ok={r.get('ok')} {time.time()-t0:.1f}s :: {str(r.get('detail') or '')[:300]}")
        print(f"      now {where()}")
        return r
    print("start", where())
    op("cross", dir="west")                 # Fuchsia -> Route 18 (east end)
    op("use_warp", x=40, y=8)               # the gate's east door
    op("use_warp", x=0, y=4)                # ...and out its west door
    op("cross", dir="north")                # Route 18 -> Route 17 (bottom)
    o = b.obs() or {}
    print("  onBike?", (o.get("player") or {}), "bag has BICYCLE", (o.get("bag") or {}).get("BICYCLE"))
    op("cross", dir="north")                # THE CLIMB
    print("end", where())
finally:
    C.stop_game(proc)
