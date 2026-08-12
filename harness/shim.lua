-- red-recomp harness shim v0 — the game as a tool call.
--
-- Runs as POKEPORT_DRIVER inside gen1recomp: each bridge cycle serializes a
-- player-visible observation to $RED_BRIDGE_DIR/obs.json, polls cmd.lua for
-- an op with a fresh seq, executes it with the in-tree driver primitives,
-- and reports the result in the next observation. Decision-free executors
-- only (CLAIM_RULES_v1 harness boundary): walking, tapping, waiting. No
-- engine oracles are read here beyond what the game shows a player.
--
-- Launch (from the gen1recomp checkout, so requires resolve):
--   POKEPORT_DRIVER=$HOME/Developer/red-recomp/harness/shim.lua \
--   POKEPORT_SPEED=20 love .
-- Headless: prefix xvfb-run -a env.

local U = require("tests.drivers.util")

local BRIDGE = os.getenv("RED_BRIDGE_DIR")
  or ((os.getenv("HOME") or ".") .. "/Developer/red-recomp/run")
os.execute('mkdir -p "' .. BRIDGE .. '" 2>/dev/null')

-- ------------------------------------------------------------ op watchdog
-- Every bridge-side activity must be FRAME-BOUNDED: brock19 wedged >120s
-- inside one op mid-forest and the whole stack died on an uncaught bridge
-- timeout. While a budget is armed, yields on the DRIVER coroutine are
-- counted (this covers the shim AND U.wait/U.tap, which yield the global);
-- exceeding the budget raises, and wd_run converts that into an op failure
-- naming the phase and position. Game-side coroutines (script runners)
-- fail the running() identity check and are never affected.
local RAW_YIELD = coroutine.yield
local UNPACK = table.unpack or unpack
local wd = { co = nil, budget = nil, frames = 0, label = "?" }
-- HEARTBEAT: brock19/20 wedged with the frame watchdog SILENT — either the
-- wall frame-rate collapsed (yields still flow, slowly) or something spins
-- without yielding; the watchdog counts yields so it is blind to both.
-- Every driver yield ticks a counter; every 2048 ticks the wall time +
-- count + current op land in run/heartbeat. Sampling that file twice gives
-- the effective yield rate (healthy 200X ~ 12k/s); a frozen file means
-- yield starvation. Hook-free on purpose: debug.sethook would disable the
-- JIT and cause the very slowdown being hunted.
local hb = { yields = 0 }
coroutine.yield = function(...)
  local co = coroutine.running()
  if wd.co and co == wd.co then
    hb.yields = hb.yields + 1
    if hb.yields % 2048 == 0 then
      local f = io.open(BRIDGE .. "/heartbeat", "w")
      if f then
        f:write(os.time() .. " " .. hb.yields .. " " .. tostring(wd.label))
        f:close()
      end
    end
  end
  if wd.budget and co == wd.co then
    wd.frames = wd.frames + 1
    if wd.frames > wd.budget then
      wd.budget = nil
      error("WATCHDOG: " .. wd.label .. " exceeded "
            .. wd.frames .. " frames", 0)
    end
  end
  return RAW_YIELD(...)
end
local function wd_run(G, label, budget, fn, ...)
  wd.co = coroutine.running()
  wd.label = label
  wd.budget = budget
  wd.frames = 0
  local res = { pcall(fn, ...) }
  wd.budget = nil
  if res[1] then return UNPACK(res, 2) end
  -- an op aborted mid-yield may have skipped its key-release lines: a
  -- direction left held would corrupt every later op
  if G and G.input and G.input.state then
    for k in pairs(G.input.state) do G.input.state[k] = false end
  end
  local where = ""
  local ow = G and G.overworld
  if ow and ow.map then
    local p = ow.player or {}
    where = (" at %s (%s,%s)"):format(tostring(ow.map.id),
      tostring(p.cellX), tostring(p.cellY))
  end
  return false, tostring(res[2]) .. where
end
local OP_FRAME_BUDGET = 120000   -- ~33 game-minutes; no legit op comes close

-- ---------------------------------------------------------------- json out
local function jesc(s)
  -- escape EVERY control byte, not just the common five: gen1 text decodes
  -- its line-advance code to 0x0b, and one bug-catcher endBattleText with a
  -- raw \v made every obs.json invalid JSON from that battle on — the
  -- Python side read None forever and the whole run wedged (brock19/20/21)
  s = s:gsub('[%c\\"]', function(ch)
    if ch == "\\" then return "\\\\"
    elseif ch == '"' then return '\\"'
    elseif ch == "\n" then return "\\n"
    elseif ch == "\r" then return "\\r"
    elseif ch == "\t" then return "\\t"
    else return string.format("\\u%04x", ch:byte()) end
  end)
  return '"' .. s .. '"'
end

local function jenc(v)
  local t = type(v)
  if t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "null" end
    return string.format("%.10g", v)
  elseif t == "string" then return jesc(v)
  elseif t == "boolean" then return tostring(v)
  elseif t == "table" then
    if #v > 0 or next(v) == nil then
      local parts = {}
      for i = 1, #v do parts[i] = jenc(v[i]) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    local parts = {}
    for k, val in pairs(v) do
      if type(k) == "string" then
        parts[#parts + 1] = jesc(k) .. ":" .. jenc(val)
      end
    end
    table.sort(parts)
    return "{" .. table.concat(parts, ",") .. "}"
  end
  return "null"
end

-- ------------------------------------------------------------ observation
-- Shallow scalar copy: self-discovering schema for tables whose exact field
-- names we haven't pinned — scalars pass, sub-tables are named only.
local function scalars(t, depth)
  local out = {}
  if type(t) ~= "table" then return out end
  for k, v in pairs(t) do
    if type(k) == "string" then
      local tv = type(v)
      if tv == "number" or tv == "string" or tv == "boolean" then
        out[k] = v
      elseif tv == "table" and (depth or 0) > 0 then
        out[k] = scalars(v, depth - 1)
      end
    end
  end
  return out
end

local events = {}
do
  local Runtime = require("src.mods.Runtime")
  local base = Runtime.emit
  Runtime.emit = function(name, payload)
    events[#events + 1] = name
    return base(name, payload)
  end
end


local function party(G)
  local out = {}
  for i, mon in ipairs((G.save and G.save.party) or {}) do
    local m = scalars(mon, 1)
    -- max HP lives in the nested stats table the scalar pass drops; the
    -- HUD shows hp/max and status, so they are player-visible eyes
    m.max_hp = mon.stats and mon.stats.hp
    if mon.status ~= nil then m.status = tostring(mon.status) end
    m.moves = {}
    for j, mv in ipairs(mon.moves or {}) do
      m.moves[j] = type(mv) == "table" and scalars(mv, 0) or tostring(mv)
    end
    out[i] = m
  end
  return out
end

local function badges(G)
  local out = {}
  for k in pairs((G.save and G.save.inventory) or {}) do
    if type(k) == "string" and k:match("BADGE$") then out[#out + 1] = k end
  end
  table.sort(out)
  return out
end

-- The last dialogue text auto-advance rode past. Auto-advance strips text
-- before a choice box, which would leave the model answering a context-free
-- yes/no; carry the prompt into the observation so the choice has meaning.
local warp_reach            -- assigned after DIRS/ledge_landing
local recent_text = nil
-- Oracle probe result (battle_probe), surfaced once in the next observation.
local last_probe = nil

local function observe(G, seq, result)
  local top = G.stack and G.stack:top()
  local o = { seq = seq, result = result, events = events, frame = U.frame() }
  events = {}
  if recent_text then o.recent_text = recent_text end
  if G.overworld and top == G.overworld then
    recent_text = nil          -- free roam: stale prompt no longer applies
    o.recent_text = nil
    o.mode = "overworld"
    local p = G.overworld.player or {}
    o.player = { x = p.cellX, y = p.cellY, facing = p.facing,
                 moving = p.moving and true or false }
    if os.getenv("RED_DBG_BUSY") == "1" then
      local function n(t) return type(t) == "table" and #t or -1 end
      local nmov = 0
      for _, npc in ipairs(G.overworld.npcs or {}) do
        if npc.moving then nmov = nmov + 1 end
      end
      local r = G.overworld.runner
      o.dbg = {
        runner = r and r.isRunning and (r:isRunning() and 1 or 0) or -1,
        scriptMoves = n(G.overworld.scriptMoves),
        pending = n(G.overworld.pendingScripts),
        parallel = n(G.overworld.parallelRunners),
        queue = n(G.overworld.parallelQueue),
        npcs_moving = nmov,
      }
    end
    local map = G.overworld.map or {}
    local md = G.data and G.data.maps and G.data.maps[map.id]
    -- Warps and dimensions are player-visible (stairs, doors, mats, the
    -- screen itself), so they belong in the eyes. Dims come from static map
    -- data (live map.width/height are nil for many maps); blocks are 2x2.
    local wb = (md and md.width) or map.width
    local hb = (md and md.height) or map.height
    o.map = { id = map.id, name = map.name,
              width = wb and wb * 2, height = hb and hb * 2 }
    if md and md.warps then
      o.map.warps = {}
      local reach = warp_reach(G) or {}
      -- REGION: two positions in the same walkable component share the same
      -- smallest reachable cell. "Did I actually get somewhere else?" is a
      -- question about the COMPONENT, not about distance (coming out the
      -- same cave door lands tiles away but in the same region — thin7).
      do
        local bx, by
        for k in pairs(reach) do
          local cx, cy = k:match("^(-?%d+),(-?%d+)$")
          if cx then
            cx, cy = tonumber(cx), tonumber(cy)
            if not bx or cy < by or (cy == by and cx < bx) then
              bx, by = cx, cy
            end
          end
        end
        if bx then o.map.region = bx .. "," .. by end
      end
      -- LAST_MAP is gen1's "back outdoors where you came from" and it is
      -- what every route GATE uses for its outward doors. Left raw, the
      -- model saw "(4,0)->LAST_MAP" (meaningless) beside
      -- "(4,7)->VIRIDIAN_FOREST" (familiar) and kept walking back into the
      -- forest. Resolve it the way the engine does — the player knows
      -- perfectly well which town is behind them.
      local lastOut = (G.overworld and G.overworld.lastOutdoor
                       and G.overworld.lastOutdoor.id)
                      or (G.save and G.save.lastOutdoor
                          and G.save.lastOutdoor.id)
      for i, w in ipairs(md.warps) do
        local dest = w.destMap
        if dest == "LAST_MAP" and lastOut then dest = lastOut end
        o.map.warps[i] = { x = w.x, y = w.y, dest = dest,
                           reachable = reach[w.x .. "," .. w.y] and true
                                       or false }
      end
    end
    -- Connections to adjacent maps (the routes/towns you reach by walking off
    -- an edge). Player-visible: the path leads off-screen that way.
    if md and md.connections then
      o.map.connections = {}
      for d, cn in pairs(md.connections) do
        o.map.connections[d] = cn.map
      end
    end
    -- Interactable objects the player can see: G.overworld.npcs is the LIVE
    -- list already filtered by objectVisible (taken items / beaten trainers /
    -- toggled-off objects are gone). Classified so the model can walk_to and
    -- interact with balls, NPCs, and signs instead of mashing blindly.
    o.map.objects = {}
    local objreach = warp_reach(G) or {}
    -- literal offsets, NOT the DIRS table: DIRS is declared further down
    -- the file, so inside observe() it is nil (the same scoping trap that
    -- killed the driver when warp reachability was first added)
    local function adjacent_reachable(x, y)
      return (objreach[(x - 1) .. "," .. y]
              or objreach[(x + 1) .. "," .. y]
              or objreach[x .. "," .. (y - 1)]
              or objreach[x .. "," .. (y + 1)]) and true or false
    end
    for _, npc in ipairs(G.overworld.npcs or {}) do
      local d = npc.def or {}
      local name = d.name or ""
      local kind = "npc"
      if name:find("POKE_BALL") or d.item then
        kind = "item"
      elseif d.trainerClass then
        kind = "trainer"
      elseif name:find("SIGN") or (d.text and not d.sprite) then
        kind = "sign"
      end
      o.map.objects[#o.map.objects + 1] = {
        x = npc.cellX, y = npc.cellY, kind = kind, name = name,
        facing = npc.facing,
        -- can we actually get next to it from here? "The Super Nerd is on
        -- this floor but not reachable from this room" is knowable on
        -- arrival; without it the run spends 10 escalation rounds finding
        -- out (user: "the first two ladders lead to dead-end rooms").
        reachable = adjacent_reachable(npc.cellX, npc.cellY),
      }
    end
  elseif top and (top.enemy or top.kind) then
    o.mode = "battle"
    o.battle = scalars(top, 0)
    local function side(s)
      if not s then return nil end
      local d = scalars(s, 0)
      local mon = s.mon or {}
      d.species = mon.species or (s.def and s.def.id)
      d.level = mon.level
      d.hp = s.shownHP or mon.hp
      d.maxhp = (s.curStats and s.curStats.hp)
      d.types = s.curTypes
      d.status = s.shownStatus or mon.status   -- scalar "SLP"/"PSN"/... or nil
      d.moves = {}
      for i, mv in ipairs(s.curMoves or mon.moves or {}) do
        local def = G.data and G.data.moves and G.data.moves[mv.id] or {}
        -- gen1: physical vs special is decided by the move's TYPE, not a
        -- per-move flag. NORMAL/FIGHTING/FLYING/GROUND/ROCK/BUG/GHOST/POISON
        -- are physical; the rest are special.
        local PHYS = { NORMAL=1, FIGHTING=1, FLYING=1, GROUND=1, ROCK=1,
                       BUG=1, GHOST=1, POISON=1 }
        d.moves[i] = { index = i, id = mv.id, pp = mv.pp,
                       type = def.type, power = def.power,
                       accuracy = def.accuracy, effect = def.effect,
                       category = def.type and (PHYS[def.type] and "physical"
                                  or "special") }
      end
      d.stats = s.curStats            -- effective in-battle stats
      d.boosts = s.stages             -- stat stage modifiers
      return d
    end
    o.battle.me = side(top.player)
    o.battle.foe = side(top.enemy)
    o.battle.player_mon, o.battle.enemy_mon = nil, nil
    if last_probe then o.battle.probe = last_probe; last_probe = nil end
  elseif top and top.pages and top.pageIndex then
    -- TextBox: pages are arrays of display-ready line strings. Emit only the
    -- page currently on screen — the model reads at the same pace a player
    -- does and advances with A, no lookahead.
    o.mode = "dialog"
    local page = top.pages[top.pageIndex] or {}
    o.dialog = { text = table.concat(page, "\n"),
                 page = top.pageIndex, pages = #top.pages,
                 waiting = top.waiting and true or false,
                 done = top.done and true or false }
  elseif top then
    o.mode = "ui"
    o.ui = scalars(top, 0)
  else
    o.mode = "boot"
  end
  o.party = party(G)
  o.badges = badges(G)
  -- bag: player-visible (the START menu ITEM screen); badges live in the
  -- same inventory table but are not bag items
  o.bag = {}
  for k, v in pairs((G.save and G.save.inventory) or {}) do
    if type(k) == "string" and not k:match("BADGE$")
       and (tonumber(v) or 0) > 0 then
      o.bag[k] = v
    end
  end
  o.money = G.save and G.save.money
  -- Set event flags, for the EXECUTOR's done_when predicates (SPD tier 0).
  -- Instrumentation, not model eyes: the model-facing obs builder must strip
  -- this per CLAIM_RULES ("milestone/event flags are instrumentation").
  o.flags = {}
  for k, v in pairs((G.save and G.save.flags) or {}) do
    if v and type(k) == "string" then o.flags[#o.flags + 1] = k end
  end
  table.sort(o.flags)
  local f = io.open(BRIDGE .. "/obs.json.tmp", "w")
  if f then
    f:write(jenc(o))
    f:close()
    os.rename(BRIDGE .. "/obs.json.tmp", BRIDGE .. "/obs.json")
  end
end

-- -------------------------------------------------------------- executors
local function walk(G, dir, steps)
  local ow = G.overworld
  for step = 1, steps do
    local p = ow.player
    if p.facing ~= dir then
      U.tap(G, dir)            -- gen1 tap-to-face
      U.wait(4)
    end
    local sx, sy = p.cellX, p.cellY
    local moved = false
    for _ = 1, 60 do
      table.insert(G.input.pressQueue, dir)
      G.input.state[dir] = true
      coroutine.yield()
      if p.cellX ~= sx or p.cellY ~= sy then moved = true break end
    end
    G.input.state[dir] = false
    U.wait(4)                  -- settle into the cell
    if not moved then
      return false, ("stuck at step %d/%d (%s,%s)"):format(
        step, steps, tostring(p.cellX), tostring(p.cellY))
    end
  end
  return true
end

-- BFS next-step toward (tx,ty) on the current map, using the engine's own
-- collision verdict (bounds/tile/entity — NPCs included live). Probe movers
-- inherit the real player via metatable so elevation/bike state hold.
-- Recomputed per step by walk_to: moving NPCs invalidate paths, so plans
-- are disposable. Sight-lines are deliberately NOT avoided — dodging
-- trainers is strategy, and strategy belongs to the model.
local DIRS = { up = {0,-1}, down = {0,1}, left = {-1,0}, right = {1,0} }

-- One-way ledge hop landing from (x,y) pressing dirname, or nil. Ledges
-- are walls to canMove (the engine hops via checkLedgeHop BEFORE tryMove),
-- so a ledge-blind BFS called Route 4's descent to Cerulean unreachable
-- (chain1). Same static rows the engine consults; landing must be a
-- walkable in-bounds cell.
local function ledge_landing(G, map, x, y, dirname)
  local d = DIRS[dirname]
  local fx, fy = x + d[1], y + d[2]
  if not map.inBounds or not map:inBounds(fx, fy) then return nil end
  local tileset = map.def and map.def.tileset
  local standing = map:cellTile(x, y)
  local front = map:cellTile(fx, fy)
  for _, ledge in ipairs((G.data and G.data.field
                          and G.data.field.ledges) or {}) do
    if (ledge.tileset or "OVERWORLD") == tileset
       and ledge.facing == dirname and ledge.input == dirname
       and ledge.standingTile == standing and ledge.ledgeTile == front then
      local lx, ly = fx + d[1], fy + d[2]
      if map:inBounds(lx, ly) and map:isWalkableCell(lx, ly) then
        return lx, ly
      end
      return nil
    end
  end
  return nil
end

-- Which cells can we currently WALK to (ledge hops included)? Used to mark
-- warps reachable/unreachable in the observation: on partitioned maps (Mt
-- Moon B1F) the right warp can be visible but walled off, and without this
-- the model re-proposes it forever. Defined here because it needs DIRS and
-- ledge_landing; observe() calls it through a forward-declared local.
function warp_reach(G)
  local okc, Collision = pcall(require, "src.world.Collision")
  local ow, p = G.overworld, G.overworld and G.overworld.player
  if not (okc and ow and p and ow.map) then return nil end
  local key = function(x, y) return x .. "," .. y end
  local seen = { [key(p.cellX, p.cellY)] = true }
  local q, head = { { x = p.cellX, y = p.cellY } }, 1
  -- STATIC blockers count, WANDERERS do not. Passing no entities at all
  -- made region ids stable (a strolling NPC no longer redraws the map) but
  -- also made the fossils on MT_MOON_B2F invisible — and in this game the
  -- FOSSIL OBJECTS are what block the corridor, so "reachable" lied about
  -- the way onward. Keep anything that stays put (items, STAY npcs) and
  -- drop only movers: furniture is geography, traffic is not.
  local STATIC = {}
  for _, e in ipairs(ow.entities or {}) do
    local mv = (e.def and e.def.movement) or "STAY"
    if mv ~= "WALK" then STATIC[#STATIC + 1] = e end
  end
  local NOBODY = STATIC
  while q[head] do
    local cur = q[head]; head = head + 1
    for dn, d in pairs(DIRS) do
      local nx, ny = cur.x + d[1], cur.y + d[2]
      if not seen[key(nx, ny)] then
        local probe = setmetatable({ cellX = cur.x, cellY = cur.y },
                                   { __index = p })
        if Collision.canMove(ow.map, NOBODY, probe, dn) then
          seen[key(nx, ny)] = true
          q[#q + 1] = { x = nx, y = ny }
        else
          local lx, ly = ledge_landing(G, ow.map, cur.x, cur.y, dn)
          if lx and not seen[key(lx, ly)] then
            seen[key(lx, ly)] = true
            q[#q + 1] = { x = lx, y = ly }
          end
        end
      end
    end
  end
  return seen
end

-- Cells a walk may never pass THROUGH: warp tiles fire on the step, so a
-- path routed over one teleports the party mid-walk. Walking to ladder
-- (5,5) through the (25,15) ladder's tile went down the wrong hole, and
-- the wrong landing was then recorded against (5,5) — severing the learned
-- route east of Route 3. Only the walk's own destination may be a warp.
local function warp_block(G, tx, ty)
  local ow = G.overworld
  local md = ow.map and ow.map.def
  local blocked = {}
  for _, w in ipairs((md and md.warps) or {}) do
    if not (w.x == tx and w.y == ty) then
      blocked[w.x .. "," .. w.y] = true
    end
  end
  return blocked
end

local function bfs_dir(G, tx, ty)
  local Collision = require("src.world.Collision")
  local ow = G.overworld
  local p = ow.player
  if p.cellX == tx and p.cellY == ty then return nil, "arrived" end
  local key = function(x, y) return x .. "," .. y end
  local wblock = warp_block(G, tx, ty)
  local seen = { [key(p.cellX, p.cellY)] = true }
  local queue = { { x = p.cellX, y = p.cellY, first = nil } }
  local head = 1
  while queue[head] do
    local cur = queue[head]; head = head + 1
    for dir, d in pairs(DIRS) do
      local nx, ny = cur.x + d[1], cur.y + d[2]
      if not seen[key(nx, ny)] and not wblock[key(nx, ny)] then
        local probe = setmetatable({ cellX = cur.x, cellY = cur.y },
                                   { __index = p })
        if Collision.canMove(ow.map, ow.entities, probe, dir) then
          seen[key(nx, ny)] = true
          local first = cur.first or dir
          if nx == tx and ny == ty then return first end
          queue[#queue + 1] = { x = nx, y = ny, first = first }
        else
          local lx, ly = ledge_landing(G, ow.map, cur.x, cur.y, dir)
          if lx and not seen[key(lx, ly)] and not wblock[key(lx, ly)] then
            seen[key(lx, ly)] = true
            local first = cur.first or dir
            if lx == tx and ly == ty then return first end
            queue[#queue + 1] = { x = lx, y = ly, first = first }
          end
        end
      end
    end
  end
  return nil, "no path"
end

-- Nearest reachable tile on a given map edge (the walkable gap in a fence is
-- the only edge tile BFS can reach), for crossing to a connected map.
-- Map dimensions in CELLS. The live overworld map object's width/height are
-- unreliable (nil for many maps -> broke cross south/east, which need them);
-- the static map data is authoritative. Blocks are 2x2 cells.
local function map_dims_cells(G)
  local ow = G.overworld
  local id = ow.map and ow.map.id
  local md = id and G.data and G.data.maps and G.data.maps[id]
  local wb = (md and md.width) or (ow.map and ow.map.width) or 0
  local hb = (md and md.height) or (ow.map and ow.map.height) or 0
  return wb * 2, hb * 2
end

-- Which cells on an edge are a REAL crossing. A gen1 connection covers only
-- part of an edge, and stepping off it reads the NEIGHBOUR strip's tile:
-- land on a solid tile and you bump exactly like a wall. A seam-blind BFS
-- returned the first reachable edge cell, so Viridian's south walk marched
-- to (3,17) and pressed down 8x into a wall ("stepped down at gap but no
-- map change"). Mirrors OverworldState:connectionLanding, clamp included.
local COMPASS = { up = "north", down = "south", left = "west", right = "east" }
local function landing_ok(G, dir, x, y)
  local ow = G.overworld
  local md = ow and ow.map and ow.map.def
  local conn = md and md.connections and md.connections[COMPASS[dir]]
  if not conn then return false end
  local dest = G.data and G.data.maps and G.data.maps[conn.map]
  if not dest then return false end
  local ts = G.data.tilesets and G.data.tilesets[dest.tileset]
  if not ts then return false end
  local destW, destH = dest.width * 2, dest.height * 2
  local off = (conn.offset or 0) * 2
  local lx, ly
  if dir == "up" then lx, ly = x - off, destH - 1
  elseif dir == "down" then lx, ly = x - off, 0
  elseif dir == "left" then lx, ly = destW - 1, y - off
  else lx, ly = 0, y - off end
  lx = math.max(0, math.min(destW - 1, lx))
  ly = math.max(0, math.min(destH - 1, ly))
  local okp, res = pcall(function()
    local Map = require("src.world.Map")
    return Map.defPassable(dest, ts, lx, ly,
                           ow.player and ow.player.surfing)
  end)
  -- never let a probe failure make a real seam look shut
  if not okp then return true end
  return res and true or false
end

local function bfs_to_edge(G, dir)
  local Collision = require("src.world.Collision")
  local ow = G.overworld
  local p = ow.player
  local W, H = map_dims_cells(G)
  local on_edge = {
    up = function(_, y) return y <= 0 end,
    down = function(_, y) return H > 0 and y >= H - 1 end,
    left = function(x, _) return x <= 0 end,
    right = function(x, _) return W > 0 and x >= W - 1 end,
  }
  local hit = on_edge[dir]
  if not hit then return nil end
  if hit(p.cellX, p.cellY) and landing_ok(G, dir, p.cellX, p.cellY) then
    return p.cellX, p.cellY
  end
  local key = function(x, y) return x .. "," .. y end
  local wblock = warp_block(G, -1, -1)   -- edge walks never end on a warp
  local seen = { [key(p.cellX, p.cellY)] = true }
  local queue = { { x = p.cellX, y = p.cellY } }
  local head = 1
  while queue[head] do
    local cur = queue[head]; head = head + 1
    for _, d in pairs(DIRS) do
      local nx, ny = cur.x + d[1], cur.y + d[2]
      if not seen[key(nx, ny)] and not wblock[key(nx, ny)] then
        local probe = setmetatable({ cellX = cur.x, cellY = cur.y },
                                   { __index = p })
        local dname = (d[1] == 0 and (d[2] < 0 and "up" or "down"))
                      or (d[1] < 0 and "left" or "right")
        if Collision.canMove(ow.map, ow.entities, probe, dname) then
          seen[key(nx, ny)] = true
          if hit(nx, ny) and landing_ok(G, dir, nx, ny) then
            return nx, ny
          end
          queue[#queue + 1] = { x = nx, y = ny }
        else
          local lx, ly = ledge_landing(G, ow.map, cur.x, cur.y, dname)
          if lx and not seen[key(lx, ly)] and not wblock[key(lx, ly)] then
            seen[key(lx, ly)] = true
            if hit(lx, ly) then return lx, ly end
            queue[#queue + 1] = { x = lx, y = ly }
          end
        end
      end
    end
  end
  return nil
end

local OPS = {}

-- NEW GAME, explicitly. U.newGame taps A on the title menu assuming NEW
-- GAME is the first row — true only when no save exists, and its own
-- comment says so. With a save present that A picks CONTINUE, so a
-- "fresh" run silently resumed (pure1 began in Cerulean with a L24
-- Wartortle, trying to walk downstairs in Red's house). Select the row by
-- NAME instead.
function OPS.new_game(G)
  U.wait(5)
  U.tap(G, "start"); U.wait(10)       -- skip the intro movie
  U.tap(G, "a");     U.wait(8)        -- title -> menu
  local menu = G.stack:top()
  if menu and menu.items and menu.index then
    local row
    for i, it in ipairs(menu.items) do
      local label = tostring(it.label or ""):upper()
      if label:find("NEW") then row = i break end
    end
    if row then
      for _ = 1, 8 do
        local t = G.stack:top()
        if not (t and t.index) or t.index == row then break end
        U.tap(G, t.index > row and "up" or "down"); U.wait(3)
      end
    end
  end
  U.tap(G, "a"); U.wait(10)
  for _ = 1, 400 do                    -- Oak speech + naming (defaults)
    U.tap(G, "a"); U.wait(2)
    if G.overworld and G.stack:top() == G.overworld then break end
  end
  U.wait(10)
  local id = G.overworld and G.overworld.map and G.overworld.map.id
  if id ~= "REDS_HOUSE_2F" then
    return false, "new game did not start (on " .. tostring(id)
      .. ") — did it CONTINUE instead?"
  end
  return true, "new game"
end

function OPS.tap(G, c)
  U.tap(G, c.btn or "a")
  return true
end

function OPS.mash_a(G, c)
  for _ = 1, (c.times or 10) do U.tap(G, "a") U.wait(2) end
  return true
end

function OPS.wait(G, c) U.wait(c.frames or 30) return true end

function OPS.walk(G, c)
  if not (G.overworld and G.stack:top() == G.overworld) then
    return false, "not in overworld"
  end
  return walk(G, c.dir, c.steps or 1)
end

function OPS.walk_to(G, c)
  if not (G.overworld and G.stack:top() == G.overworld) then
    return false, "not in overworld"
  end
  local ow = G.overworld
  local startMap = ow.map and ow.map.id
  local p = ow.player
  for _ = 1, (c.max_steps or 200) do
    if G.stack:top() ~= ow then
      return true, "interrupted (battle or script)"
    end
    if (ow.map and ow.map.id) ~= startMap then
      return true, "warped to " .. tostring(ow.map and ow.map.id)
    end
    if p.cellX == c.x and p.cellY == c.y then return true end
    local dir, why = bfs_dir(G, c.x, c.y)
    if not dir then
      return why == "arrived", why
    end
    local moved
    for attempt = 1, 3 do
      moved = walk(G, dir, 1)
      if moved then break end
      U.wait(16)               -- transient NPC block: let them wander off
    end
    if not moved then
      return false, ("blocked at (%d,%d) heading %s"):format(
        p.cellX, p.cellY, dir)
    end
  end
  return false, "step budget exhausted"
end

-- Take a warp/door/stairs. Walk onto the warp tile, then step THROUGH it
-- (door mats and edge warps fire on the step off the tile, not on arrival),
-- trying the map-edge direction first. Decision-free: the model picks which
-- warp by x,y; the executor handles the walk-and-step-through. This is the
-- door + map-transition primitive walk_to (in-map only) can't cover.
function OPS.use_warp(G, c)
  if not (G.overworld and G.stack:top() == G.overworld) then
    return false, "not in overworld"
  end
  local ow = G.overworld
  local startMap = ow.map and ow.map.id
  local p = ow.player
  if not (c.x and c.y) then return false, "use_warp needs x,y" end

  local function attempt(x, y)
    if p.cellX ~= x or p.cellY ~= y then
      OPS.walk_to(G, { x = x, y = y, max_steps = c.max_steps or 120 })
      if (ow.map and ow.map.id) ~= startMap then return true end
    end
    if p.cellX ~= x or p.cellY ~= y then return false, "unreachable" end
    -- step through: prefer whichever edge the tile sits on (cell dims)
    local w, h = map_dims_cells(G)
    if w == 0 then w = 99 end
    if h == 0 then h = 99 end
    local order = {}
    if y >= h - 1 then order = {"down","left","right","up"}
    elseif y <= 0 then order = {"up","left","right","down"}
    elseif x <= 0 then order = {"left","up","down","right"}
    elseif x >= w - 1 then order = {"right","up","down","left"}
    else order = {"down","up","left","right"} end
    for _, dir in ipairs(order) do
      table.insert(G.input.pressQueue, dir)
      G.input.state[dir] = true
      for _ = 1, 30 do
        coroutine.yield()
        if (ow.map and ow.map.id) ~= startMap then
          G.input.state[dir] = false
          return true
        end
      end
      G.input.state[dir] = false
      U.wait(4)
    end
    return false, "no fire"
  end

  -- Doorway warps come in 2-tile pairs and one side can be walled off
  -- (VIRIDIAN_FOREST_SOUTH_GATE: (4,0) is unreachable, only (5,0) enters
  -- the forest — the in-tree route uses 5,0). The model picks the DOOR;
  -- which tile of the pair is walkable is mechanics, so on failure retry
  -- the adjacent twin with the same destination.
  local tiles = { { x = c.x, y = c.y } }
  local md = startMap and G.data and G.data.maps and G.data.maps[startMap]
  if md and md.warps then
    local dest
    for _, w in ipairs(md.warps) do
      if w.x == c.x and w.y == c.y then dest = w.destMap break end
    end
    if dest then
      for _, w in ipairs(md.warps) do
        if w.destMap == dest
           and math.abs(w.x - c.x) + math.abs(w.y - c.y) == 1 then
          tiles[#tiles + 1] = { x = w.x, y = w.y }
        end
      end
    end
  end
  local reached_any = false
  for _, t in ipairs(tiles) do
    local ok, w = attempt(t.x, t.y)
    if ok or (ow.map and ow.map.id) ~= startMap then return true, "warped" end
    reached_any = reached_any or (w == "no fire")
  end
  if reached_any then
    return false, "stepped through but no warp fired"
  end
  return false, "couldn't reach the warp tile"
end

-- Cross to the connected map in a direction (north/south/east/west). Finds
-- the walkable gap in that edge (BFS), walks to it, and steps off the seam to
-- trigger the connection. This is how you travel between routes/towns when
-- there is no door warp. Decision-free: the model picks the direction.
function OPS.cross(G, c)
  if not (G.overworld and G.stack:top() == G.overworld) then
    return false, "not in overworld"
  end
  local dmap = { north = "up", south = "down", west = "left", east = "right" }
  local cmap = { up = "north", down = "south", left = "west", right = "east" }
  local dir = dmap[c.dir] or c.dir
  if not DIRS[dir] then return false, "cross needs dir north/south/east/west" end
  local ow = G.overworld
  local startMap = ow.map and ow.map.id
  local p = ow.player
  -- A map with no connection that way (indoor maps have none at all) has no
  -- edge to cross: fail fast with the real reason. "no reachable north edge"
  -- reads like a pathing problem and sent the model chasing phantom paths
  -- when a subgoal started inside OAKS_LAB (brock7 go_to_route_1).
  local md = startMap and G.data and G.data.maps and G.data.maps[startMap]
  if md and not (md.connections and md.connections[cmap[dir]]) then
    local outs = {}
    if md.connections then
      for d in pairs(md.connections) do outs[#outs + 1] = d end
    end
    return false, ("%s has no %s edge — %s"):format(
      tostring(startMap), cmap[dir],
      #outs > 0 and ("its edges go " .. table.concat(outs, "/"))
        or "it is indoors; exit through a door/stairs with use_warp")
  end
  -- NPC-robust: a wandering NPC can sit on the seam gap or block the only
  -- corridor, making the edge transiently unreachable. Re-BFS across a few
  -- rounds with settle time instead of failing out (the Viridian bounce came
  -- from failing here and the model falling back to blind walk).
  -- Moving toward some edges TRIGGERS a cutscene that carries you across on
  -- its own (Pallet north -> the Oak escort into the lab). If that fires,
  -- ride it: press A through its text and wait for the map to change, rather
  -- than reporting "stuck". Returns true when the escort delivers us.
  local function ride_cutscene()
    for _ = 1, 40 do
      if (ow.map and ow.map.id) ~= startMap then return true end
      local top = G.stack:top()
      if top and top.pages and top.pageIndex then
        U.tap(G, "a"); U.wait(3)          -- cutscene dialogue
      elseif G.overworld and top == ow
          and not (ow.runner and ow.runner.isRunning
                   and ow.runner:isRunning())
          and not (ow.player and ow.player.moving) then
        return false                       -- free control, no cutscene running
      else
        U.wait(4)                          -- script moving us / transition
      end
    end
    return (ow.map and ow.map.id) ~= startMap
  end

  local ex, ey
  for round = 1, 4 do
    ex, ey = bfs_to_edge(G, dir)
    if ex then break end
    U.wait(40)
    if G.stack:top() ~= ow then
      if ride_cutscene() then return true, "crossed (cutscene)" end
    end
  end
  if not ex then
    if ride_cutscene() then return true, "crossed (cutscene)" end
    -- the connection exists (the fail-fast above passed) but BFS can't walk
    -- to the seam: blocked terrain splits the map (ROUTE_2's north half is
    -- only reachable through Viridian Forest)
    local dest = md and md.connections and md.connections[cmap[dir]]
    return false, ("the %s seam of %s (to %s) cannot be walked to from "
      .. "here — terrain blocks it; the way there goes through a door or "
      .. "another map"):format(cmap[dir], tostring(startMap),
                               tostring(dest and dest.map or "?"))
  end
  if p.cellX ~= ex or p.cellY ~= ey then
    for round = 1, 3 do
      OPS.walk_to(G, { x = ex, y = ey, max_steps = c.max_steps or 200 })
      if (ow.map and ow.map.id) ~= startMap then
        return true, "crossed (mid-walk)"
      end
      -- a cutscene may have interrupted the walk (Oak's "Hey! Wait!") — ride
      -- it out before deciding we're stuck.
      if G.stack:top() ~= ow or (ow.player and ow.player.moving) then
        if ride_cutscene() then return true, "crossed (cutscene)" end
      end
      if p.cellX == ex and p.cellY == ey then break end
      U.wait(30)
      local nx, ny = bfs_to_edge(G, dir)   -- NPC moved: retarget the gap
      if nx then ex, ey = nx, ny end
    end
    if p.cellX ~= ex or p.cellY ~= ey then
      if ride_cutscene() then return true, "crossed (cutscene)" end
      return false, ("couldn't reach %s edge gap (%d,%d), stuck at (%d,%d)")
        :format(tostring(c.dir), ex, ey, p.cellX, p.cellY)
    end
  end
  -- step off the seam repeatedly until the map changes
  for _ = 1, 8 do
    if (ow.map and ow.map.id) ~= startMap then return true, "crossed" end
    table.insert(G.input.pressQueue, dir)
    G.input.state[dir] = true
    for _ = 1, 20 do
      coroutine.yield()
      if (ow.map and ow.map.id) ~= startMap then
        G.input.state[dir] = false; return true, "crossed"
      end
    end
    G.input.state[dir] = false
    U.wait(3)
  end
  if (ow.map and ow.map.id) ~= startMap then return true, "crossed" end
  return false, ("stepped %s at gap (%d,%d) but no map change")
    :format(dir, p.cellX, p.cellY)
end

-- ------------------------------------------------------------ shop/bag UI
-- Menu-driving helpers for the shop and bag flows, ported from the in-tree
-- route driver (tests/drivers/route.lua): same stack-shape predicates
-- (list rows carry .value, menus .onSelect, quantity boxes .qty, bare
-- choices .index with no .items), and its traps — B is the ONLY safe key
-- to close a shop (A on the buy list is a purchase), and success is
-- verified against the BAG, not the menu flow.
local function ui_top(G) return G.stack:top() end
local function ui_rows(G) local t = ui_top(G) return t and t.items end
local function ui_is_menu(G)
  local r = ui_rows(G)
  return r ~= nil and r[1] ~= nil and r[1].onSelect ~= nil
end
local function ui_is_list(G)
  local r = ui_rows(G)
  return r ~= nil and r[1] ~= nil and r[1].value ~= nil
end
local function ui_is_qty(G)
  local t = ui_top(G) return t ~= nil and t.qty ~= nil
end
local function ui_is_choice(G)
  local t = ui_top(G) return t ~= nil and t.index ~= nil and t.items == nil
end
local function ui_press_until(G, pred, btn, tries)
  for _ = 1, tries or 60 do
    if pred(G) then return true end
    U.tap(G, btn); U.wait(4)
  end
  return pred(G)
end
local function ui_cursor_to(G, field, want, tries)
  for _ = 1, tries or 40 do
    local t = ui_top(G)
    if not t or t[field] == want then return t ~= nil end
    U.tap(G, t[field] > want and "up" or "down"); U.wait(3)
  end
  local t = ui_top(G)
  return t ~= nil and t[field] == want
end
local function ui_qty_to(G, want)
  for _ = 1, 120 do
    local t = ui_top(G)
    if not t or not t.qty then return false end
    if t.qty == want then return true end
    U.tap(G, t.qty < want and "up" or "down"); U.wait(3)
  end
  return false
end
local function ui_close_shop(G)
  for _ = 1, 40 do
    if not (ui_is_list(G) or ui_is_qty(G) or ui_is_choice(G)
            or ui_is_menu(G)) then
      return true
    end
    U.tap(G, "b"); U.wait(6)
  end
  return false
end
local function ui_back_out(G)
  for _ = 1, 40 do
    local t = ui_top(G)
    if t == G.overworld or (t and (t.enemy or t.kind)) then return true end
    U.tap(G, "b"); U.wait(6)
  end
  return false
end
local function bag_count(G, id)
  return ((G.save and G.save.inventory) or {})[id] or 0
end

-- Buy c.count of c.item from this mart's clerk. Decision-free: the model
-- picks WHAT and HOW MANY; the menu driving is mechanics.
local function ui_shop_up(G) return ui_is_menu(G) or ui_is_list(G) end

function OPS.buy(G, c)
  if not (c.item and c.count) then return false, "buy needs item, count" end
  -- TARGET semantics: own c.count total, not "c.count more". Escalation
  -- rounds carry state forward and re-propose their macros — with buy-more
  -- semantics every retry SPENT REAL MONEY (brock31 walked into Pewter
  -- with 127 of 3000 left and could not afford a single POTION).
  local have0 = bag_count(G, c.item)
  if have0 >= c.count then
    return true, ("already have %s x%d"):format(c.item, have0)
  end
  -- AFFORDABILITY FIRST (the shop-price sticker is on the shelf, pamphlet-
  -- tier): every observed "shop failure" was really an empty wallet, and
  -- walking the whole menu to discover that wasted rounds and hid the real
  -- cause. Report the arithmetic instead.
  local money = (G.save and G.save.money) or 0
  local price = ((G.data and G.data.items and G.data.items[c.item]) or {}).price
  if price and price > 0 then
    local afford = math.floor(money / price)
    if afford < 1 then
      return false, ("cannot afford %s: it costs %d and you have %d")
        :format(c.item, price, money)
    end
    if afford < (c.count - have0) then
      -- buy what the wallet allows rather than failing outright; the
      -- QuantityBox caps at .max anyway, this just makes it intentional
      c = { item = c.item, count = have0 + afford, max_steps = c.max_steps }
    end
  end
  -- Tolerate an already-open shop: the model often interacts the clerk
  -- itself first (its macro left the greeting/menu on the stack and the
  -- old strict not-in-overworld check failed the whole purchase). Ride
  -- whatever dialog is up toward the BUY/SELL menu; only run our own
  -- clerk interaction from clean overworld.
  if G.overworld and G.stack:top() ~= G.overworld then
    if not ui_shop_up(G) then
      ui_press_until(G, ui_shop_up, "a", 20)
    end
    if not ui_shop_up(G) then
      ui_back_out(G)
    end
  end
  if G.overworld and G.stack:top() == G.overworld then
    local ow = G.overworld
    local clerk
    for _, npc in ipairs(ow.npcs or {}) do
      local nm = ((npc.def or {}).name or ""):upper()
      if nm:find("CLERK") or nm:find("CASHIER") then clerk = npc break end
    end
    if not clerk then return false, "no shop clerk on this map" end
    if not OPS.interact(G, { x = clerk.cellX, y = clerk.cellY }) then
      return false, "couldn't reach the clerk"
    end
    if not ui_press_until(G, ui_is_menu, "a", 60) then
      ui_back_out(G)
      return false, "shop menu never opened"
    end
  end
  if ui_is_menu(G) then
    ui_cursor_to(G, "index", 1)                   -- BUY
    U.tap(G, "a"); U.wait(10)
  end
  if not ui_press_until(G, ui_is_list, "a", 30) then
    ui_close_shop(G); ui_back_out(G)
    return false, "buy list never opened"
  end
  local idx, sold = nil, {}
  for i, row in ipairs(ui_rows(G)) do
    sold[#sold + 1] = tostring(row.value)
    if row.value == c.item then idx = i break end
  end
  if not idx then
    ui_close_shop(G); ui_back_out(G)
    -- name the actual stock so the caller can adapt instead of retrying
    -- blind (Viridian famously sells no POTION at all)
    return false, c.item .. " is not sold here — this mart sells: "
      .. table.concat(sold, ", ")
  end
  if not ui_cursor_to(G, "index", idx) then
    ui_close_shop(G); ui_back_out(G)
    return false, "cursor stuck on the buy list"
  end
  -- the price text ("That'll be N. How many?") pages BEFORE the quantity
  -- box: ride it with A instead of racing it with one fixed wait
  U.tap(G, "a"); U.wait(6)
  if not ui_press_until(G, ui_is_qty, "a", 20) then
    ui_close_shop(G); ui_back_out(G)
    return false, ("no quantity box opened (money: %d — not enough?)")
      :format((G.save and G.save.money) or 0)
  end
  local want = math.min(c.count - have0, ui_top(G).max or c.count)
  if not ui_qty_to(G, want) then
    ui_close_shop(G); ui_back_out(G)
    return false, "couldn't set the quantity"
  end
  U.tap(G, "a"); U.wait(6)
  if ui_is_choice(G) then                          -- "That'll be X. OK?"
    ui_cursor_to(G, "index", 1)
    U.tap(G, "a"); U.wait(10)
  end
  ui_press_until(G, ui_is_list, "a", 20)           -- clear purchase text
  local have = bag_count(G, c.item)
  ui_close_shop(G)
  ui_back_out(G)
  if have <= have0 then
    return false, ("purchase did not reach the bag (money %d, bag had %d) "
      .. "— no room, or the shop refused"):format(
      (G.save and G.save.money) or 0, have0)
  end
  return true, ("bought: %s x%d in bag, %d money left"):format(
    c.item, have, (G.save and G.save.money) or 0)
end

-- Use a bag item in the field (START -> ITEM -> item -> USE -> party
-- slot). Healing items target c.slot (default the lead).
function OPS.use_item(G, c)
  if not (G.overworld and G.stack:top() == G.overworld) then
    return false, "not in overworld"
  end
  if not c.item then return false, "use_item needs item" end
  if bag_count(G, c.item) < 1 then
    return false, "no " .. c.item .. " in the bag"
  end
  U.tap(G, "start"); U.wait(8)
  local menu = ui_top(G)
  if not (menu and menu.screenId == "StartMenu") then
    ui_back_out(G); return false, "start menu never opened"
  end
  local itemRow
  for i, it in ipairs(menu.items or {}) do
    if it.label == "ITEM" then itemRow = i break end
  end
  if not itemRow or not ui_cursor_to(G, "index", itemRow) then
    ui_back_out(G); return false, "no ITEM row"
  end
  U.tap(G, "a"); U.wait(10)
  local bag = ui_top(G)
  if not (bag and bag.screenId == "BagMenu") then
    ui_back_out(G); return false, "bag never opened"
  end
  local bagRow
  for i, r in ipairs(bag.items or {}) do
    if r.value == c.item then bagRow = i break end
  end
  if not bagRow or not ui_cursor_to(G, "index", bagRow) then
    ui_back_out(G); return false, c.item .. " not in the bag list"
  end
  U.tap(G, "a"); U.wait(8)
  if ui_is_menu(G) or ui_is_choice(G) then         -- USE/TOSS -> USE
    ui_cursor_to(G, "index", 1)
    U.tap(G, "a"); U.wait(8)
  end
  local pm
  for _ = 1, 20 do                                 -- ride to the party picker
    pm = ui_top(G)
    if pm and pm.screenId == "PartyMenu" then break end
    U.tap(G, "a"); U.wait(6)
  end
  pm = ui_top(G)
  if pm and pm.screenId == "PartyMenu" then
    ui_cursor_to(G, "index", c.slot or 1)
    U.tap(G, "a"); U.wait(10)
  end
  for _ = 1, 15 do                                 -- "recovered HP!" text
    local t = ui_top(G)
    if not (t and t.pages) then break end
    U.tap(G, "a"); U.wait(6)
  end
  ui_back_out(G)
  return true, "used " .. c.item
end

-- Level-grind primitive: stand in this map's wild grass and pace until an
-- encounter interrupts (or the step budget runs out). The EXECUTOR fights
-- each battle with the subgoal's policy and re-sends this op — the same
-- battle-retry machinery as traversal — until the plan's done_when (a
-- level gate) holds. Decision-free: the model decides WHERE (which map)
-- and the plan decides UNTIL; walking into grass is mechanics.
function OPS.grind(G, c)
  if not (G.overworld and G.stack:top() == G.overworld) then
    return false, "not in overworld"
  end
  local Collision = require("src.world.Collision")
  local ow = G.overworld
  local p = ow.player
  local map = ow.map
  if not (map and map.isGrassCell) then return false, "no map" end
  local function dirname_of(d)
    return (d[1] == 0 and (d[2] < 0 and "up" or "down"))
      or (d[1] < 0 and "left" or "right")
  end
  -- stand in grass: BFS to the nearest reachable grass cell if not on one
  if not map:isGrassCell(p.cellX, p.cellY) then
    local key = function(x, y) return x .. "," .. y end
    local seen = { [key(p.cellX, p.cellY)] = true }
    local queue = { { x = p.cellX, y = p.cellY } }
    local head, gx, gy = 1, nil, nil
    while queue[head] and not gx do
      local cur = queue[head]; head = head + 1
      for _, d in pairs(DIRS) do
        local nx, ny = cur.x + d[1], cur.y + d[2]
        if not seen[key(nx, ny)] then
          local probe = setmetatable({ cellX = cur.x, cellY = cur.y },
                                     { __index = p })
          if Collision.canMove(map, ow.entities, probe, dirname_of(d)) then
            seen[key(nx, ny)] = true
            if map:isGrassCell(nx, ny) then gx, gy = nx, ny break end
            queue[#queue + 1] = { x = nx, y = ny }
          end
        end
      end
    end
    if not gx then return false, "no reachable grass on this map" end
    OPS.walk_to(G, { x = gx, y = gy, max_steps = c.max_steps or 200 })
    if G.stack:top() ~= ow then return true, "battle en route to grass" end
    if not map:isGrassCell(p.cellX, p.cellY) then
      return false, "couldn't reach the grass"
    end
  end
  -- pace: step between adjacent grass cells (each step rolls the wild RNG)
  local BACK = { left = "right", right = "left", up = "down", down = "up" }
  for _ = 1, (c.steps or 80) do
    if G.stack:top() ~= ow then return true, "encounter" end
    local moved = false
    for _, dn in ipairs({ "left", "right", "up", "down" }) do
      local d = DIRS[dn]
      if map:isGrassCell(p.cellX + d[1], p.cellY + d[2])
         and Collision.canMove(map, ow.entities, p, dn) then
        walk(G, dn, 1)
        moved = true
        break
      end
    end
    if not moved then
      -- isolated grass cell: step off and back on (re-entry rolls the RNG)
      for _, dn in ipairs({ "left", "right", "up", "down" }) do
        if Collision.canMove(map, ow.entities, p, dn) then
          walk(G, dn, 1)
          if G.stack:top() ~= ow then return true, "encounter" end
          walk(G, BACK[dn], 1)
          moved = true
          break
        end
      end
      if not moved then return false, "boxed in on the grass" end
    end
  end
  if G.stack:top() ~= ow then return true, "encounter" end
  return true, "paced without an encounter (re-send to keep grinding)"
end

-- List-menu navigation: any stack state exposing a numeric cursor `index`.
-- Moves the cursor to c.index, then A (or just positions with c.press=false).
function OPS.menu(G, c)
  local top = G.stack:top()
  if not (top and type(top.index) == "number") then
    return false, "no list menu on top"
  end
  local target = c.index or 1
  for _ = 1, 24 do
    if top.index == target then break end
    U.tap(G, top.index > target and "up" or "down")
    U.wait(2)
  end
  if top.index ~= target then
    return false, "cursor did not reach " .. tostring(target)
  end
  if c.press ~= false then
    U.tap(G, "a")
    U.wait(4)
  end
  return true
end

-- Battle executors. Grid is row-major 2x2: FIGHT=1, PKMN=2, ITEM=3, RUN=4.
-- These are decision-free: the MODEL picks the move index / target slot
-- (CLAIM_RULES_v1 — battle policy is the model's).
-- The battle menu is a 2x2 grid: FIGHT ITEM / PKMN RUN (1..4).
-- This used to tap LEFT whenever the columns differed — but going from
-- FIGHT (col 0) to RUN (col 1) needs RIGHT, and left at column 0 does
-- nothing, so the cursor never moved and RUN was unreachable. Fleeing
-- silently failed 14422 times across 6984 battles (exactly one battle
-- ever ended on a run) while battle_move kept working, because it only
-- ever asks for index 1, which is already selected. Move on the axis
-- that is actually wrong, in the direction that actually closes it.
local function battle_menu_to(G, battle, want)
  for _ = 1, 8 do
    if battle.menuIndex == want then return true end
    local i, w = battle.menuIndex - 1, want - 1
    local col, wcol = i % 2, w % 2
    local row, wrow = math.floor(i / 2), math.floor(w / 2)
    if col ~= wcol then
      U.tap(G, wcol > col and "right" or "left")
    elseif row ~= wrow then
      U.tap(G, wrow > row and "down" or "up")
    end
    U.wait(2)
  end
  return battle.menuIndex == want
end

local function in_battle(G)
  local b = G.stack:top()
  return b and (b.enemy or b.kind) and b or nil
end

function OPS.battle_move(G, c)
  local b = in_battle(G)
  if not b then return false, "not in battle" end
  local want = c.index or 1
  -- advance any pending text until the action menu is up
  for _ = 1, 40 do
    if b.phase == "menu" then break end
    U.tap(G, "a"); U.wait(3)
  end
  if b.phase ~= "menu" then return false, "menu never appeared" end
  if not battle_menu_to(G, b, 1) then return false, "couldn't reach FIGHT" end
  U.tap(G, "a"); U.wait(4)
  if b.phase ~= "moveSelect" then
    return false, "no moveSelect (disabled/struggle?)"
  end
  for _ = 1, 8 do
    if b.moveIndex == want then break end
    U.tap(G, b.moveIndex > want and "up" or "down"); U.wait(2)
  end
  if b.moveIndex ~= want then return false, "cursor missed move" end
  U.tap(G, "a"); U.wait(3)
  -- play out the turn's text back to the next decision or battle end
  for _ = 1, 120 do
    local nb = in_battle(G)
    if not nb then return true, "battle ended" end
    if nb.phase == "menu" or nb.phase == "moveSelect" then return true end
    U.tap(G, "a"); U.wait(3)
  end
  return true, "turn resolved (timeout advancing text)"
end

-- ORACLE PROBE: engine-truth damage per move vs the current foe, computed
-- with roll stand-ins that consume NO game RNG (route.lua's midRng pattern).
-- This is the oracle's ground truth (CLAIM_RULES: the referee may use engine
-- oracles; the MODEL's observation must not — battle_probe is never in the
-- model-facing obs path). Result is stashed for the next observation.
function OPS.battle_probe(G)
  local b = in_battle(G)
  if not b then return false, "not in battle" end
  if not (b.player and b.enemy and b.computeDamage) then
    return false, "battle has no damage model here"
  end
  local mid = function(a, z) return math.floor((a + z) / 2) end
  local lo = function(a, _) return a end
  local hi = function(_, z) return z end
  local function dmg(probe, rng)
    local ok, d, info = pcall(function()
      return b:computeDamage(b.player, b.enemy, probe, { rng = rng })
    end)
    if ok and type(d) == "number" then return d, info end
    return nil, nil
  end
  local foe_hp = (b.enemy.shownHP)
    or (b.enemy.mon and b.enemy.mon.hp)
  local out = {}
  for i, mv in ipairs(b.player.curMoves or {}) do
    local def = b:moveDef(mv)
    if def then
      local probe = setmetatable({ id = mv.id }, { __index = def })
      local dm, info = dmg(probe, mid)
      out[#out + 1] = {
        index = i, id = mv.id, pp = mv.pp,
        dmg_mid = dm, dmg_min = dmg(probe, lo), dmg_max = dmg(probe, hi),
        type_mult = info and info.typeMult,
        ko_min = (dmg(probe, lo) or 0) >= (foe_hp or 1e9),   -- guaranteed
        ko_mid = (dm or 0) >= (foe_hp or 1e9),
      }
    end
  end
  last_probe = { foe_hp = foe_hp, moves = out }
  return true, "probed " .. #out .. " moves"
end

function OPS.battle_run(G)
  local b = in_battle(G)
  if not b then return false, "not in battle" end
  for _ = 1, 40 do
    if b.phase == "menu" then break end
    U.tap(G, "a"); U.wait(3)
  end
  if not battle_menu_to(G, b, 4) then return false, "couldn't reach RUN" end
  U.tap(G, "a"); U.wait(3)
  for _ = 1, 30 do
    if not in_battle(G) then return true, "fled" end
    U.tap(G, "a"); U.wait(3)
  end
  return true, "run attempted"
end

function OPS.battle_switch(G, c)
  local b = in_battle(G)
  if not b then return false, "not in battle" end
  for _ = 1, 40 do
    if b.phase == "menu" then break end
    U.tap(G, "a"); U.wait(3)
  end
  if not battle_menu_to(G, b, 2) then return false, "couldn't reach PKMN" end
  U.tap(G, "a"); U.wait(4)
  local slot = c.slot or 1
  local top = G.stack:top()
  if top and type(top.index) == "number" then
    for _ = 1, 12 do
      if top.index == slot then break end
      U.tap(G, top.index > slot and "up" or "down"); U.wait(2)
    end
    U.tap(G, "a"); U.wait(3)
    U.tap(G, "a"); U.wait(3)   -- confirm SWITCH on the submenu
  end
  for _ = 1, 60 do
    local nb = in_battle(G)
    if nb and (nb.phase == "menu" or nb.phase == "moveSelect") then
      return true
    end
    if not nb then return true, "battle ended" end
    U.tap(G, "a"); U.wait(3)
  end
  return true
end

-- Walk adjacent to a target tile/object, face it, and press A. Decision-free
-- executor: the model picks WHAT to interact with (by x,y or object name);
-- the mechanical walk-adjacent-face-press is execution. Unblocks Poke Balls,
-- NPCs, signs — anything the object list surfaces.
function OPS.interact(G, c)
  if not (G.overworld and G.stack:top() == G.overworld) then
    return false, "not in overworld"
  end
  local ow = G.overworld
  local tx, ty = c.x, c.y
  if c.name and not tx then
    for _, npc in ipairs(ow.npcs or {}) do
      if (npc.def or {}).name == c.name then tx, ty = npc.cellX, npc.cellY end
    end
    if not tx then return false, "object '" .. c.name .. "' not visible" end
  end
  if not tx then return false, "interact needs x,y or name" end
  -- stand on an orthogonally adjacent walkable tile, then face the target.
  -- Counter NPCs (Center nurse, mart clerk) have NO walkable adjacent tile:
  -- gen1 talks ACROSS the counter, so the distance-2 spots facing the
  -- target are valid stands too (adjacent ones stay preferred) — but ONLY
  -- when no other object sits on the tile between, or the press talks to
  -- THAT instead (a distance-2 stand at the Squirtle ball pressed A into
  -- the Charmander ball and picked the wrong starter).
  local function occupied(x, y)
    for _, npc in ipairs(ow.npcs or {}) do
      if npc.cellX == x and npc.cellY == y then return true end
    end
    return false
  end
  local adj = { {tx, ty + 1, "up"}, {tx, ty - 1, "down"},
                {tx - 1, ty, "right"}, {tx + 1, ty, "left"} }
  local over = { {tx, ty + 2, "up", tx, ty + 1},
                 {tx, ty - 2, "down", tx, ty - 1},
                 {tx - 2, ty, "right", tx - 1, ty},
                 {tx + 2, ty, "left", tx + 1, ty} }
  for _, o in ipairs(over) do
    if not occupied(o[4], o[5]) then
      adj[#adj + 1] = { o[1], o[2], o[3] }
    end
  end
  local p = ow.player
  local function press_from_adjacent()
    for _, a in ipairs(adj) do
      if p.cellX == a[1] and p.cellY == a[2] then
        if p.facing ~= a[3] then U.tap(G, a[3]); U.wait(3) end
        U.tap(G, "a"); U.wait(8)
        -- verify something opened: a distance-2 press with no counter
        -- between hits empty air and must not count as an interaction
        return G.stack:top() ~= ow
      end
    end
    return false
  end
  -- retry across ambient-dialog interruptions (e.g. the lab rival's timed
  -- "fed up with waiting"): clear any text box, then approach and press.
  for _ = 1, 4 do
    for _ = 1, 12 do          -- clear any pending text
      if G.stack:top() == ow then break end
      U.tap(G, "a"); U.wait(3)
    end
    if G.stack:top() ~= ow then return false, "stuck in a menu/dialog" end
    if press_from_adjacent() then return true end
    for _, a in ipairs(adj) do
      OPS.walk_to(G, { x = a[1], y = a[2], max_steps = 60 })
      if G.stack:top() == ow and p.cellX == a[1] and p.cellY == a[2] then
        break
      end
    end
    if press_from_adjacent() then return true end
  end
  return false, "no reachable tile adjacent to target"
end

-- Use a bag item DURING battle (action grid slot 3 -> bag list -> item ->
-- party target). Costs the turn; that is the caller's trade to make.
function OPS.battle_item(G, c)
  local b = in_battle(G)
  if not b then return false, "not in battle" end
  if not c.item then return false, "battle_item needs item" end
  if bag_count(G, c.item) < 1 then
    return false, "no " .. c.item .. " in the bag"
  end
  for _ = 1, 40 do                                 -- reach the action menu
    if b.phase == "menu" then break end
    U.tap(G, "a"); U.wait(3)
  end
  if b.phase ~= "menu" then return false, "no battle action menu" end
  if not battle_menu_to(G, b, 3) then return false, "couldn't reach ITEM" end
  U.tap(G, "a"); U.wait(6)
  if not ui_press_until(G, ui_is_list, "a", 40) then
    ui_back_out(G); return false, "battle bag never opened"
  end
  local idx
  for i, row in ipairs(ui_rows(G) or {}) do
    if row.value == c.item then idx = i break end
  end
  if not idx or not ui_cursor_to(G, "index", idx) then
    ui_back_out(G); return false, c.item .. " not in the battle bag"
  end
  U.tap(G, "a"); U.wait(10)
  local pm = ui_top(G)                             -- party target picker
  if pm and pm.onSwitch ~= nil and pm.index ~= nil then
    ui_cursor_to(G, "index", c.slot or 1)
    U.tap(G, "a"); U.wait(12)
  end
  for _ = 1, 150 do        -- drain the heal text until battle takes input
    local t = G.stack:top()
    if not (t and (t.enemy or t.kind)) then break end
    if t.phase == "menu" or t.phase == "moveSelect" then break end
    U.tap(G, "a"); U.wait(4)
  end
  return true, "used " .. c.item .. " in battle"
end

-- Throw a ball in battle (battle ITEM -> ball -> A throws outright, no
-- submenu). Rides the shake/catch text; declines the nickname prompt.
-- Decision-free: WHEN to throw is the policy's call.
function OPS.throw_ball(G, c)
  local b = in_battle(G)
  if not b then return false, "not in battle" end
  local ball = c.ball or "POKE_BALL"
  if bag_count(G, ball) < 1 then return false, "no " .. ball .. " left" end
  local party0 = #((G.save and G.save.party) or {})
  for _ = 1, 40 do
    if b.phase == "menu" then break end
    U.tap(G, "a"); U.wait(3)
  end
  if b.phase ~= "menu" then return false, "no battle action menu" end
  if not battle_menu_to(G, b, 3) then return false, "couldn't reach ITEM" end
  U.tap(G, "a"); U.wait(6)
  if not ui_press_until(G, ui_is_list, "a", 40) then
    ui_back_out(G); return false, "battle bag never opened"
  end
  local idx
  for i, row in ipairs(ui_rows(G) or {}) do
    if row.value == ball then idx = i break end
  end
  if not idx or not ui_cursor_to(G, "index", idx) then
    ui_back_out(G); return false, ball .. " not in the battle bag"
  end
  U.tap(G, "a"); U.wait(10)
  -- ride the throw: shakes text; on success a nickname YES/NO appears
  -- (answer NO) and the battle ends; on a miss the turn plays out
  for _ = 1, 200 do
    local t = G.stack:top()
    if ui_is_choice(G) then                 -- "give a nickname?"
      ui_cursor_to(G, "index", 2)           -- NO
      U.tap(G, "a"); U.wait(6)
    elseif not (t and (t.enemy or t.kind)) then
      break                                 -- battle over (caught or done)
    elseif t.phase == "menu" or t.phase == "moveSelect" then
      break                                 -- miss: battle continues
    else
      U.tap(G, "a"); U.wait(4)
    end
  end
  local caught = #((G.save and G.save.party) or {}) > party0
  return true, caught and "CAUGHT (party grew)" or
    ("threw " .. ball .. ", not caught")
end

-- Pick a party slot on a forced party menu (the lead fainted: "Use next
-- POKeMON?" -> party list). Decision-free: WHICH slot is the policy's call.
function OPS.pick_party(G, c)
  local slot = c.slot or 2
  -- ride any choice/text to the party menu (A answers YES on the prompt)
  local pm
  for _ = 1, 60 do
    pm = ui_top(G)
    if pm and pm.onSwitch ~= nil and pm.index ~= nil then break end
    if pm == G.overworld then return false, "not in a party pick" end
    U.tap(G, "a"); U.wait(4)
    pm = nil
  end
  if not pm then return false, "party menu never appeared" end
  if not ui_cursor_to(G, "index", slot) then
    return false, "couldn't reach slot " .. slot
  end
  U.tap(G, "a"); U.wait(8)
  -- ride back into the battle (or out of it)
  for _ = 1, 120 do
    local t = G.stack:top()
    if t == G.overworld then break end
    if t and (t.enemy or t.kind)
       and (t.phase == "menu" or t.phase == "moveSelect") then
      break
    end
    U.tap(G, "a"); U.wait(4)
  end
  return true, "sent out slot " .. slot
end

-- DEV DIAGNOSTIC (never in a decision path; not part of the model's eyes):
-- report this map's pathing reality — reachable-set size, which edge cells
-- are walkable/reachable, and which cells offer a ledge hop. Exists to
-- debug traversal failures like Route 4's east seam.
function OPS.map_probe(G, c)
  if not (G.overworld and G.stack:top() == G.overworld) then
    return false, "not in overworld"
  end
  local Collision = require("src.world.Collision")
  local ow, p, map = G.overworld, G.overworld.player, G.overworld.map
  local W, H = map_dims_cells(G)
  local key = function(x, y) return x .. "," .. y end
  local seen = { [key(p.cellX, p.cellY)] = true }
  local queue = { { x = p.cellX, y = p.cellY } }
  local head, hops = 1, {}
  while queue[head] do
    local cur = queue[head]; head = head + 1
    for dname, d in pairs(DIRS) do
      local nx, ny = cur.x + d[1], cur.y + d[2]
      local probe = setmetatable({ cellX = cur.x, cellY = cur.y },
                                 { __index = p })
      if Collision.canMove(map, ow.entities, probe, dname) then
        if not seen[key(nx, ny)] then
          seen[key(nx, ny)] = true
          queue[#queue + 1] = { x = nx, y = ny }
        end
      else
        local lx, ly = ledge_landing(G, map, cur.x, cur.y, dname)
        if lx then
          if #hops < 12 then
            hops[#hops + 1] = ("(%d,%d)%s->(%d,%d)"):format(
              cur.x, cur.y, dname, lx, ly)
          end
          if not seen[key(lx, ly)] then
            seen[key(lx, ly)] = true
            queue[#queue + 1] = { x = lx, y = ly }
          end
        end
      end
    end
  end
  local n = 0
  for _ in pairs(seen) do n = n + 1 end
  -- edge cells on the requested side: walkable? reachable?
  local side = c.dir or "east"
  local walk, reach = {}, {}
  for i = 0, (side == "east" or side == "west") and H - 1 or W - 1 do
    local x, y
    if side == "east" then x, y = W - 1, i
    elseif side == "west" then x, y = 0, i
    elseif side == "north" then x, y = i, 0
    else x, y = i, H - 1 end
    if map:isWalkableCell(x, y) then
      walk[#walk + 1] = x .. "," .. y
      if seen[key(x, y)] then reach[#reach + 1] = x .. "," .. y end
    end
  end
  -- tile ids around the player, to compare against the ledge rows
  local tiles = {}
  for dname, d in pairs(DIRS) do
    tiles[dname] = map:cellTile(p.cellX + d[1], p.cellY + d[2])
  end
  return true, ("dims=%dx%d pos=(%d,%d) standing_tile=%s reachable=%d | "
    .. "%s-edge walkable=[%s] reachable=[%s] | front_tiles up=%s down=%s "
    .. "left=%s right=%s | ledge_hops=%d [%s]"):format(
    W, H, p.cellX, p.cellY, tostring(map:cellTile(p.cellX, p.cellY)), n,
    side, table.concat(walk, " "), table.concat(reach, " "),
    tostring(tiles.up), tostring(tiles.down), tostring(tiles.left),
    tostring(tiles.right), #hops, table.concat(hops, " "))
end

-- Save the game via the START menu (a PLAYER action — this is the claim-
-- clean persistence, unlike dev checkpoints): START -> SAVE -> YES ->
-- ride the save text. The title's CONTINUE loads it next boot.
function OPS.save_game(G)
  if not (G.overworld and G.stack:top() == G.overworld) then
    return false, "not in overworld"
  end
  U.tap(G, "start"); U.wait(8)
  local menu = ui_top(G)
  if not (menu and menu.screenId == "StartMenu") then
    ui_back_out(G); return false, "start menu never opened"
  end
  local row
  for i, it in ipairs(menu.items or {}) do
    if it.label == "SAVE" then row = i break end
  end
  if not row or not ui_cursor_to(G, "index", row) then
    ui_back_out(G); return false, "no SAVE row"
  end
  U.tap(G, "a"); U.wait(10)
  -- Ride the player/badges/dex/time panel to its confirm. The panel is a
  -- multi-page TextBox and the YES/NO ChoiceBox only pushes once the last
  -- page finishes TYPING, which outlasted the old 30x4-frame budget (the
  -- "no confirm" failures). Never break on the StartMenu itself — it is
  -- menu-shaped too, and answering it would select POKeDEX instead.
  local confirmed = false
  for _ = 1, 200 do
    local t = ui_top(G)
    if t and t.index ~= nil and t.items == nil then confirmed = true break end
    if t == G.overworld then break end
    U.tap(G, "a"); U.wait(4)
  end
  if not confirmed then
    local t = ui_top(G)
    ui_back_out(G)
    return false, ("no save confirm (top=%s, has_items=%s)"):format(
      tostring(t and (t.screenId or "?")), tostring(t and t.items ~= nil))
  end
  -- Ground truth for "did it save" is the SAVE FILE, not the UI stack: the
  -- write happens on the "Now saving..." box's onDone, and every stack-shape
  -- heuristic I tried reported failure on saves that had demonstrably been
  -- written (a CONTINUE landed on the saved tile; slot1.lua's mtime moved).
  local function save_stamp()
    local best = 0
    for _, dir in ipairs({ "saves/red", "saves" }) do
      local ok, items = pcall(love.filesystem.getDirectoryItems, dir)
      if ok and items then
        for _, f in ipairs(items) do
          local iok, info = pcall(love.filesystem.getInfo, dir .. "/" .. f)
          if iok and info and info.type == "file" and info.modtime then
            if info.modtime > best then best = info.modtime end
          end
        end
      end
    end
    return best
  end
  local stamp0 = save_stamp()

  ui_cursor_to(G, "index", 1)                    -- YES
  U.tap(G, "a"); U.wait(10)
  -- "Now saving..." (auto, 120-frame hold, writes on its onDone) then
  -- "<NAME> saved the game!" (auto, sound + 30 frames). Both pop THEMSELVES
  -- and take no button (StartMenu.lua:70-85 / issue #765) — pressing A here
  -- would fall through onto the overworld and talk to whatever is in front.
  -- ...and when they pop, the START MENU is still underneath (SAVE was
  -- selected from it), so waiting for the overworld alone never resolved
  -- and reported failure on a save that had already been WRITTEN (proved
  -- by a CONTINUE landing on the saved tile). Wait for either, then close.
  local written = false
  for _ = 1, 400 do
    if save_stamp() > stamp0 then written = true break end
    local t = ui_top(G)
    if t == G.overworld then break end
    U.wait(4)
  end
  -- the write lands while "Now saving..." is still held (120 frames) — let
  -- the auto-boxes finish before backing out, or B presses hit a box that
  -- ignores input and the run resumes with the menu still up
  for _ = 1, 200 do
    local t = ui_top(G)
    if t == G.overworld or (t and t.screenId == "StartMenu") then break end
    U.wait(4)
  end
  -- close the StartMenu for real: a single back-out pass sometimes left it
  -- up, and the ratchet probe then failed every following subgoal with
  -- "not in overworld" (saving after each subgoal multiplied the leak)
  for _ = 1, 6 do
    if ui_top(G) == G.overworld then break end
    ui_back_out(G)
    U.tap(G, "b"); U.wait(8)
  end
  if not written then
    return false, ("save file never changed (top=%s)"):format(
      tostring((ui_top(G) or {}).screenId or "overworld"))
  end
  return true, ("saved (file written%s)"):format(
    ui_top(G) == G.overworld and "" or ", menu still open")
end

-- Checkpoint capture/restore (in-memory), for escalation's clean retries:
-- a failed macro proposal corrupts the state, so each escalation round
-- restores the subgoal's start. CLAIM_RULES: checkpoints are for development/
-- refinement, NEVER inside the record run. Blobs are keyed by token.
local saved_checkpoints = {}
function OPS.checkpoint_capture(G, c)
  local ok, Checkpoint = pcall(require, "src.core.Checkpoint")
  if not ok then return false, "no Checkpoint module" end
  local insp = Checkpoint.inspect(G)
  if not insp.canCapture then
    return false, "cannot capture: " .. tostring(insp.reason)
  end
  local cok, ck = pcall(Checkpoint.capture, G)
  if not cok or not ck then return false, "capture failed" end
  saved_checkpoints[c.token or "default"] = ck
  return true, "captured " .. (c.token or "default")
end

local reseed_counter = 0
function OPS.checkpoint_restore(G, c)
  local ok, Checkpoint = pcall(require, "src.core.Checkpoint")
  if not ok then return false, "no Checkpoint module" end
  local ck = saved_checkpoints[c.token or "default"]
  if not ck then return false, "no checkpoint " .. (c.token or "default") end
  local rok, err = pcall(Checkpoint.restore, G, ck)
  if not rok then return false, "restore failed: " .. tostring(err) end
  -- reseed=true: Checkpoint.restore puts back the CAPTURED rng state, so a
  -- replay would repeat the same luck. CLAIM_RULES forbids luck foresight
  -- on refinement replays, and policy-eval trials need fresh rolls — so
  -- re-randomize after restoring.
  if c.reseed then
    reseed_counter = reseed_counter + 1
    pcall(function()
      love.math.setRandomSeed(os.time() * 1000 + reseed_counter)
    end)
  end
  return true, "restored " .. (c.token or "default")
      .. (c.reseed and " (rng reseeded)" or "")
end

function OPS.screenshot(G, c)
  return U.shot(G, c.path or (BRIDGE .. "/shot.png"))
end

function OPS.quit() return true, "quitting" end

-- --------------------------------------------------- auto-advance dialogue
-- The model should only be asked to act at genuine DECISION points. Between
-- ops the harness rides out everything else: plain text boxes, battle
-- message text, the nickname ceremony, and script-driven cutscenes (the Oak
-- escort). This deletes the "stuck mashing dialogue" failure class and the
-- escort, and slashes model calls.
local function scripts_busy(G)
  local ow = G.overworld
  if not ow then return false end
  local r = ow.runner
  if r and r.isRunning and r:isRunning() then return true end
  if ow.player and ow.player.moving then return true end
  -- the same signals Checkpoint.scriptsBusy uses: a cutscene (e.g. the Oak
  -- escort) drives the player via scriptMoves / parallel runners / pending
  -- scripts, and any of these can be the only non-empty one between beats.
  local function nonempty(t) return type(t) == "table" and next(t) ~= nil end
  if nonempty(ow.scriptMoves) or nonempty(ow.pendingScripts)
      or nonempty(ow.parallelRunners) or nonempty(ow.parallelQueue) then
    return true
  end
  -- NOTE: deliberately NOT checking npc.moving — ambient NPCs wander during
  -- normal free-roam, which would make free control never read as a decision.
  return false
end

-- Info/ceremony screens that just need A to dismiss (not decisions).
local CEREMONY = { DexEntryMenu = true }

-- True when the game is waiting on a real choice the model must make.
local function decision_reached(G)
  local top = G.stack:top()
  if not top then return false end                        -- between states
  if G.overworld and top == G.overworld then
    return not scripts_busy(G)                            -- free roam only
  end
  if top.enemy or top.kind then                           -- battle
    return top.phase == "menu" or top.phase == "moveSelect"
  end
  if top.pages and top.pageIndex then return false end    -- plain text box
  local sid = tostring(top.screenId or "")
  if sid == "NamingScreen" or CEREMONY[sid] then return false end
  if type(top.index) == "number" then return true end     -- yes/no, list menu
  if sid ~= "" then return true end                       -- named screen (dex/PC/shop/move-learn)
  return false                                            -- transition/fade/misc: wait it out
end

local function advance_to_decision(G, maxn)
  local stable = 0
  for _ = 1, maxn or 600 do
    if decision_reached(G) then
      -- confirm the decision state holds: a cutscene (e.g. the Oak escort
      -- after "Hey! Wait!") reads idle for a stretch of frames before its
      -- next beat schedules, so require a sustained idle window (~40 frames)
      -- before handing control back. Genuine free control stays idle forever,
      -- so this only adds negligible latency there; a resuming cutscene trips
      -- scripts_busy within the window and we keep riding it.
      stable = stable + 1
      if stable >= 20 then return end
      U.wait(2)
    else
      stable = 0
      local top = G.stack:top()
      local sid = top and tostring(top.screenId or "") or ""
      if top and top.pages and top.pageIndex then
        local pg = top.pages[top.pageIndex]
        if type(pg) == "table" then recent_text = table.concat(pg, " ") end
        U.tap(G, "a"); U.wait(2)                          -- plain text
      elseif top and (top.enemy or top.kind) then
        U.tap(G, "a"); U.wait(2)                          -- battle message text
      elseif sid == "NamingScreen" then
        U.tap(G, "start"); U.wait(3); U.tap(G, "a"); U.wait(3)  -- default name
      elseif CEREMONY[sid] then
        U.tap(G, "a"); U.wait(3)                          -- info screen
      elseif G.overworld and top == G.overworld then
        U.wait(3)              -- script-busy overworld cutscene: just wait,
                              -- never press A (could talk to an NPC on a
                              -- brief control return mid-script)
      else
        -- unknown non-overworld state: a transition (ignores A) or a
        -- press-to-continue like the rival's post-battle exit (needs A).
        U.tap(G, "a"); U.wait(3)
      end
    end
  end
end

-- ------------------------------------------------------------ bridge loop
return function(G)
  U.wait(10)
  local seq = 0
  local result = { op = "boot", ok = true }
  while true do
    -- only ever observe at a decision point; watchdog-bounded so a state
    -- the advancer can't clear stalls one cycle, not the whole bridge
    wd_run(G, "advance_to_decision", OP_FRAME_BUDGET, advance_to_decision, G)
    observe(G, seq, result)
    -- poll for the next command
    local cmd
    while true do
      local f = io.open(BRIDGE .. "/cmd.lua", "r")
      if f then
        local body = f:read("*a")
        f:close()
        local chunk = body and load(body, "cmd", "t", {})
        local ok, c = pcall(chunk or function() end)
        if ok and type(c) == "table" and (c.seq or 0) > seq then
          cmd = c
          break
        end
      end
      U.wait(6)
    end
    seq = cmd.seq
    local op = OPS[cmd.op]
    if op then
      local ok, detail = wd_run(G, cmd.op, OP_FRAME_BUDGET, op, G, cmd)
      result = { op = cmd.op, ok = ok and true or false,
                 detail = detail and tostring(detail) or nil }
    else
      result = { op = tostring(cmd.op), ok = false, detail = "unknown op" }
    end
    if cmd.op == "quit" then
      observe(G, seq, result)
      return
    end
  end
end
