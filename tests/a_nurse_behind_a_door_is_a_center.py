#!/usr/bin/env python3
"""A nurse behind a door is a Center, whatever the map is called.

Indigo Plateau, 2026-09-06. The party stood weak between the lobby's two
doors, the plan's first step was to heal, and heal() answered "no Pokemon
Center nurse here, and no Center door on this map". Both doors lead to
INDIGO_PLATEAU_LOBBY, whose object table holds INDIGOPLATEAULOBBY_NURSE.
The op found Center doors by the destination's NAME containing POKECENTER,
and the lobby is not called that. The model's fallback was DIG to Viridian,
which the gate refuses outdoors, and after that the only healing it knew was
back through Victory Road, whose puzzle resets on the way (user: "it needs
to get to the plateau first so it can heal there ... otherwise itll have to
go through victory road all over again" — "yeah thats exactly what
happened"; and: "maybe for pallet to direct you to your mom").

Who heals is in the game's own tables: a nurse anywhere, and Mom at home
once the starter is had (reds_house.lua, RedsHouse1FMomHealScript). A
nurse also moves where a blackout returns you; Mom does not, and the op
says which. The walk keeps the footprint rule: only a door that has been
on screen is walked to, and an unseen one is said to be unseen.

The first boot of this test found the next bug: from the Plateau's bottom
row, aiming at the unseen lobby door made the retry back off "down", over
the map's south edge onto Route 23, where the op kept its old coordinates,
walked to Route 23's own (9,5), and said "warped". yield_ground now never
steps off the map, and the attempt reads the map fresh instead of the
overworld object it began with.

  tests/a_nurse_behind_a_door_is_a_center.py            the pinned fixture
  tests/a_nurse_behind_a_door_is_a_center.py --no-boot  source and luajit only
"""
from __future__ import annotations
import re, shutil, subprocess, sys, os, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
SHIM = (ROOT / "harness/shim.lua").read_text()
FIXTURE = ROOT / "tests/fixtures/indigo_plateau_outside.lua"
checks = []
def ck(name, cond, detail=""):
    checks.append((name, bool(cond)))
    if not cond and detail:
        print("          " + str(detail)[:300])

ck("the door search asks the destination's object table for someone who heals",
   'or map_has_healer(G, w.destMap)) then' in SHIM)
ck("...beside the old name check, not instead of it",
   'tostring(w.destMap or ""):find("POKECENTER")' in SHIM)
ck("...and only walks to a door that has been on screen",
   'if _seen[w.x .. "," .. w.y] then' in SHIM
   and "has never been on screen from where " in SHIM)
ck("Mom heals only once the starter is had, and never moves the blackout point",
   'G.save.flags.EVENT_GOT_STARTER then' in SHIM
   and "Where you \"\n        .. \"wake after a blackout is UNCHANGED" in SHIM)
ck("a nurse's heal says it moved the blackout point",
   "this is now where you wake \"\n      .. \"after a blackout" in SHIM)
ck("yield_ground never steps off the map",
   "local safe = (ow.map and ow.map.inBounds and ow.map:inBounds(nx, ny))" in SHIM)
ck("use_warp's attempt reads the map fresh, not the object it started with",
   "local _live = G.overworld and G.overworld.map and G.overworld.map.id\n      if _live == startMap then return nil end" in SHIM
   and "if (G.overworld and G.overworld.map and G.overworld.map.id) ~= startMap then\n          G.input.state[dir] = false" in SHIM)

if shutil.which("luajit"):
    m1 = re.search(r"local function is_healer_def\(G, mapid, o\).*?\nend\n", SHIM, re.S)
    m2 = re.search(r"function map_has_healer\(G, mapid\).*?\nend\n", SHIM, re.S)
    ck("the helpers extract", bool(m1 and m2))
    lua = m1.group(0) + m2.group(0) + '''
local os = require("os")
local G = { save = { flags = { EVENT_GOT_STARTER = true } }, data = { maps = {
  INDIGO_PLATEAU_LOBBY = { objects = { { name = "INDIGOPLATEAULOBBY_NURSE", sprite = "SPRITE_NURSE" },
                                        { name = "INDIGOPLATEAULOBBY_CLERK", sprite = "SPRITE_CLERK" } } },
  REDS_HOUSE_1F = { objects = { { name = "REDSHOUSE1F_MOM", sprite = "SPRITE_MOM" } } },
  VIRIDIAN_MART = { objects = { { name = "VIRIDIANMART_CLERK", sprite = "SPRITE_CLERK" } } },
  ROUTE_23 = { objects = {} },
} } }
local ok = true
local function ck(name, got, want)
  if got ~= want then ok = false; print("FAIL " .. name .. " got=" .. tostring(got)) else print("ok   " .. name) end
end
ck("the lobby holds a healer", map_has_healer(G, "INDIGO_PLATEAU_LOBBY"), true)
ck("Mom's house holds a healer", map_has_healer(G, "REDS_HOUSE_1F"), true)
local G2 = { save = { flags = {} }, data = G.data }
ck("...but not before the starter", map_has_healer(G2, "REDS_HOUSE_1F"), false)
ck("a mart does not", map_has_healer(G, "VIRIDIAN_MART"), false)
ck("an empty map does not", map_has_healer(G, "ROUTE_23"), false)
ck("an unknown map does not", map_has_healer(G, "NOWHERE"), false)
ck("a nurse is a nurse", is_healer_def(G, "INDIGO_PLATEAU_LOBBY", { sprite = "SPRITE_NURSE" }), "nurse")
ck("Mom is Mom, at home only", is_healer_def(G, "REDS_HOUSE_1F", { sprite = "SPRITE_MOM" }), "mom")
ck("...and a Mom sprite elsewhere is not", is_healer_def(G, "CELADON_MANSION_1F", { sprite = "SPRITE_MOM" }), nil)
os.exit(ok and 0 or 1)
'''
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as f:
        f.write(lua); path = f.name
    r = subprocess.run(["luajit", path], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        ck("luajit: " + line[5:], line.startswith("ok"))
    ck("luajit run exits clean", r.returncode == 0)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)

if "--no-boot" not in sys.argv and FIXTURE.exists():
    import contract as C                               # noqa: E402
    run_dir = ROOT / "run/nursedoor"
    # A FRESH FOOTPRINT. The bridge dir keeps seen.json between boots, so a
    # second run of this test started with the lobby door already seen and
    # the "never on screen" half could not be exercised.
    for f in ("seen.json", "seen_walk.json"):
        (run_dir / f).unlink(missing_ok=True)
    proc = C.start_game(run_dir, FIXTURE, "200")
    try:
        os.environ["RED_BRIDGE_DIR"] = str(run_dir)
        from bridge import Bridge                       # noqa: E402
        from executor import bootstrap                  # noqa: E402
        b = Bridge(run_dir); bootstrap(b, cont=True)
        o = b.obs() or {}
        here = (o.get("map") or {}).get("id")
        pl = o.get("player") or {}
        print(f"  standing on {here} at {pl.get('x')},{pl.get('y')}; respawn {(o.get('respawn') or {}).get('map')}")
        if here != "INDIGO_PLATEAU":
            print("  SKIPPED the boot half — the fixture is not on INDIGO_PLATEAU")
        else:
            # the shunt, as a regression: the door has never been on screen from
            # the bottom row, so the op must refuse and the party must stay put
            r = (b.send("use_warp", x=9, y=5) or {}).get("result") or {}
            o = b.obs() or {}
            ck("use_warp at a door never on screen is refused and the party stays on the map",
               not r.get("ok") and (o.get("map") or {}).get("id") == "INDIGO_PLATEAU",
               f"{r.get('detail')} | now {(o.get('map') or {}).get('id')}")
            r = (b.send("heal") or {}).get("result") or {}
            o = b.obs() or {}
            ck("heal with the door unseen says so, and does not wander",
               not r.get("ok") and "has never been on screen" in str(r.get("detail"))
               and (o.get("map") or {}).get("id") == "INDIGO_PLATEAU", str(r.get("detail")))
            # look first, then heal
            b.send("sweep", until="door")
            o = b.obs() or {}
            seen_door = any(w.get("x") in (9, 10) for w in (o.get("map") or {}).get("warps") or [])
            ck("a sweep brings the lobby door into view", seen_door, str((o.get("map") or {}).get("warps")))
            r = (b.send("heal") or {}).get("result") or {}
            o = b.obs() or {}
            now = (o.get("map") or {}).get("id")
            det = str(r.get("detail") or "")
            ck("heal then walks into the lobby and the nurse heals", r.get("ok") and now == "INDIGO_PLATEAU_LOBBY",
               f"{det} | now on {now}")
            hurt = [m for m in (o.get("party") or []) if int(m.get("hp") or 0) < int(m.get("max_hp") or m.get("hp") or 0)]
            ck("...the party is at full HP", not hurt, str([(m.get('species'), m.get('hp'), m.get('max_hp')) for m in hurt]))
            ck("...and the blackout point is now the lobby, as the op says",
               (o.get("respawn") or {}).get("map") == "INDIGO_PLATEAU_LOBBY" and "where you wake" in det,
               f"{o.get('respawn')} | {det}")
    finally:
        C.stop_game(proc)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
