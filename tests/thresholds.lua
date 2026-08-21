-- Which warps does the shim's warp_look hide?
--
-- The "landing" rule was written from ONE example -- SILPH_CO_1F 16,10, a
-- warp entry on plain floor with floor on all four sides, which does
-- nothing when you stand on it -- and it was stated as "not a door tile,
-- not a pad, not on the map edge". That description also fits every route
-- gate, every Rocket Hideout lift door, the S.S. Anne cabin doors, and both
-- cells of the Vermilion pier, all of which work perfectly: they fire on a
-- BLOCKED STEP toward a carpet tile (src/world/Warp.lua's extraCheck).
--
-- Sixty ways out of this game were invisible. This walks every map in the
-- ROM data and holds the count: whatever else changes, the set of warps
-- nobody is told about stays the seven that genuinely cannot be taken.
--
-- Run: lua tests/thresholds.lua   (needs the gen1recomp data next door)

local D = os.getenv("HOME") .. "/Developer/gen1recomp/data/generated/"
local ok, maps = pcall(dofile, D .. "maps.lua")
if not ok then print("skip: gen1recomp data not found at " .. D); os.exit(0) end
local ts = dofile(D .. "tilesets.lua")
local field = dofile(D .. "field.lua")
local C = field.warpCarpets
local DIRS = { up = {0,-1}, down = {0,1}, left = {-1,0}, right = {1,0} }

local function setof(l) local s = {} for _, v in ipairs(l or {}) do s[v] = true end return s end
local function inl(l, v) for _, x in ipairs(l or {}) do if x == v then return true end end return false end

local landings, thresholds = {}, 0
for id, m in pairs(maps) do
  local T = ts[m.tileset]
  if T and T.blocks and m.blocks then
    local W, H = m.width * 2, m.height * 2
    local doors, wt = setof(T.doorTiles), setof(T.warpTiles)
    local function cellTile(cx, cy)
      local tx, ty = cx * 2, cy * 2 + 1
      local bx, by = math.floor(tx / 4), math.floor(ty / 4)
      local bid
      if bx < 0 or by < 0 or bx >= m.width or by >= m.height then bid = m.borderBlock
      else bid = m.blocks[by * m.width + bx + 1] end
      local b = T.blocks[(bid or 0) + 1]
      if not b then return nil end
      return b[(ty % 4) * 4 + (tx % 4) + 1]
    end
    local useCarpet
    if inl(C.edgeMaps, id) then useCarpet = false
    elseif inl(C.function2Maps, id) then useCarpet = true
    else useCarpet = inl(C.function2Tilesets, m.tileset) end
    local function extra(x, y, dn)          -- Warp.extraCheck, on raw data
      local facingEdge = (dn == "up" and y == 0) or (dn == "down" and y == H - 1)
                      or (dn == "left" and x == 0) or (dn == "right" and x == W - 1)
      if not useCarpet then return facingEdge end
      local d = DIRS[dn]
      local front = cellTile(x + d[1], y + d[2])
      if id == C.ssAnneBow.map then return front == C.ssAnneBow.tile end
      return inl(C.tiles[dn], front)
    end
    for _, w in ipairs(m.warps or {}) do
      local t = cellTile(w.x, w.y)
      local edge = (w.x <= 0 or w.y <= 0 or w.x >= W - 1 or w.y >= H - 1)
      if not edge and not doors[t] and not wt[t] then
        local fires = false
        for dn in pairs(DIRS) do if extra(w.x, w.y, dn) then fires = true end end
        if fires then thresholds = thresholds + 1
        else landings[#landings + 1] = ("%s %d,%d -> %s"):format(id, w.x, w.y, w.destMap) end
      end
    end
  end
end
table.sort(landings)

-- The seven that really cannot be taken: the far cell of a two-tile gate
-- doorway, the two Silph landings, and Celadon Mart's roof landing.
local WANT = {
  "CELADON_CITY 39,19 -> CELADON_MART_5F",
  "ROUTE_7 11,9 -> ROUTE_7_GATE",
  "ROUTE_7 18,9 -> ROUTE_7_GATE",
  "ROUTE_8 1,9 -> ROUTE_8_GATE",
  "ROUTE_8 8,9 -> ROUTE_8_GATE",
  "SILPH_CO_11F 5,5 -> LAST_MAP",
  "SILPH_CO_1F 16,10 -> SILPH_CO_3F",
}
local fails = 0
local function check(name, cond, detail)
  print(("  %s  %s"):format(cond and "ok  " or "FAIL", name))
  if not cond then print("          " .. tostring(detail)); fails = fails + 1 end
end

print("warps with no door tile, no pad and no map edge under them:")
check(("%d fire on a blocked step"):format(thresholds), thresholds == 60, thresholds)
check(("%d are landings nobody can take"):format(#landings), #landings == #WANT, #landings)
for i, want in ipairs(WANT) do
  check("  " .. want, landings[i] == want, landings[i])
end
check("the Vermilion pier is not among them",
      not inl(landings, "VERMILION_CITY 18,31 -> VERMILION_DOCK"))
check("nor the gangway onto the ship",
      not inl(landings, "VERMILION_DOCK 14,2 -> SS_ANNE_1F"))

print(("\n%s"):format(("-"):rep(60)))
if fails > 0 then
  print(("WAYS OUT ARE BEING HIDDEN AGAIN: %d case(s)"):format(fails))
  os.exit(1)
end
print("only the seven untakeable warps are hidden")
