"""A statue is made by a SCRIPT, not by a tile.

The scan matched collision tile 61 on a comment that claimed it "appears
once per Mansion floor and elsewhere only in the Cinnabar and Saffron
gyms". That was written from memory and never checked: tile 61 is in FIFTY-
FOUR maps — BLUES_HOUSE, DAYCARE, AGATHAS_ROOM, four cells of FUCHSIA_CITY,
CELADON_CITY, PEWTER_CITY — and CINNABAR_GYM at (17,13), the gym the very
next leg walks into (user, 2026-08-24: "are we sure it doesnt appear in
every gym?").

The map scripts now export their own coordinates, so only a map that really
implements switches reports any.
"""
import subprocess, sys, pathlib

GAME = pathlib.Path("/home/wiz/Developer/gen1recomp")
checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


def lua(expr):
    return subprocess.run(
        ["lua5.4", "-e", 'local M = dofile("data/scripts/story6.lua") ' + expr],
        cwd=GAME, capture_output=True, text=True).stdout.strip()


def coords(field, mapid):
    return lua(f'local e = M.{mapid} local l = e and e.{field} '
               'local t = {} for _, c in ipairs(l or {}) do '
               't[#t+1] = c[1] .. "," .. c[2] end print(table.concat(t, " "))')


ck("1F declares its one statue", coords("switches", "POKEMON_MANSION_1F") == "2,5")
ck("B1F declares both of its statues",
   coords("switches", "POKEMON_MANSION_B1F") == "20,3 18,25")
ck("CINNABAR_GYM declares NO statues",
   coords("switches", "CINNABAR_GYM") == "")

ck("CINNABAR_GYM declares its six quiz machines",
   coords("machines", "CINNABAR_GYM") == "15,7 10,1 9,7 9,13 1,13 1,7")
ck("the Mansion declares no quiz machines",
   coords("machines", "POKEMON_MANSION_B1F") == "")

# the ANSWERS stay behind: position is on the screen, the quiz is the puzzle
ck("machine answers are NOT exported",
   lua('local m = M.CINNABAR_GYM.machines '
       'print(tostring(m and m[1] and m[1].yes ~= nil))') == "false")

# and the shim reads scripts, not tiles
shim = (pathlib.Path("/home/wiz/Developer/red-recomp/harness/shim.lua")
        .read_text())
ck("the shim no longer identifies a statue by tile 61",
   "cellTile(cx, cy) == 61" not in shim)
ck("the shim reads the script's own list",
   "_view.switches" in shim and "_view.machines" in shim)

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
