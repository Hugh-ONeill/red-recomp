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
coroutine.yield = function(...)
  if wd.budget and coroutine.running() == wd.co then
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
  s = s:gsub("[\\\"\n\r\t]", { ["\\"] = "\\\\", ['"'] = '\\"',
    ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t" })
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
      for i, w in ipairs(md.warps) do
        o.map.warps[i] = { x = w.x, y = w.y, dest = w.destMap }
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

local function bfs_dir(G, tx, ty)
  local Collision = require("src.world.Collision")
  local ow = G.overworld
  local p = ow.player
  if p.cellX == tx and p.cellY == ty then return nil, "arrived" end
  local key = function(x, y) return x .. "," .. y end
  local seen = { [key(p.cellX, p.cellY)] = true }
  local queue = { { x = p.cellX, y = p.cellY, first = nil } }
  local head = 1
  while queue[head] do
    local cur = queue[head]; head = head + 1
    for dir, d in pairs(DIRS) do
      local nx, ny = cur.x + d[1], cur.y + d[2]
      if not seen[key(nx, ny)] then
        local probe = setmetatable({ cellX = cur.x, cellY = cur.y },
                                   { __index = p })
        if Collision.canMove(ow.map, ow.entities, probe, dir) then
          seen[key(nx, ny)] = true
          local first = cur.first or dir
          if nx == tx and ny == ty then return first end
          queue[#queue + 1] = { x = nx, y = ny, first = first }
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
  if hit(p.cellX, p.cellY) then return p.cellX, p.cellY end
  local key = function(x, y) return x .. "," .. y end
  local seen = { [key(p.cellX, p.cellY)] = true }
  local queue = { { x = p.cellX, y = p.cellY } }
  local head = 1
  while queue[head] do
    local cur = queue[head]; head = head + 1
    for _, d in pairs(DIRS) do
      local nx, ny = cur.x + d[1], cur.y + d[2]
      if not seen[key(nx, ny)] then
        local probe = setmetatable({ cellX = cur.x, cellY = cur.y },
                                   { __index = p })
        if Collision.canMove(ow.map, ow.entities, probe,
            (d[1] == 0 and (d[2] < 0 and "up" or "down"))
            or (d[1] < 0 and "left" or "right")) then
          seen[key(nx, ny)] = true
          if hit(nx, ny) then return nx, ny end
          queue[#queue + 1] = { x = nx, y = ny }
        end
      end
    end
  end
  return nil
end

local OPS = {}

function OPS.new_game(G) U.newGame(G) return true end

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
local function battle_menu_to(G, battle, want)
  for _ = 1, 6 do
    if battle.menuIndex == want then return true end
    local col, wcol = (battle.menuIndex - 1) % 2, (want - 1) % 2
    U.tap(G, col ~= wcol and "left" or (battle.menuIndex > want and "up"
                                        or "down"))
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

function OPS.checkpoint_restore(G, c)
  local ok, Checkpoint = pcall(require, "src.core.Checkpoint")
  if not ok then return false, "no Checkpoint module" end
  local ck = saved_checkpoints[c.token or "default"]
  if not ck then return false, "no checkpoint " .. (c.token or "default") end
  local rok, err = pcall(Checkpoint.restore, G, ck)
  if not rok then return false, "restore failed: " .. tostring(err) end
  return true, "restored " .. (c.token or "default")
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
