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

-- DIAGNOSTIC, off unless RED_DIALOG_TRACE=1. One line per text-advance
-- iteration into run/dialog_trace.log, so a box that will not close can be
-- read back frame by frame instead of guessed at. Bill's speech ends the
-- only way out of Cerulean and the run lost it to "a box was up and would
-- not close" with nothing recorded about WHICH box. Never read by the
-- model, never on in a claim run.
local DLG_TRACE = os.getenv("RED_DIALOG_TRACE") == "1"
local function dlg_trace(G, where, i)
  if not DLG_TRACE then return end
  local f = io.open(BRIDGE .. "/dialog_trace.log", "a")
  if not f then return end
  local t = G and G.stack and G.stack:top()
  local ow = G and G.overworld
  f:write(("%-10s %3d top=%s ow=%s screen=%s kind=%s pages=%s idx=%s "
           .. "items=%s title=%s choice=%s\n"):format(
    where, i, tostring(t), tostring(t == ow),
    tostring(t and t.screenId), tostring(t and t.kind),
    tostring(t and t.pages and #t.pages), tostring(t and t.pageIndex),
    tostring(t and t.items and #t.items), tostring(t and t.title),
    tostring(t and (t.choice ~= nil or t.yesNo ~= nil or t.isChoice))))
  f:close()
end

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
-- The write itself, so something that does NOT yield can still say it is
-- alive. observe() is the case: it walks the whole walkable component and
-- scans up to 72x72 tiles without a single yield, so the heartbeat file
-- simply stops for its duration -- and a stopped heartbeat is the exact
-- signature of the yield starvation this file was written to hunt. It was
-- reading as the disease. Now a sample taken mid-observation says
-- "observe", which is a different answer from "nothing is moving".
local function hb_write(label)
  local f = io.open(BRIDGE .. "/heartbeat", "w")
  if f then
    f:write(os.time() .. " " .. hb.yields .. " " .. tostring(label))
    f:close()
  end
end
-- assigned further down, once the text buffers it writes into exist
local note_text
coroutine.yield = function(...)
  local co = coroutine.running()
  if wd.co and co == wd.co then
    hb.yields = hb.yields + 1
    -- READ THE SCREEN WHILE THE OP IS STILL RUNNING. Text that appears
    -- mid-op was never recorded: the settle loop only sees whichever page
    -- is up when the op RETURNS, so a two-page speech reached the ledger
    -- as its second half. The Saffron guard says "Gee, I'm thirsty,
    -- though!" and then "Oh wait there, the road's closed" — and only the
    -- refusal ever survived, which is the half that explains nothing.
    -- Cheap by construction: nothing is built unless the page changed.
    local g = wd.G
    local top = g and g.stack and g.stack:top()
    if top and top.pages and top.pageIndex and note_text
        and (top ~= wd.pagetop or top.pageIndex ~= wd.pageidx) then
      wd.pagetop, wd.pageidx = top, top.pageIndex
      local pg = top.pages[top.pageIndex]
      if type(pg) == "table" then note_text(table.concat(pg, " ")) end
    end
    if hb.yields % 2048 == 0 then hb_write(tostring(wd.label)) end
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
  wd.G = G                       -- for the yield hook's screen sampling
  wd.label = label
  wd.budget = budget
  wd.frames = 0
  local res = { pcall(fn, ...) }
  wd.budget = nil
  if res[1] then return UNPACK(res, 2) end
  -- an op aborted mid-yield may have skipped its key-release lines: a
  -- direction left held would corrupt every later op.
  -- pressQueue FIRST: walk/cross/use_warp insert into the queue and THEN
  -- yield, so the watchdog can raise before the yield returns. Input:step()
  -- re-asserts state[btn]=true for anything still queued, which put the
  -- direction straight back and walked the player through every later
  -- U.wait. Clearing state alone was a no-op against exactly the window
  -- the watchdog exists to close.
  if G and G.input then
    local q = G.input.pressQueue
    if q then for i = #q, 1, -1 do q[i] = nil end end
    if G.input.state then
      for k in pairs(G.input.state) do G.input.state[k] = false end
    end
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
-- AN HM IS A KEY ITEM, whatever the data table says. items.lua marks the
-- fossils and the ticket keyItem = true but leaves the HMs without it --
-- they carry `machine = { kind = "HM" }` instead -- so every HM was
-- reported as an ordinary bag item AND offered to the model as something
-- it could throw away to free a slot. Gen 1 refuses both: an HM cannot be
-- tossed or sold, and the game says so on screen ("That's too impor-tant
-- to toss!"), which is the tier this belongs to. One test, both readers.
local function is_key_item(def)
  if not def then return false end
  if def.keyItem then return true end
  return (def.machine and def.machine.kind == "HM") and true or false
end

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
    -- WHAT TYPE IT IS. The status screen prints it under the name, so it is
    -- as player-visible as the level beside it -- but nothing published it,
    -- and a run cannot aim at "get something that resists this" while the
    -- only thing it knows about its party is species and numbers. Read off
    -- the species table the game reads.
    do
      local def = G.data and G.data.pokemon and G.data.pokemon[mon.species]
      if def and def.types then
        m.types = {}
        for k, t in ipairs(def.types) do m.types[k] = tostring(t) end
      end
    end
    out[i] = m
  end
  return out
end

-- HOW MANY SPECIES ARE OWNED AND SEEN. The Pokedex screen shows both
-- totals on its own summary line, so this is on-screen tier. It is also
-- load-bearing: the Route 2 aide trades HM05 FLASH for TEN OWNED, and with
-- no way to count them that gate cannot be written as a subgoal at all --
-- the run can only bump into it. Counts only; which species those are is
-- already in the party list for anything in the party.
local function pokedex(G)
  local dex = G.save and G.save.pokedex
  if not dex then return nil end
  local owned, seen = 0, 0
  for _ in pairs(dex.owned or {}) do owned = owned + 1 end
  for _ in pairs(dex.seen or {}) do seen = seen + 1 end
  return { owned = owned, seen = seen }
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
local region_reach          -- ditto; identity fill, no one-way hops
local ui_back_out           -- ditto; needed by need_overworld above it

-- CLOSE THE BOX AND GET ON WITH IT. Fifteen ops refused outright with "not
-- in overworld" whenever any menu or text box happened to be up — a sign
-- still being read, a shop screen left open, the tail of somebody's
-- speech. The model then re-issued the same op, hit the same box, and
-- burned its rounds on a door it was standing next to. Pressing B is not a
-- decision: it dismisses a screen nobody asked to be in and puts the
-- player back where the op can run. A BATTLE is never dismissed this way —
-- that is a real state with real choices, and it is handled elsewhere.
local function need_overworld(G)
  if G.overworld and G.stack:top() == G.overworld then return true end
  local t = G.stack and G.stack:top()
  if t and (t.enemy or t.kind) then return false end   -- in battle; leave it
  if ui_back_out then ui_back_out(G) end
  return (G.overworld and G.stack:top() == G.overworld) and true or false
end
-- map id -> { "x,y" = region name }. Names are minted once and never
-- rewritten, so a region cannot be renamed by the world opening up.
local region_of = {}
local recent_text = nil
-- The LAST thing anybody said, kept after the box closes. recent_text is
-- wiped the moment control returns, which is correct for "is a prompt open
-- right now" and useless for learning: this game explains its own gates out
-- loud ("I'm too sleepy to move", "you need the POKEDEX"), and every word
-- of it was being dropped before the model could read it.
local last_text = nil
-- QUESTIONS THIS RUN HAS ACTUALLY BEEN SHOWN, keyed by who asked. An
-- `answer` is only honoured for a question already quoted back to the
-- model, because `answer="yes"` turned out to be boilerplate rather than
-- consent: it rode along on 302 of 560 interacts, including with signposts
-- and a PC and a CUT_TREE, none of which can ask anything. On the one NPC
-- in Kanto who takes a Pokemon for a yes, that reflex boarded a level 40
-- CHARIZARD and left a level 6 MAGIKARP to fight a gym. Unread questions
-- are declined and quoted (that path already existed); the next interact
-- can answer them for real. Signposts are unaffected — they never ask.
local seen_question = {}
-- WHAT AN ELEVATOR PANEL OFFERS, once it has been pressed. map id ->
-- { "1F", "2F", ... }. A lift's warp tiles are rewritten at runtime from
-- this menu, so its floors are not warps in the map data and no amount of
-- door-counting can find them; the menu on screen is where they exist.
-- Learned only by a press that worked, never read ahead of the body.
local lift_floors = {}
-- ...and ALL of it, not just the last page. A speech breaks into pages on
-- \f, and keeping only the page showing when the box closed threw away
-- everything said before it. The Saffron gate guard says "I'm on guard
-- duty. Gee, I'm thirsty, though!" and THEN "Oh wait there, the road's
-- closed." — so the run recorded the refusal and lost the reason, which is
-- the only clue that the gate opens with a drink. Accumulate the pages of
-- one speech; a return to free roam ends it and the next starts fresh.
local text_run = nil
-- HOW MANY TIMES ANYBODY HAS SPOKEN, ever, this process. A bare count,
-- and it exists because comparing the WORDS cannot tell "she said it
-- again" from "her last line is still sitting in the buffer".
-- last_text outlives the box that printed it, so the executor could only
-- attribute a line to the op that caused it by checking the text had
-- CHANGED — which silences anyone who repeats themselves. The Viridian
-- mart clerk says "Okay! Say hi to PROF.OAK for me!" every single time
-- she is spoken to, and that sentence names the next objective; the run
-- was shown it on the first press and never again, while it pressed her
-- over and over waiting for a Pokemon she does not have. A counter that
-- moves whenever a line is PRINTED settles it without looking at the
-- words at all.
local text_seq = 0
function note_text(txt)        -- forward-declared above the yield hook
  if not txt or #txt == 0 then return end
  text_seq = text_seq + 1
  recent_text = txt
  if text_run and text_run:sub(1, #txt) == txt then
    -- the speech is starting over: a fresh telling, not more of the last
    -- one. Without this a guard who refuses you five times accumulates
    -- five copies of himself, since bouncing off a blocked door never
    -- yields the clean free-roam frame that ends a speech.
    text_run = txt
  elseif not (text_run and text_run:sub(-#txt) == txt) then
    text_run = text_run and (text_run .. " " .. txt) or txt
  end
  last_text = text_run
end
-- Oracle probe result (battle_probe), surfaced once in the next observation.
local last_probe = nil

-- FIXTURES YOU CAN SEE BUT NO LIST NAMES. The engine keeps pressable
-- machinery outside both the object and sign lists ("hidden events"
-- internally): Pokemon Center PCs, slot machines, the Vermilion Gym trash
-- cans, and Bill's cell separator. Every one of them is a sprite drawn on
-- screen — a human player walks up BECAUSE they can see them — so naming
-- them is on-screen tier, and the separator's name is the one Bill speaks
-- out loud. The truly hidden things (items found by pressing A at a
-- blank-looking tile) are deliberately NOT here: listing those would be
-- x-ray vision, not eyesight.
local function map_fixtures(G, map_id)
  local out = {}
  local fld = (G.data and G.data.field) or {}
  local ex = fld.hiddenExtras or {}
  for _, h in ipairs((ex.pcTiles or {})[map_id] or {}) do
    out[#out + 1] = { x = h.x, y = h.y, name = "PC", facing = h.facing }
  end
  for i, h in ipairs((fld.slotMachines or {})[map_id] or {}) do
    out[#out + 1] = { x = h.x, y = h.y, name = "SLOT_MACHINE_" .. i }
  end
  if map_id == "VERMILION_GYM" and ex.trashCans then
    for _, h in ipairs(ex.trashCans.cans or {}) do
      out[#out + 1] = { x = h.x, y = h.y, name = "TRASH_CAN_" .. h.can }
    end
  end
  -- The Game Corner poster. It hangs on the wall in plain sight and it is
  -- the door to the Rocket hideout, but it lives in its OWN field table
  -- (gameCornerPoster) rather than in hiddenExtras, so nothing here listed
  -- it and the room read as nothing but slot machines. A press the model
  -- cannot name is a press it cannot make.
  local gcp = fld.gameCornerPoster
  if gcp and gcp.map == map_id and gcp.poster then
    out[#out + 1] = { x = gcp.poster.x, y = gcp.poster.y, name = "POSTER" }
  end
  if map_id == "BILLS_HOUSE" then
    out[#out + 1] = { x = 1, y = 4, name = "CELL_SEPARATION_SYSTEM",
                      facing = "up" }
  end
  return out
end

local function observe(G, seq, result)
  hb_write("observe")
  local top = G.stack and G.stack:top()
  local o = { seq = seq, result = result, events = events, frame = U.frame() }
  events = {}
  if recent_text then o.recent_text = recent_text end
  if last_text then o.last_text = last_text end
  o.text_seq = text_seq        -- see note_text: printed-line count, not words
  if G.overworld and top == G.overworld then
    recent_text = nil          -- free roam: stale prompt no longer applies
    o.recent_text = nil
    text_run = nil             -- that speech is over; the next starts clean
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
    -- the floors this car's panel was seen to offer (see lift_floors)
    o.map.lift_floors = lift_floors[tostring(map.id)]
    -- ONE FILL, NOT TWO. `reach` here and `objreach` further down were
    -- the SAME call -- warp_reach(G), same arguments, same frame, same
    -- answer -- computed twice for every observation. On an outdoor map
    -- that is a second flood of the whole walkable component for nothing.
    -- (The third fill, region_reach, is genuinely different: no_ledges.)
    -- observe() never yields, so every cell it walks is time the heartbeat
    -- file does not tick, and a stalled heartbeat is exactly the signature
    -- of the yield starvation this harness was once wedged hunting.
    local _reach_memo
    local function reachable_cells()
      if not _reach_memo then _reach_memo = warp_reach(G) or {} end
      return _reach_memo
    end
    if md and md.warps then
      o.map.warps = {}
      local reach = reachable_cells()
      -- REGION: two positions in the same walkable component share the same
      -- smallest reachable cell. "Did I actually get somewhere else?" is a
      -- question about the COMPONENT, not about distance (coming out the
      -- same cave door lands tiles away but in the same region — thin7).
      --
      -- ...BUT A PLACE KEEPS THE NAME IT WAS FIRST GIVEN. The bare
      -- fingerprint is DYNAMIC: it is the smallest cell reachable RIGHT
      -- NOW, so the moment the walkable space grows -- a tree cut, an NPC
      -- stepping aside, a boulder pushed -- the minimum moves and the same
      -- physical spot reports a different region. Every edge, visit,
      -- sighting and frontier entry filed under the old name is orphaned by
      -- that, which is what AREA_ALIASES exists to paper over. Worse for
      -- Cerulean specifically: cutting the tree would fuse the main city
      -- and the southern strip into one label and lose the distinction the
      -- run spent all morning learning.
      --
      -- So: remember which region each cell was assigned to, and when we
      -- are standing on a cell that already has a name, keep it. Only
      -- genuinely unnamed ground gets the current component's fingerprint.
      -- Purely additive -- names are minted once and never rewritten, and
      -- space expanding never merges two names.
      do
        -- identity comes from the two-way fill, NOT the warp fill above
        local rreach = region_reach(G) or reach
        local bx, by
        for k in pairs(rreach) do
          local cx, cy = k:match("^(-?%d+),(-?%d+)$")
          if cx then
            cx, cy = tonumber(cx), tonumber(cy)
            if not bx or cy < by or (cy == by and cx < bx) then
              bx, by = cx, cy
            end
          end
        end
        local known = region_of[map.id]
        if not known then known = {}; region_of[map.id] = known end
        local here = (p.cellX or -1) .. "," .. (p.cellY or -1)
        -- ONE REMEMBERED CELL RE-IDENTIFIES THE WHOLE REGION. Standing
        -- cell first (after the tree is cut, main and the strip south of
        -- it share one component and must still answer to their own
        -- names); otherwise any already-named cell we can reach. Only
        -- ground nobody has ever named falls through to a fresh mint.
        local name = known[here]
        if not name then
          for k in pairs(rreach) do
            if known[k] then name = known[k] break end
          end
        end
        name = name or (bx and (bx .. "," .. by))
        if name then
          o.map.region = name
          -- paint only the ground that has never been named, and only
          -- ground you could walk back from -- otherwise one look from the
          -- top of the ridge stamps the whole strip below with main's name
          for k in pairs(rreach) do
            if known[k] == nil then known[k] = name end
          end
          known[here] = name
          -- one cell per name is all the executor needs to store: the
          -- component walk above re-spreads it on the next load.
          local seen_name, anchors = {}, {}
          for k, v in pairs(known) do
            if not seen_name[v] then seen_name[v] = true; anchors[k] = v end
          end
          o.map.region_anchors = anchors
        end
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
    local objreach = reachable_cells()
    -- literal offsets, NOT the DIRS table: DIRS is declared further down
    -- the file, so inside observe() it is nil (the same scoping trap that
    -- killed the driver when warp reachability was first added)
    -- COUNTER STAFF ARE REACHABLE. "Reachable" meant a walkable tile
    -- orthogonally adjacent, and a clerk or nurse behind a counter has
    -- none -- so every shopkeeper and every nurse in Kanto was filtered
    -- out of the observation and out of sightings. The Pokemon Center
    -- listed its Cable Club receptionist, its gentleman and its PC, and
    -- not the one person in the building who heals you; the bike shop
    -- looked FULLY WORKED with a voucher unspent in the bag, because the
    -- only two people it could see had both been spoken to. Gen 1 talks
    -- ACROSS a counter, and OPS.interact already stands at distance 2 to
    -- do it -- this just teaches the observation the same reach, with the
    -- same guard (nobody on the tile between, or the press hits them).
    local function occupied_cell(x, y)
      for _, n in ipairs(G.overworld.npcs or {}) do
        if n.cellX == x and n.cellY == y then return true end
      end
      return false
    end
    local function adjacent_reachable(x, y)
      if objreach[(x - 1) .. "," .. y] or objreach[(x + 1) .. "," .. y]
         or objreach[x .. "," .. (y - 1)] or objreach[x .. "," .. (y + 1)]
      then return true end
      local over = { { x, y + 2, x, y + 1 }, { x, y - 2, x, y - 1 },
                     { x - 2, y, x - 1, y }, { x + 2, y, x + 1, y } }
      for _, o in ipairs(over) do
        if objreach[o[1] .. "," .. o[2]] and not occupied_cell(o[3], o[4]) then
          return true
        end
      end
      return false
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
    -- OBJECTS THIS MAP DEFINES THAT ARE NOT PRESENT YET. G.overworld.npcs
    -- is the LIVE list, filtered by objectVisible, so a room whose script
    -- has more to reveal looks identical to one that is finished. Bill's
    -- house defines three objects and shows one until his errand is done;
    -- Cerulean defines the guard who replaces the one blocking the house.
    -- Counting them lets the harness decline to certify a room as fully
    -- worked when it KNOWS the room can still change. Count only, no names
    -- and no positions: the model is not being told what is coming.
    do
      local live = {}
      for _, npc in ipairs(G.overworld.npcs or {}) do
        local n = (npc.def or {}).name
        if n then live[n] = true end
      end
      local dormant = 0
      for _, od in ipairs((md and md.objects) or {}) do
        if od.name and not live[od.name] then dormant = dormant + 1 end
      end
      o.map.dormant = dormant
    end
    -- SIGNS ARE THINGS YOU PRESS A ON. They live in a separate map list
    -- from objects and were never observed at all, so anything that is
    -- scenery rather than a person was invisible: notice boards, the
    -- Pokedex-rating PC, and BILL'S CELL SEPARATOR — the one interaction
    -- that finishes his errand and, through it, unblocks Cerulean. The
    -- model cannot name what it cannot see, and a room full of unpressed
    -- signs was certifying itself as fully worked.
    for _, sg in ipairs((md and md.signs) or {}) do
      local nm = sg.name or sg.text or ("SIGN_" .. tostring(sg.x) .. "_"
                                        .. tostring(sg.y))
      o.map.objects[#o.map.objects + 1] = {
        x = sg.x, y = sg.y, kind = "sign", name = nm,
        reachable = adjacent_reachable(sg.x, sg.y),
      }
    end
    -- The comment above promised Bill's separator; md.signs never
    -- contained it (it is a hidden_event, not a sign). These are the
    -- machines the player can SEE — see map_fixtures.
    for _, f in ipairs(map_fixtures(G, map.id)) do
      o.map.objects[#o.map.objects + 1] = {
        x = f.x, y = f.y, kind = "fixture", name = f.name,
        reachable = adjacent_reachable(f.x, f.y),
      }
    end
    -- CUT TREES are drawn bushes — the most on-screen thing there is —
    -- and the only way through several fences (Vermilion Gym's door
    -- among them). Listed so the model can aim field_move at one.
    do
      local lm = G.overworld and G.overworld.map
      -- tile ids are only meaningful within ONE tileset (tryCut's own
      -- rule, learned when raw block matching chain-cut "ornamental
      -- bushes" and crashed PLATEAU): a cuttable OBSTACLE is OVERWORLD
      -- tree $3d or GYM plant $50, standing on a non-walkable cell.
      -- Grass ($52) is cuttable too but cosmetic — listing every tussock
      -- would drown the object list.
      local ts = lm and lm.def and lm.def.tileset
      local want = (ts == "OVERWORLD" and 0x3d)
                   or (ts == "GYM" and 0x50) or nil
      -- lm.widthCells directly: map_dims_cells is declared further down
      -- the file and is nil inside observe (the DIRS scoping trap again)
      if lm and lm.cellTile and want then
        local w = lm.widthCells or 0
        local h = lm.heightCells or 0
        for cy = 0, math.min(h - 1, 71) do
          for cx = 0, math.min(w - 1, 71) do
            if lm:cellTile(cx, cy) == want
               and not lm:isWalkableCell(cx, cy) then
              o.map.objects[#o.map.objects + 1] = {
                x = cx, y = cy, kind = "cut_tree", name = "CUT_TREE",
                reachable = adjacent_reachable(cx, cy),
              }
            end
          end
        end
      end
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
    -- IS THIS A QUESTION OR A MENU? scalars() copies only scalar fields, so
    -- a menu's `items` table never reaches the observation -- and the
    -- executor's "a cursor and no items means yes/no" test was therefore
    -- true of EVERYTHING with a cursor. It put the mart's BUY list to the
    -- model as a yes/no, got "yes" (it was trying to reach the day care
    -- man), pressed A into the shopping list and spent 2000 doing it.
    -- Answer the question here, with the same test the shim itself uses.
    o.ui.is_choice = (top.index ~= nil and top.items == nil) and true or false
  else
    o.mode = "boot"
  end
  o.party = party(G)
  o.badges = badges(G)
  o.pokedex = pokedex(G)
  -- bag: player-visible (the START menu ITEM screen); badges live in the
  -- same inventory table but are not bag items
  o.bag = {}
  -- WHICH OF THEM ARE KEY ITEMS. Player-visible: the game refuses to toss
  -- or sell one and says so out loud ("That's too important to toss!"),
  -- which is how OPS.toss already knows. It was never published, so the
  -- executor could only see {ITEM: count} and had no way to tell a
  -- POTION from a BIKE_VOUCHER — and what you are carrying is the thing
  -- that changes what people say to you when you come back.
  o.key_items = {}
  local function note_key(k)
    local def = G.data and G.data.items and G.data.items[k]
    if is_key_item(def) then o.key_items[#o.key_items + 1] = k end
  end
  for k, v in pairs((G.save and G.save.inventory) or {}) do
    if type(k) == "string" and not k:match("BADGE$")
       and (tonumber(v) or 0) > 0 then
      o.bag[k] = v
      note_key(k)
    end
  end
  -- What the PC is holding. Player-visible: it is the WITHDRAW ITEM list,
  -- one A-press away at any Pokemon Center. Without it a withdrawal is a
  -- guess, and anything deposited is gone from the run's knowledge the
  -- moment it stops being in the bag.
  o.pc_items = {}
  for k, v in pairs((G.save and G.save.pcItems) or {}) do
    if type(k) == "string" and (tonumber(v) or 0) > 0 then
      o.pc_items[k] = v
      -- A KEY ITEM IN THE PC IS STILL ONE YOU HAVE (user, 2026-08-15).
      -- The bag holds 20 kinds and fills, storing is the answer, and the
      -- run has never once used the PC — but the moment it does, a
      -- deposited SILPH SCOPE would read as never acquired and every
      -- conversation it unlocks would look untouched again.
      note_key(k)
    end
  end
  table.sort(o.key_items)
  -- WHO IS AT THE DAY CARE. Same reason as pc_items: the run answered
  -- "yes" to the DAYCARE_GENTLEMAN while hunting for a way to Celadon and
  -- handed over a level 40 CHARIZARD, leaving a level 6 MAGIKARP to beat
  -- Erika with. Nothing in the observation said where it went, so the loss
  -- was unexplainable AND the fix — walk back in and pay to take it out —
  -- was unthinkable. The Day Care Man says all of this out loud when you
  -- talk to him, and the party screen shows the hole.
  do
    local dc = G.save and G.save.daycare
    local mon = dc and dc.mon
    if mon and mon.species then
      o.daycare = {
        species = mon.species,
        level = mon.level,
        deposit_level = dc.depositLevel,
        -- what it costs to take back: 100 per level gained, minimum 100
        cost = 100 * math.max(1, (tonumber(mon.level) or 0)
                                 - (tonumber(dc.depositLevel) or 0) + 1),
      }
    end
  end
  -- WHERE YOU WAKE IF YOU FAINT. The game sets this every time you heal
  -- and a player always knows it; the harness only ever mentioned it
  -- AFTERWARDS, in the journal line about the blackout that already
  -- happened. The run crossed most of Rock Tunnel with its respawn still
  -- in PEWTER -- the far west corner -- having walked past the Pokemon
  -- Center at the tunnel mouth without healing, and lost the whole
  -- crossing to one faint. Whether that is worth a detour is its call;
  -- not knowing the stake was ours.
  do
    local lh = G.save and G.save.lastHeal
    if lh and lh.map then
      o.respawn = { map = lh.map,
                    outdoor = lh.outdoor and lh.outdoor.id or nil }
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
  -- and hand the label back, so a sample taken after this returns does not
  -- go on reporting an observation that finished
  hb_write(tostring(wd.label))
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

-- WHERE AN ARROW TILE ACTUALLY PUTS YOU. Rocket Hideout B2F/B3F and
-- Viridian Gym are floored with spinners: stepping on one slides you along
-- a fixed move list (engine/overworld/spinners.asm; the same static
-- field.spinners table the engine reads), and the cell you stop on may be
-- another arrow, which chains. A BFS that treats them as ordinary floor
-- plans routes that cannot be walked -- it thinks it can step onto an
-- arrow and stay there. Same shape as ledge_landing: read the table the
-- engine reads, and report where you END UP.
local function spinner_landing(G, map, x, y, depth)
  local list = G.data and G.data.field and G.data.field.spinners
               and G.data.field.spinners[map and map.id]
  if not list then return nil end
  for _, sp in ipairs(list) do
    if sp.x == x and sp.y == y then
      local cx, cy = x, y
      for _, mv in ipairs(sp.moves or {}) do
        local d = DIRS[mv.dir]
        if d then
          cx = cx + d[1] * (mv.count or 0)
          cy = cy + d[2] * (mv.count or 0)
        end
      end
      if (cx ~= x or cy ~= y) and (depth or 0) < 8 then
        local lx, ly = spinner_landing(G, map, cx, cy, (depth or 0) + 1)
        if lx then return lx, ly end
      end
      if map.inBounds and not map:inBounds(cx, cy) then return nil end
      return cx, cy
    end
  end
  return nil
end

-- Which cells can we currently WALK to (ledge hops included)? Used to mark
-- warps reachable/unreachable in the observation: on partitioned maps (Mt
-- Moon B1F) the right warp can be visible but walled off, and without this
-- the model re-proposes it forever. Defined here because it needs DIRS and
-- ledge_landing; observe() calls it through a forward-declared local.
-- reach WITHOUT one-way hops. A ledge you can drop off but not climb is a
-- BOUNDARY, not a corridor: from the top of Cerulean's ridge the plain
-- fill leaks into the strip below and swallows it, so main city and the
-- southern section report one identity and the passage between them reads
-- as a door back to where you started. Region names are minted from THIS
-- fill -- what you can walk and walk back from, bounded by seams and
-- one-way drops. Warp reachability still uses the leaky one: a warp you
-- can only get to by dropping down IS reachable, it just is not here.
region_reach = function(G) return warp_reach(G, true) end

function warp_reach(G, no_ledges)
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
          -- an arrow tile is not somewhere you stand: you arrive and are
          -- slid on. One-way, like a ledge, so the two-way identity fill
          -- (no_ledges) refuses to cross it at all.
          local sx, sy = spinner_landing(G, ow.map, nx, ny)
          if sx then
            if not no_ledges and not seen[key(sx, sy)] then
              seen[key(sx, sy)] = true
              q[#q + 1] = { x = sx, y = sy }
            end
            seen[key(nx, ny)] = true
          else
            seen[key(nx, ny)] = true
            q[#q + 1] = { x = nx, y = ny }
          end
        elseif not no_ledges then
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
          -- THE WALKER'S OWN PATHFINDER HAS TO KNOW THIS TOO. Stepping
          -- onto an arrow tile slides you across the room, so a route
          -- planned as if you stopped there is wrong at the first press:
          -- walk_to aims, gets carried somewhere else, re-paths, and burns
          -- its step budget doing it. Rocket Hideout B3F is 16 such tiles.
          local sx, sy = spinner_landing(G, ow.map, nx, ny)
          if sx then
            if sx == tx and sy == ty then return first end
            if not seen[key(sx, sy)] and not wblock[key(sx, sy)] then
              seen[key(sx, sy)] = true
              queue[#queue + 1] = { x = sx, y = sy, first = first }
            end
          else
            if nx == tx and ny == ty then return first end
            queue[#queue + 1] = { x = nx, y = ny, first = first }
          end
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
  -- DIAGNOSTICS. When this returns nil the caller can only say "no path",
  -- which has been true of four different causes this week. Count what was
  -- actually walked, how close to the wanted edge it got, how many ledge
  -- hops it used, and whether it TOUCHED the edge and was turned away by
  -- landing_ok — those need opposite fixes and look identical from outside.
  local nseen, nledge, edge_rejected, nspin = 1, 0, 0, 0
  local best, bestx, besty = 1e9, nil, nil
  local function dist(x, y)
    if dir == "up" then return y end
    if dir == "down" then return (H - 1) - y end
    if dir == "left" then return x end
    return (W - 1) - x
  end
  local function note(x, y)
    nseen = nseen + 1
    local dd = dist(x, y)
    if dd < best then best, bestx, besty = dd, x, y end
  end
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
          local sx, sy = spinner_landing(G, ow.map, nx, ny)
          if sx then
            -- AN ARROW TILE IS NOT SOMEWHERE YOU STAND: you arrive and are
            -- slid on. warp_reach and bfs_dir both say so and skip the tile
            -- itself; this BFS said it in a comment and then queued the
            -- arrow anyway AND accepted it as an edge cell -- so a seam on
            -- a spinner floor (Rocket Hideout B3F is sixteen of them,
            -- Viridian Gym more) was handed to cross as a place to walk to,
            -- and the walk ended somewhere else entirely.
            if not seen[key(sx, sy)] then
              seen[key(sx, sy)] = true
              nspin = nspin + 1
              note(sx, sy)
              if hit(sx, sy) and landing_ok(G, dir, sx, sy) then
                return sx, sy
              end
              queue[#queue + 1] = { x = sx, y = sy }
            end
          else
            note(nx, ny)
            if hit(nx, ny) then
              if landing_ok(G, dir, nx, ny) then return nx, ny end
              edge_rejected = edge_rejected + 1
            end
            queue[#queue + 1] = { x = nx, y = ny }
          end
        else
          local lx, ly = ledge_landing(G, ow.map, cur.x, cur.y, dname)
          if lx and not seen[key(lx, ly)] and not wblock[key(lx, ly)] then
            seen[key(lx, ly)] = true
            nledge = nledge + 1
            note(lx, ly)
            -- ...AND THE SAME TEST THE OTHER TWO BRANCHES APPLY. This one
            -- returned a cell on the wanted edge without ever asking
            -- whether the far side has floor there, so cross walked to it
            -- and pressed into a wall -- reported as "reached the edge and
            -- the crossing failed", which is the opposite diagnosis to the
            -- true one. landing_ok is fail-open on a probe error, so this
            -- can only reject seams that genuinely have nothing behind
            -- them.
            if hit(lx, ly) then
              if landing_ok(G, dir, lx, ly) then return lx, ly end
              edge_rejected = edge_rejected + 1
            end
            queue[#queue + 1] = { x = lx, y = ly }
          end
        end
      end
    end
  end
  -- THREE values: the caller reads (ex, ey, why), so a two-value return
  -- put the diagnostic in ey and left why nil -- the message came back
  -- exactly as silent as before.
  -- ...and WHERE it stalled, so the caller can name what is next to that
  -- rather than what happens to sit near the edge. Route 2's report named
  -- a CUT_TREE at 5,10 while the walk stopped at 18,2 — thirteen cells
  -- away, across the map, and not the thing in the way.
  return nil, nil, ("BFS from %d,%d walked %d cells (%d ledge hop%s, %d arrow-tile "
    .. "slide%s); closest to "
    .. "the %s edge was %s,%s, still %d cell%s short%s")
    :format(p.cellX, p.cellY, nseen, nledge, nledge == 1 and "" or "s",
            nspin, nspin == 1 and "" or "s", dir, tostring(bestx), tostring(besty), best,
            best == 1 and "" or "s",
            edge_rejected > 0
              and ("; it DID reach the edge " .. edge_rejected
                   .. "x but the landing on the far side was refused")
              or ""), bestx, besty
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
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  return walk(G, c.dir, c.steps or 1)
end

function OPS.walk_to(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
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

-- Give the ground back. An NPC standing where you want to be is a DEADLOCK,
-- not a wall: a pacing NPC cannot step aside while the player occupies the
-- one square it would step into, so waiting in place waits forever — the run
-- asked for the same SS Anne stairwell six times running and was told
-- "couldn't reach the warp tile" every time, because its own body was what
-- pinned the NPC. Step off, let it take its turn, then come back.
-- Never yield ONTO a warp: leaving by the wrong door reports success.
local function yield_ground(G)
  local ow = G.overworld
  local p = ow.player
  local md = G.data and G.data.maps and G.data.maps[ow.map and ow.map.id]
  local function is_warp(x, y)
    for _, w in ipairs((md or {}).warps or {}) do
      if w.x == x and w.y == y then return true end
    end
    return false
  end
  for _, dir in ipairs({ "down", "up", "left", "right" }) do
    local d = DIRS[dir]
    if d and not is_warp(p.cellX + d[1], p.cellY + d[2]) then
      if walk(G, dir, 1) then
        U.wait(45)          -- NPCs pace on their own timer, not ours
        return true
      end
    end
  end
  U.wait(45)
  return false
end

-- Take a warp/door/stairs. Walk onto the warp tile, then step THROUGH it
-- (door mats and edge warps fire on the step off the tile, not on arrival),
-- trying the map-edge direction first. Decision-free: the model picks which
-- warp by x,y; the executor handles the walk-and-step-through. This is the
-- door + map-transition primitive walk_to (in-map only) can't cover.
function OPS.use_warp(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  local ow = G.overworld
  local startMap = ow.map and ow.map.id
  local p = ow.player
  if not (c.x and c.y) then return false, "use_warp needs x,y" end

  -- WHICH DOOR ACTUALLY FIRED. note_transition keys its edge on the tile
  -- we AIMED at, so a walk toward the Day Care door that crosses the Route
  -- 5 gate warp on the way recorded "10,21 leads to ROUTE_5_GATE". That
  -- contradicted the true edge learned walking IN, the conflict rule voided
  -- the honest one, and go_to_daycare went unreachable in the next two log
  -- lines: the run had learned the way in and the harness overwrote it.
  -- The departure tile cannot be recovered once the map has flipped -- by
  -- the time walk_to returns, the player is already somewhere else -- so
  -- when a crossing happens MID-WALK we say the door is unknown and let
  -- the executor record no edge at all. Honest ignorance beats a wrong
  -- edge; that is the same rule the conflict-voiding already states, moved
  -- to where the bad data is born instead of cleaning up after it.
  local walk_why = nil
  local function attempt(x, y)
    -- Three passes, yielding ground between them: pass 1 is the plain
    -- walk, and each retry backs off a tile first so an NPC pinned by the
    -- player has somewhere to go. cross() is already NPC-robust this way
    -- (it re-BFSes across rounds); a door needs the same patience.
    for pass = 1, 3 do
      if p.cellX ~= x or p.cellY ~= y then
        local _wok, _wwhy = OPS.walk_to(
          G, { x = x, y = y, max_steps = c.max_steps or 400 })
        walk_why = _wwhy or walk_why
        if (ow.map and ow.map.id) ~= startMap then
          return true, "crossed mid-walk (door unknown)"
        end
      end
      if p.cellX == x and p.cellY == y then break end
      if pass < 3 then yield_ground(G) end
      if (ow.map and ow.map.id) ~= startMap then
        return true, "crossed mid-walk (door unknown)"
      end
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
      -- a held direction whose neighbor was walkable DRIFTS the player
      -- off the warp cell (the SS Anne bow's down/up/left are all open
      -- deck), and the fire test only counts from the warp cell — the
      -- right-press that actually exits the bow was being made two tiles
      -- adrift with the frame budget already spent walking
      if p.cellX ~= x or p.cellY ~= y then
        OPS.walk_to(G, { x = x, y = y, max_steps = 12 })
        if (ow.map and ow.map.id) ~= startMap
           and (p.cellX ~= x or p.cellY ~= y) then
          break
        end
      end
      table.insert(G.input.pressQueue, dir)
      G.input.state[dir] = true
      for _ = 1, 40 do
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
  -- SAY WHO IS IN THE WAY. Pathfinding treats a person as terrain and
  -- refuses to route through them, so a door with somebody planted in
  -- front of it reports only "couldn't reach" — and this game puts its
  -- gatekeepers exactly there. The Saffron gate guard explains the whole
  -- gate out loud, but only to someone who walks up to him, and the run
  -- could not even learn he existed from this message.
  local blockers = {}
  for _, npc in ipairs(ow.npcs or {}) do
    for _, t in ipairs(tiles) do
      if math.abs((npc.cellX or -99) - t.x)
         + math.abs((npc.cellY or -99) - t.y) <= 2 then
        local nm = (npc.def or {}).name
        if nm and not blockers[nm] then
          blockers[#blockers + 1] = ("%s at (%d,%d)")
            :format(nm, npc.cellX, npc.cellY)
          blockers[nm] = true
        end
      end
    end
  end
  if #blockers > 0 then
    return false, "couldn't reach the warp tile — somebody is standing by "
      .. "it: " .. table.concat(blockers, ", ")
      .. ". People who stand in front of doors in this game usually say "
      .. "why; interact with them to hear it."
  end
  return false, "couldn't reach the warp tile ("
    .. tostring(walk_why or "no reason recorded") .. ")"
end

-- Cross to the connected map in a direction (north/south/east/west). Finds
-- the walkable gap in that edge (BFS), walks to it, and steps off the seam to
-- trigger the connection. This is how you travel between routes/towns when
-- there is no door warp. Decision-free: the model picks the direction.
function OPS.cross(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
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

  local ex, ey, bfs_why, stallx, stally
  for round = 1, 4 do
    ex, ey, bfs_why, stallx, stally = bfs_to_edge(G, dir)
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
    -- DO NOT NAME THE CAUSE. BFS knows only that no walkable path reached
    -- the seam; it cannot tell rock from a sleeping Snorlax from a bush
    -- the party could cut down this minute. Claiming "terrain blocks it,
    -- the way goes through another map" sent the run around three sides of
    -- Kanto twice: north of Route 12 that is Snorlax and the answer is the
    -- Poke Flute, and east of Cerulean it is a CUT_TREE the party has
    -- known CUT for hours. Both are on screen. State the fact, and let
    -- what is standing there be read from the objects like anything else.
    -- ...AND SAY WHAT IS THERE. "Go and look" is not help when the
    -- looking is the harness's job: the objects, their tiles and whether
    -- a bush is cuttable are all in the map data already. East of
    -- Cerulean that is a CUT_TREE the party has known CUT for hours, and
    -- north of Route 12 it is a SNORLAX. Naming it costs nothing and
    -- decides nothing — cut it, wake it, or go round is still the
    -- model's call. Also point at the buildings on this edge: the
    -- Cerulean trashed house is a PASSAGE (a hole in its back wall), and
    -- a door is a way through that BFS over open ground cannot see.
    local lm = ow.map
    local W = (lm and lm.widthCells) or 0
    local H = (lm and lm.heightCells) or 0
    -- DISTANCE TO THE SEAM, not a fixed band. A five-cell strip missed
    -- Cerulean's CUT_TREE by three cells — it sits at 19,28 on a map 36
    -- tall, squarely across the southern approach — and the report came
    -- back "nothing sits against that edge" about the very bush that was
    -- stopping the walk. Rank by how close a thing is to the edge in
    -- question and name the nearest handful; no threshold to get wrong.
    -- `dir` here is the INPUT key (up/down/left/right); cmap turns it into
    -- the compass name the message prints. Comparing against "south" never
    -- matched, so seam_dist returned 9999 for everything, near_seam was
    -- always false, and the report said "nothing sits against that edge"
    -- about a Slowbro five tiles away and a CUT_TREE seven.
    local function seam_dist(x, y)
      if dir == "up"    then return y end
      if dir == "down"  then return (H - 1) - y end
      if dir == "left"  then return x end
      if dir == "right" then return (W - 1) - x end
      return 9999
    end
    local function near_seam(x, y)
      return seam_dist(x, y) <= 12
    end
    local blockers, doors = {}, {}
    -- RANK BY DISTANCE TO WHERE THE WALK STOPPED, not to the edge. The
    -- thing in the way is next to the last cell reached; anything else in
    -- the band is scenery. Route 2 stalled at 18,2 and the report named a
    -- CUT_TREE at 5,10 — ten cells off the seam, twenty-one from the walk,
    -- and irrelevant. Falls back to seam distance if the stall point is
    -- unknown.
    -- TWO LISTS, BOTH TRUE. What is beside the last cell reached is what
    -- stopped this walk. What is elsewhere on the map is still worth
    -- saying — a cuttable bush anywhere might be the thing that opens the
    -- road — it just is not "against that edge", which is what the old
    -- single list claimed about a tree ten cells off the seam.
    local elsewhere = {}
    -- ACTIONABLE ANYWHERE, INCIDENTAL ONLY IF CLOSE. Distance to the
    -- stall point is the wrong discriminator on its own: Route 2's one
    -- cuttable bush sits at 5,10 and gates the whole northern approach,
    -- while the walk stalled at 18,2 against terrain on the far side of
    -- the route — twenty-one cells away and still the thing to cut. A
    -- bush is worth naming wherever it is; a wandering trainer is only
    -- worth naming if it is next to where you actually stopped.
    local function add(tag, x, y, actionable)
      local d = (stallx and stally)
        and (math.abs(x - stallx) + math.abs(y - stally))
        or seam_dist(x, y)
      if actionable or not stallx or d <= 8 then
        blockers[#blockers + 1] = { s = ("%s at %d,%d"):format(tag, x, y),
                                    d = actionable and -1 or d }
      elseif #elsewhere < 4 then
        elsewhere[#elsewhere + 1] = ("%s at %d,%d"):format(tag, x, y)
      end
    end
    -- SAY WHICH BLOCKERS ARE PEOPLE. A wandering trainer standing in a
    -- corridor reads exactly like a wall in a BFS result, but this seam
    -- has been crossed 15 times and people step aside -- so "cannot be
    -- walked to" here means "not this second", not "not ever". Naming a
    -- bush as cuttable and a person as a person is the same act: saying
    -- what is there. Whether to wait, go round, or give up stays open.
    for _, npc in ipairs((ow.npcs) or {}) do
      local nx, ny = npc.cellX, npc.cellY
      if nx and ny and near_seam(nx, ny) then
        add(tostring((npc.def or {}).name or "someone")
            .. " (a person, who moves)", nx, ny)
      end
    end
    for _, f in ipairs(map_fixtures(G, (lm and lm.id)) or {}) do
      if f.x and f.y and near_seam(f.x, f.y) then
        add(tostring(f.name or "something"), f.x, f.y)
      end
    end
    -- cuttable bushes, the same tile test observe() uses, but only over
    -- the five-cell band against this edge rather than the whole map
    local ts = lm and lm.def and lm.def.tileset
    local want = (ts == "OVERWORLD" and 0x3d) or (ts == "GYM" and 0x50) or nil
    if lm and lm.cellTile and want then
      for cy = 0, math.min(H - 1, 71) do
        for cx = 0, math.min(W - 1, 71) do
          if near_seam(cx, cy) and lm:cellTile(cx, cy) == want
             and not lm:isWalkableCell(cx, cy) then
            add("CUT_TREE (a bush CUT clears)", cx, cy, true)
          end
        end
      end
    end
    for _, w in ipairs((md and md.warps) or {}) do
      if w.x and w.y and near_seam(w.x, w.y) and #doors < 6 then
        doors[#doors + 1] = ("%s at %d,%d")
          :format(tostring(w.destMap or "somewhere"), w.x, w.y)
      end
    end
    table.sort(blockers, function(a, b) return (a.d or 0) < (b.d or 0) end)
    local btxt = {}
    for i = 1, math.min(#blockers, 5) do btxt[i] = blockers[i].s end
    blockers = btxt
    local said = ""
    if #blockers > 0 then
      said = said .. " Right where the walk stopped: "
        .. table.concat(blockers, ", ") .. "."
    end
    if #elsewhere > 0 then
      -- NOT "on this map" — everything here already passed the near-seam
      -- filter, so this is only what lies near that edge but away from
      -- where the walk stalled. Route 2 has SIX cut bushes and this list
      -- can only ever hold the ones close to the seam; claiming the map
      -- would be the same over-reach the old "standing against that edge"
      -- line made, one level up.
      said = said .. " Also near that edge, though not what stopped you: "
        .. table.concat(elsewhere, ", ") .. "."
    end
    if #doors > 0 then
      said = said .. " Doors on that edge (a building can be a way "
        .. "THROUGH, not just a room): " .. table.concat(doors, ", ") .. "."
    end
    if said == "" then
      said = " Nothing this map lists sits against that edge."
    end
    return false, ("the %s seam of %s (to %s) cannot be walked to from "
      .. "here — no walkable path reaches it."):format(
        cmap[dir], tostring(startMap), tostring(dest and dest.map or "?"))
      .. (bfs_why and (" " .. bfs_why .. ".") or "") .. said
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
-- Same undersized-budget bug as settle_dialog (see there): 40 taps of B is
-- under two pages of typing, so backing out of anything wordy reported
-- failure with the box merely half-read. Progress-budgeted the same way.
ui_back_out = function(G)
  local stall, seen_top, seen_idx = 0, nil, nil
  for i = 1, 400 do
    local t = ui_top(G)
    dlg_trace(G, "back_out", i)
    if t == G.overworld or (t and (t.enemy or t.kind)) then return true end
    if t == seen_top and (t and t.pageIndex) == seen_idx then
      stall = stall + 1
      if stall > 100 then return false end
    else
      stall, seen_top, seen_idx = 0, t, (t and t.pageIndex)
    end
    U.tap(G, "b"); U.wait(6)
  end
  return false
end
local function bag_count(G, id)
  return ((G.save and G.save.inventory) or {})[id] or 0
end

-- WHAT THE SCREEN SAYS IS A NAME FOR THE THING (2026-08-17).
-- The bag row reads "POKé BALL". The internal id is POKE_BALL. The model
-- wrote POKEBALL and was told "POKEBALL is not sold here" while standing
-- at a counter with them on the shelf, and every other item op says
-- worse: `no POKEBALL in the bag` with ten of them in it. That last one
-- is the lying class outright — the harness knows the answer, has been
-- given a name that identifies the object beyond doubt, and denies the
-- object exists. See CLAIM_RULES: stop lying, stop hiding, stop refusing.
--
-- EXACT MODULO PUNCTUATION, AND NOTHING LOOSER. This does not guess. It
-- folds case and drops the separators that only exist because one name
-- was typed and the other compiled: POKE_BALL, POKE BALL, Poke Ball and
-- pokeball are one key, TM_01 and TM01 are one key. It will not match a
-- prefix, a substring or a near-miss, because buying, tossing and selling
-- the WRONG item costs real money or a real item, and a harness that
-- picks the object for you has stopped facilitating the decision and
-- started making it. If nothing matches, or somehow two things do, the
-- name is handed back untouched and the op fails exactly as it does now,
-- with its own message.
local function _item_key(s)
  return (tostring(s or ""):upper():gsub("[^A-Z0-9]", ""))
end

local function canon_item(G, name)
  if name == nil or name == "" then return name end
  local items = (G.data and G.data.items) or {}
  if items[name] ~= nil then return name end          -- an exact id wins
  local want, hit, n = _item_key(name), nil, 0
  for id in pairs(items) do
    if _item_key(id) == want then
      hit, n = id, n + 1
      if n > 1 then return name end                   -- ambiguous: hands off
    end
  end
  return hit or name
end

-- Buy c.count of c.item from this mart's clerk. Decision-free: the model
-- picks WHAT and HOW MANY; the menu driving is mechanics.
-- IS A SHOP ACTUALLY OPEN, or just SOMETHING? This was
--   ui_is_menu(G) or ui_is_list(G)
-- which is "the top of the stack is any list at all" -- and the START menu
-- is a list whose first row has onSelect, so it passed. buy and sell then
-- rode whatever was open: a stray START menu left up by an earlier op made
-- OPS.buy press A into SAVE/OPTION/EXIT and call the result a shop.
-- The real shop stack is ShopMenu (pushed through Screens, so it carries a
-- screenId) with its BUY/SELL ListMenu on top (pushed raw, so it does not
-- -- but ListMenu keeps the title it was built with). Ask for those two by
-- name rather than for the shape they happen to share with everything else.
local function ui_shop_up(G)
  local t = ui_top(G)
  if not t then return false end
  if tostring(t.screenId or "") == "ShopMenu" then return true end
  local title = tostring(t.title or ""):upper()
  return (title == "BUY" or title == "SELL") and ui_is_list(G)
end

-- WHERE THE NEAREST COUNTER IS. "No shop clerk on this map" is true and
-- useless when you are standing in the street outside the mart: the run
-- worked out for itself that a NUGGET covers the 100 the day care wanted,
-- issued the sell, and was told only that this was the wrong place --
-- with no hint that the right place was one door away. The door and its
-- destination are both in the map the game already gives us, and the
-- MART SIGN is on screen beside it.
-- ...AND THEN WALK IN. Being told "the door is at 25,25" costs a whole
-- round to act on, and the run spent several standing in the street
-- re-issuing sell. Walking to the counter was already execution here --
-- OPS.sell walks to the clerk once inside, and OPS.interact walks itself
-- adjacent before pressing -- so stepping through the door of the shop
-- you just asked to trade at is the same mechanical errand, not a
-- decision. WHAT to sell, and whether to sell at all, stays the model's.
-- Does this map actually have somebody to trade with? A "MART" substring
-- said yes to CELADON_MART_ELEVATOR and CELADON_MART_ROOF, and said yes
-- to CELADON_MART_1F, whose only staff is a RECEPTIONIST who sells
-- nothing -- so the first door tried in Celadon could have been a lift.
-- Ask the destination whether it has a counter instead of guessing from
-- its name.
--
-- ON THE EDGE, AND FLAGGED AS SUCH (user, 2026-08-15). This reads the
-- objects of a map nobody has entered. The defence was "the harness reads,
-- it never tells" -- but the read decides WHERE THE BODY GOES, and the
-- next observation is a mart with a clerk in front of it, so the knowledge
-- reaches the model through the world instead of through a sentence. BFS
-- over the collision map is not the same: BFS routes to a place the MODEL
-- named, while this picks which of several destinations to walk into.
-- Judged acceptable because "sell this" plausibly implies "at a counter",
-- and the cost of guessing wrong is a wasted round rather than a lost
-- Pokemon -- but it is the one place in this harness that reads ahead of
-- what has been walked. Everything else (doorstep placement, the passage
-- note, the seam blocker report) is built from walked evidence only.
-- See ~/TODO.md for the tightenings on the table.
local function map_has_counter(G, id)
  local m = id and G.data and G.data.maps and G.data.maps[id]
  for _, o in ipairs((m and m.objects) or {}) do
    local nm = tostring(o.name or ""):upper()
    if nm:find("CLERK") or nm:find("CASHIER") then return true end
  end
  return false
end

local function enter_shop(G)
  local ow = G.overworld
  local md = ow and ow.map and G.data and G.data.maps
              and G.data.maps[ow.map.id]
  for _, w in ipairs((md and md.warps) or {}) do
    -- BOTH TESTS. A counter alone is not a shop that trades: BIKE_SHOP
    -- has a BIKESHOP_CLERK, so "has a clerk" walked into the bike shop,
    -- whose man only says "How do you like your new BICYCLE?" and opens
    -- no menu. A MART in the id alone is not enough either -- that lets
    -- in CELADON_MART_1F (receptionist), _ELEVATOR and _ROOF. Require a
    -- mart AND a counter. Both are readable from the street: the buildings
    -- carry their own signposts, which is why picking between them is
    -- following a sign rather than reading the map table.
    if w.x and w.y and tostring(w.destMap or ""):find("MART")
       and map_has_counter(G, w.destMap) then
      local ok = OPS.use_warp(G, { x = w.x, y = w.y })
      return ok and true or false
    end
  end
  return false
end

local function shop_door_hint(G)
  local ow = G.overworld
  local md = ow and ow.map and G.data and G.data.maps
              and G.data.maps[ow.map.id]
  for _, w in ipairs((md and md.warps) or {}) do
    -- LOOSER THAN enter_shop ON PURPOSE. Walking through the wrong door
    -- by itself is a wasted round; NAMING a door and letting the model
    -- decide costs nothing. Celadon's only street door is MART_1F, whose
    -- staff is a receptionist and whose counters are upstairs — not worth
    -- auto-entering, very much worth mentioning.
    local d = tostring(w.destMap or "")
    if w.x and w.y and (map_has_counter(G, w.destMap) or d:find("MART")) then
      return (" The door into %s is at %d,%d on this map — go in and sell "
              .. "at the counter."):format(d, w.x, w.y)
    end
  end
  return ""
end

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
      return false, ("cannot afford %s: it costs %d and you have %d — "
        .. "the clerk also BUYS: sell spares "
        .. "({\"op\":\"sell\",\"item\":...}) to raise money")
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
    local went_in = false
    if not clerk then
      -- one try at the door, then look again
      went_in = enter_shop(G)
      if went_in then
        ow = G.overworld
        for _, npc in ipairs(ow.npcs or {}) do
          local nm = ((npc.def or {}).name or ""):upper()
          if nm:find("CLERK") or nm:find("CASHIER") then clerk = npc break end
        end
      end
    end
    if not clerk then
      -- TWO DIFFERENT FAILURES, TWO DIFFERENT SENTENCES. Saying "no mart
      -- door on this map either" after walking through one is a lie of
      -- exactly the kind this harness keeps having to un-tell.
      if went_in then
        return false, "went into the shop, but found no clerk inside to "
          .. "trade with"
      end
      return false, "no shop clerk here, and no door to a shop counter "
        .. "on this map." .. shop_door_hint(G)
    end
    if not OPS.interact(G, { x = clerk.cellX, y = clerk.cellY,
                             stop_at_menu = true }) then
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

-- Sell c.count of c.item to this mart's clerk (count omitted = the whole
-- stack). WHAT to part with is the model's judgment; the counter is
-- mechanics. Selling both raises money and frees bag slots — a NUGGET
-- exists for exactly this.
function OPS.sell(G, c)
  if not c.item then return false, "sell needs item" end
  local have0 = bag_count(G, c.item)
  if have0 < 1 then return false, "no " .. c.item .. " in the bag" end
  local want = math.min(c.count or have0, have0)
  if G.overworld and G.stack:top() ~= G.overworld then
    if not ui_shop_up(G) then ui_press_until(G, ui_shop_up, "a", 20) end
    if not ui_shop_up(G) then ui_back_out(G) end
  end
  if G.overworld and G.stack:top() == G.overworld then
    local ow = G.overworld
    local clerk
    for _, npc in ipairs(ow.npcs or {}) do
      local nm = ((npc.def or {}).name or ""):upper()
      if nm:find("CLERK") or nm:find("CASHIER") then clerk = npc break end
    end
    local went_in = false
    if not clerk then
      -- one try at the door, then look again
      went_in = enter_shop(G)
      if went_in then
        ow = G.overworld
        for _, npc in ipairs(ow.npcs or {}) do
          local nm = ((npc.def or {}).name or ""):upper()
          if nm:find("CLERK") or nm:find("CASHIER") then clerk = npc break end
        end
      end
    end
    if not clerk then
      -- TWO DIFFERENT FAILURES, TWO DIFFERENT SENTENCES. Saying "no mart
      -- door on this map either" after walking through one is a lie of
      -- exactly the kind this harness keeps having to un-tell.
      if went_in then
        return false, "went into the shop, but found no clerk inside to "
          .. "trade with"
      end
      return false, "no shop clerk here, and no door to a shop counter "
        .. "on this map." .. shop_door_hint(G)
    end
    if not OPS.interact(G, { x = clerk.cellX, y = clerk.cellY,
                             stop_at_menu = true }) then
      return false, "couldn't reach the clerk"
    end
    if not ui_press_until(G, ui_is_menu, "a", 60) then
      ui_back_out(G)
      return false, "shop menu never opened"
    end
  end
  if ui_is_menu(G) then
    ui_cursor_to(G, "index", 2)                   -- SELL
    U.tap(G, "a"); U.wait(10)
  end
  if not ui_press_until(G, ui_is_list, "a", 30) then
    ui_close_shop(G); ui_back_out(G)
    return false, "sell list never opened"
  end
  local idx
  for i, row in ipairs(ui_rows(G)) do
    if row.value == c.item then idx = i break end
  end
  if not idx then
    ui_close_shop(G); ui_back_out(G)
    return false, c.item .. " is not in the sell list (key items "
      .. "cannot be sold)"
  end
  if not ui_cursor_to(G, "index", idx) then
    ui_close_shop(G); ui_back_out(G)
    return false, "cursor stuck on the sell list"
  end
  U.tap(G, "a"); U.wait(6)
  if ui_press_until(G, ui_is_qty, "a", 20) then
    if not ui_qty_to(G, want) then
      ui_close_shop(G); ui_back_out(G)
      return false, "couldn't set the quantity"
    end
    U.tap(G, "a"); U.wait(6)
  end
  if ui_is_choice(G) then                          -- "I can pay N. OK?"
    ui_cursor_to(G, "index", 1)
    U.tap(G, "a"); U.wait(10)
  end
  ui_press_until(G, ui_is_list, "a", 20)
  local have = bag_count(G, c.item)
  ui_close_shop(G)
  ui_back_out(G)
  if have >= have0 then
    return false, "the sale did not go through"
  end
  return true, ("sold %s x%d — money now %d%s"):format(
    c.item, have0 - have, (G.save and G.save.money) or 0,
    have == 0 and ", slot freed" or "")
end

-- Use a bag item in the field (START -> ITEM -> item -> USE -> party
-- slot). Healing items target c.slot (default the lead).
function OPS.use_item(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
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
  -- SLOT IS 1-BASED, AND 0 IS TRUTHY IN LUA. `c.slot or 1` left slot=0 on
  -- a 0-based request, party[0] is nil, so the move list came out EMPTY
  -- and every forget= was rejected as "not one of its moves" — against a
  -- Pokemon that "knows ". The model asked to forget GROWL, twice, and
  -- was refused both times by this; the Razor Leaf that got written over
  -- instead was never its choice. Clamp, and say so when the slot is real
  -- but out of range.
  local party = (G.save and G.save.party) or {}
  local slot = math.floor(tonumber(c.slot) or 1)
  if slot < 1 then slot = 1 end            -- there is no slot 0
  if #party > 0 and slot > #party then
    ui_back_out(G)
    return false, ("no party slot %d — the party has %d")
      :format(slot, #party)
  end
  pm = ui_top(G)
  if pm and pm.screenId == "PartyMenu" then
    ui_cursor_to(G, "index", slot)
    U.tap(G, "a"); U.wait(10)
  end
  -- TM/HM teach flow. The MODEL owns every choice in it: which mon
  -- (c.slot) and — when the mon already knows four — which move to write
  -- over (c.forget). With no c.forget the teach is ABANDONED and the op
  -- reports all four current moves, so the overwrite is chosen looking at
  -- the whole moveset, never defaulted to whatever the cursor sat on.
  local HM_MOVES = { CUT = true, FLY = true, SURF = true,
                     STRENGTH = true, FLASH = true }
  local mon = party[slot]
  local monmoves = {}
  for j, mv in ipairs((mon and mon.moves) or {}) do
    monmoves[j] = tostring(type(mv) == "table" and mv.id or mv)
  end
  local function page_text()
    local t = G.stack:top()
    if t and t.pages and t.pageIndex then
      local pg = t.pages[t.pageIndex]
      if type(pg) == "table" then return table.concat(pg, " ") end
      return tostring(pg or "")
    end
    return ""
  end
  if c.forget and HM_MOVES[c.forget] then
    ui_back_out(G)
    return false, "HM moves cannot be forgotten; pick a different forget="
  end
  local abandoned
  -- "Not compatible" is ON SCREEN — the game says so by name the moment a
  -- TM meets a Pokemon that cannot take it. Without catching it here the
  -- fall-through blamed the FULL MOVE LIST instead ("it already knows four
  -- moves, pick a forget="), which is advice that can never work: no
  -- choice of forget= makes TM_WATER_GUN teachable to a Charmeleon, so the
  -- model would burn every round overwriting a different move for nothing.
  local incompatible
  for _ = 1, 50 do
    local t = G.stack:top()
    if t == G.overworld then break end
    do
      local _tx = page_text()
      if _tx:find("not compatible") or _tx:find("Not compatible")
         or _tx:find("NOT COMPATIBLE") then
        incompatible = true
      end
    end
    if t and t.newMoveId and t.selecting then
      -- the forget list is live: pick the model's chosen move
      local idx
      for j, name in ipairs(monmoves) do
        if name == c.forget then idx = j end
      end
      if not idx then
        abandoned = (c.forget or "nothing")
          .. " is not one of its moves; teach ABANDONED"
        U.tap(G, "b"); U.wait(8)
      else
        for _ = 1, idx - 1 do U.tap(G, "down"); U.wait(3) end
        U.tap(G, "a"); U.wait(10)
      end
    elseif ui_is_choice(G) then
      local txt = page_text()
      local learnq = txt:find("older") or txt:find("trying to learn")
      if learnq and not (c.forget and not abandoned) then
        U.tap(G, "b"); U.wait(8)     -- NO: don't delete, go to abandon
      elseif txt:find("bandon") or txt:find("ive up") then
        U.tap(G, "a"); U.wait(8)     -- YES: stop trying to learn
      else
        U.tap(G, "a"); U.wait(8)     -- teach?/use? prompts move along
      end
    else
      U.tap(G, "a"); U.wait(5)
    end
  end
  ui_back_out(G)
  -- report from the party record, the only truth that matters
  local after = {}
  for j, mv in ipairs((mon and mon.moves) or {}) do
    after[j] = tostring(type(mv) == "table" and mv.id or mv)
  end
  local gained
  for _, name in ipairs(after) do
    local old = false
    for _, o in ipairs(monmoves) do if o == name then old = true end end
    if not old then gained = name end
  end
  if gained then
    return true, "used " .. c.item .. " — slot " .. slot
      .. " learned " .. gained
  end
  if abandoned then
    -- An empty list is never the Pokemon's fault; it means we looked in
    -- the wrong place. Saying "It knows ." sent the model hunting for a
    -- better forget= when no name could ever have matched.
    if #monmoves == 0 then
      return false, abandoned .. ". The harness could not read slot "
        .. slot .. "'s moves, so no forget= could match — this is a "
        .. "harness fault, not a bad choice of move."
    end
    return false, abandoned .. ". It knows "
      .. table.concat(monmoves, ", ")
      .. ". Re-send use_item with forget= one of those (HM moves "
      .. "cannot be forgotten)."
  end
  if c.item:find("^TM_") or c.item:find("^HM_") then
    if incompatible then
      return false, (mon and mon.species or ("slot " .. slot))
        .. " is NOT COMPATIBLE with " .. c.item
        .. " — that species can never learn this move, so no forget= will "
        .. "help. Try the machine on a different party member, or a "
        .. "different machine."
    end
    if #monmoves >= 4 then
      return false, "it already knows four moves: "
        .. table.concat(monmoves, ", ")
        .. ". Choose which to write over and re-send use_item with "
        .. "forget= that move (HM moves cannot be forgotten)."
    end
    return false, "the teach did not go through"
  end
  return true, "used " .. c.item
end

-- Use a FIELD MOVE (CUT and kin) at a target tile: stand orthogonally
-- adjacent to (x,y) facing it, then drive START -> POKeMON -> the mon
-- that knows the move -> the move in its submenu. WHICH party member
-- knows it is a party-list fact (mechanics); WHETHER and WHERE to use it
-- was the model's decision when it named the tile.
function OPS.field_move(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  local mv = c.move
  if not mv then return false, "field_move needs move" end
  local slot
  for i, mon in ipairs((G.save and G.save.party) or {}) do
    for _, m in ipairs(mon.moves or {}) do
      local id = tostring(type(m) == "table" and m.id or m)
      if id == mv then slot = i break end
    end
    if slot then break end
  end
  if not slot then
    if bag_count(G, "HM_" .. mv) > 0 or bag_count(G, "TM_" .. mv) > 0 then
      return false, "no party Pokemon knows " .. mv
        .. " — teach it first (use_item with the TM/HM in your bag)"
    end
    return false, "no party Pokemon knows " .. mv
      .. " and NO TM/HM for it is in the bag — someone in the world has "
      .. "to hand that machine over before " .. mv .. " can ever be used"
  end
  local ow = G.overworld
  local p = ow.player
  if c.x and c.y then
    local adj = { {c.x, c.y + 1, "up"}, {c.x, c.y - 1, "down"},
                  {c.x - 1, c.y, "right"}, {c.x + 1, c.y, "left"} }
    local placed
    for _, a in ipairs(adj) do
      if p.cellX == a[1] and p.cellY == a[2] then placed = a break end
    end
    if not placed then
      for _, a in ipairs(adj) do
        OPS.walk_to(G, { x = a[1], y = a[2], max_steps = 60 })
        if p.cellX == a[1] and p.cellY == a[2] then placed = a break end
      end
    end
    if not placed then
      return false, "no reachable tile adjacent to the target"
    end
    if p.facing ~= placed[3] then U.tap(G, placed[3]); U.wait(4) end
  end
  U.tap(G, "start"); U.wait(8)
  local menu = ui_top(G)
  if not (menu and menu.screenId == "StartMenu") then
    ui_back_out(G); return false, "start menu never opened"
  end
  local row
  for i, it in ipairs(menu.items or {}) do
    local l = it.label or ""
    if l:find("POK") and l:find("MON") then row = i break end
  end
  if not row or not ui_cursor_to(G, "index", row) then
    ui_back_out(G); return false, "no POKeMON row"
  end
  U.tap(G, "a"); U.wait(10)
  local pm = ui_top(G)
  if not (pm and pm.screenId == "PartyMenu") then
    ui_back_out(G); return false, "party menu never opened"
  end
  ui_cursor_to(G, "index", slot)
  U.tap(G, "a"); U.wait(8)
  -- the field-move submenu is PartyMenu-INTERNAL state (subItems /
  -- subIndex), not a pushed screen: ui_top kept reporting the party list
  -- and the label lookup read mon rows, failing "CUT was not offered"
  -- with Cut sitting right there
  local pm2 = G.stack:top()
  local subs = pm2 and pm2.subItems
  local mrow
  for i, it in ipairs(subs or {}) do
    local lab = ((it.label or it.text or it.action or "") .. ""):upper()
    if lab:find(mv, 1, true) then mrow = i break end
  end
  if not mrow then
    local seen = {}
    for _, it in ipairs(subs or {}) do
      seen[#seen + 1] = tostring(it.label or it.text or it.action or "?")
    end
    ui_back_out(G)
    return false, mv .. " was not offered in the menu (it lists: "
      .. table.concat(seen, ", ") .. ")"
  end
  for _ = 1, 40 do
    if not pm2.subIndex or pm2.subIndex == mrow then break end
    U.tap(G, pm2.subIndex > mrow and "up" or "down"); U.wait(3)
  end
  U.tap(G, "a"); U.wait(10)
  local said
  for _ = 1, 30 do
    local t = G.stack:top()
    if t == ow then break end
    if t and t.pages and t.pageIndex then
      local pg = t.pages[t.pageIndex]
      if type(pg) == "table" then said = table.concat(pg, " ")
      else said = tostring(pg or "") end
    end
    U.tap(G, "a"); U.wait(5)
  end
  U.wait(24)   -- the cut animation finishes after the text closes
  return true, "used " .. mv .. (said and (" — " .. said) or "")
end

-- Toss items from the bag. WHAT to toss is entirely the model's call
-- (its treasure vs its junk); driving the TOSS row and the quantity
-- wheel is mechanics. Born at the captain's cabin: a 20-of-20 bag ate
-- HM01 silently.
function OPS.toss(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  if not c.item then return false, "toss needs item" end
  local have = bag_count(G, c.item)
  if have < 1 then return false, "no " .. c.item .. " in the bag" end
  -- KEY ITEMS CANNOT BE THROWN AWAY. The game says so itself
  -- ("That's too impor-tant to toss!") and items.lua marks them
  -- keyItem = true, so there is no reason to walk the bag menu and find
  -- out. The run reached for the S.S. TICKET to make room for the SILPH
  -- SCOPE — sound thinking, the boat has sailed and the ticket is spent —
  -- and gen 1 simply will not allow it. Say which ones it CAN throw.
  local def = G.data and G.data.items and G.data.items[c.item]
  if is_key_item(def) then
    local spare = {}
    for id, n in pairs((G.save and G.save.inventory) or {}) do
      local d2 = G.data.items and G.data.items[id]
      if (tonumber(n) or 0) > 0 and not is_key_item(d2) then
        spare[#spare + 1] = id
      end
    end
    table.sort(spare)
    return false, c.item .. " is a KEY ITEM — \"That's too important to "
      .. "toss!\" — this game never lets one go, spent or not."
      .. (#spare > 0
          and (" Things you CAN throw away: " .. table.concat(spare, ", ")
               .. ".")
          or " Nothing in the bag can be thrown away.")
  end
  local n = math.min(c.count or have, have)
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
  if ui_is_menu(G) or ui_is_choice(G) then     -- USE/TOSS -> TOSS (row 2)
    ui_cursor_to(G, "index", 2)
    U.tap(G, "a"); U.wait(8)
  end
  for _ = 1, n - 1 do                          -- quantity wheel starts at 1
    U.tap(G, "up"); U.wait(2)
  end
  U.tap(G, "a"); U.wait(8)
  if ui_is_choice(G) then                      -- "is that OK?" -> yes
    U.tap(G, "a"); U.wait(8)
  end
  for _ = 1, 10 do
    local t = ui_top(G)
    if not (t and t.pages) then break end
    U.tap(G, "a"); U.wait(5)
  end
  ui_back_out(G)
  local left = bag_count(G, c.item)
  if left < have then
    return true, "tossed " .. (have - left) .. " " .. c.item
      .. (left > 0 and (", " .. left .. " left") or ", slot freed")
  end
  return false, "toss did not go through"
end

-- ------------------------------------------------------------ PC storage
-- The fourth answer to a full bag, and the only reversible one. Tossing
-- HM01 is forever; storing it is a walk back to any Pokemon Center. WHICH
-- item leaves the bag stays the plan's call — this is the verb, not the
-- choice.
--
-- The menus differ by location (OverworldController:openPC): the bedroom PC
-- in REDS_HOUSE_2F runs item storage directly, every other PC first shows
-- the multi-PC menu whose own-name row is the item storage. Drive by LABEL,
-- never by row index: the rows present depend on the Pokedex and on whether
-- Bill has been met.
local function ui_row_labelled(G, want)
  for i, r in ipairs(ui_rows(G) or {}) do
    local lb = r.label
    if type(lb) == "string" and lb:upper():find(want, 1, true) then
      return i
    end
  end
end

local function pc_open_storage(G)
  local ow = G.overworld
  local px, py, pfacing
  for _, f in ipairs(map_fixtures(G, ((ow.map or {}).id))) do
    if f.name == "PC" then px, py, pfacing = f.x, f.y, f.facing end
  end
  if not px then
    return false, "there is no PC on this map (every Pokemon Center has one)"
  end
  -- stand beside it and face it, WITHOUT the A-mash interact() ends with:
  -- that would walk straight through these menus
  local p = ow.player
  local adj = { { px, py + 1, "up" }, { px, py - 1, "down" },
                { px - 1, py, "right" }, { px + 1, py, "left" } }
  if pfacing then
    local keep = {}
    for _, a in ipairs(adj) do
      if a[3] == pfacing then keep[#keep + 1] = a end
    end
    if #keep > 0 then adj = keep end
  end
  local at = false
  for _ = 1, 2 do
    for _, a in ipairs(adj) do
      if p.cellX == a[1] and p.cellY == a[2] then
        if p.facing ~= a[3] then U.tap(G, a[3]); U.wait(3) end
        at = true; break
      end
    end
    if at then break end
    for _, a in ipairs(adj) do
      OPS.walk_to(G, { x = a[1], y = a[2], max_steps = 60 })
      if p.cellX == a[1] and p.cellY == a[2] then break end
    end
  end
  if not at then return false, "could not stand at the PC" end
  U.tap(G, "a"); U.wait(10)
  for _ = 1, 12 do                       -- through "Turned on the PC" text
    if ui_is_menu(G) then break end
    U.tap(G, "a"); U.wait(5)
  end
  if not ui_is_menu(G) then
    ui_back_out(G); return false, "the PC never opened"
  end
  if not ui_row_labelled(G, "DEPOSIT ITEM") then   -- the multi-PC menu
    local own = ui_row_labelled(G, "'S PC")
    -- "SOMEONE'S PC"/"BILL'S PC" is the BOX menu and matches that too; the
    -- item storage is the row carrying the player's own name
    local name = ((G.save or {}).player or {}).name
    if name and name ~= "" then
      own = ui_row_labelled(G, name:upper() .. "'S PC") or own
    end
    if not own then
      ui_back_out(G); return false, "no item-storage row on the PC menu"
    end
    ui_cursor_to(G, "index", own)
    U.tap(G, "a"); U.wait(10)
  end
  if not ui_row_labelled(G, "DEPOSIT ITEM") then
    ui_back_out(G); return false, "item storage never opened"
  end
  return true
end

local function pc_move(G, c, row, giving)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  if not c.item then return false, "needs item" end
  local before = bag_count(G, c.item)
  local stored = ((G.save or {}).pcItems or {})[c.item] or 0
  if giving and before < 1 then
    return false, "no " .. c.item .. " in the bag to store"
  end
  if not giving and stored < 1 then
    return false, "the PC is not holding any " .. c.item
  end
  local ok, why = pc_open_storage(G)
  if not ok then return false, why end
  local r = ui_row_labelled(G, row)
  if not r then ui_back_out(G); return false, row .. " row missing" end
  ui_cursor_to(G, "index", r)
  U.tap(G, "a"); U.wait(8)
  if not ui_is_list(G) then
    ui_back_out(G)
    return false, (giving and "the bag" or "the PC") .. " list never opened"
  end
  local want
  for i, it in ipairs(ui_rows(G) or {}) do
    if it.value == c.item then want = i break end
  end
  if not want then
    ui_back_out(G)
    return false, c.item .. " is not in the " ..
      (giving and "bag" or "PC") .. " list"
  end
  ui_cursor_to(G, "index", want)
  U.tap(G, "a"); U.wait(8)
  -- Key items and HMs move one with no prompt (IsKeyItem, players_pc.asm);
  -- everything else raises the quantity selector.
  local n = math.min(c.count or 1, giving and before or stored)
  if ui_is_qty(G) then
    ui_qty_to(G, math.max(1, n))
    U.tap(G, "a"); U.wait(8)
  end
  for _ = 1, 8 do                        -- footer/confirm text
    local t = ui_top(G)
    if not (t and t.pages) then break end
    U.tap(G, "a"); U.wait(5)
  end
  ui_back_out(G)
  local after = bag_count(G, c.item)
  if giving and after < before then
    return true, ("stored %d %s via PC (%d left in the bag)")
      :format(before - after, c.item, after)
  end
  if not giving and after > before then
    return true, ("withdrew %d %s from the PC")
      :format(after - before, c.item)
  end
  if giving then
    return false, "the PC would not take it (its 50 stacks may be full)"
  end
  return false, "nothing came out — the bag may be full at 20 kinds"
end

-- Move an item from the bag into PC storage. Frees a bag slot WITHOUT
-- destroying anything.
function OPS.store_item(G, c) return pc_move(G, c, "DEPOSIT ITEM", true) end

-- Take an item back out of PC storage.
function OPS.retrieve_item(G, c)
  return pc_move(G, c, "WITHDRAW ITEM", false)
end

-- THE DAY CARE, AS A BOX. Boarding a Pokemon was reachable only by saying
-- "yes" to the DAY-CARE MAN, and the party picker that follows takes an
-- A-press — so the same reflex that answers signposts handed over a level
-- 40 CHARIZARD and picked slot 1 to do it. These name the deed and the
-- slot the way store_item/retrieve_item do for the PC: the model says WHO
-- and WHETHER, the harness drives the menus. Everything they refuse is a
-- fact the game would refuse on anyway, reported before any button moves.
local function daycare_talk(G, slot)
  -- SAY THE PLAIN THING FIRST. Issued from inside the Poke Mart, the only
  -- complaint was that an object named DAYCARE_GENTLEMAN was not visible,
  -- which reads like a harness fault rather than "you are in the wrong
  -- building". The day care is its own map on ROUTE_5.
  local here
  for _, npc in ipairs((G.overworld and G.overworld.npcs) or {}) do
    if ((npc.def or {}).name or "") == "DAYCARE_GENTLEMAN" then here = true end
  end
  if not here then
    return false, "the DAY-CARE MAN is not in this building — the day care "
      .. "is its own small house on ROUTE_5, and you have to be inside it"
  end
  -- pass the slot through: this op HAS chosen one, so the party-picker
  -- guard in settle_dialog must let it past
  local ok, why = OPS.interact(G, { name = "DAYCARE_GENTLEMAN",
                                    answer = "yes", read_question = true,
                                    slot = slot })
  if not ok then return false, why or "could not talk to the day care man" end
  return true
end

-- HEALING, AS ONE ACT. "Go to the Center and heal" was four things the
-- model had to author every time: notice the party is hurt, route to the
-- town with a Center, get through its door, and then find the NURSE
-- specifically -- not the SUPER_NERD, and above all not the
-- LINK_RECEPTIONIST, whose "we have to save the game" prompt once held a
-- campaign for 23 escalations. Every one of those but the first is
-- mechanical, and the nurse has needed special-casing in five separate
-- places already; this puts her in one.
--
-- FINDING THE DOOR IS ALLOWED HERE (user ruling, 2026-08-15): Centers and
-- marts are LABELLED IN THE OVERWORLD -- every one of the game's 11
-- Centers has its own signpost object, the two cave-mouth ones on Route 4
-- and Route 10 included -- so "that building is a Pokemon Center" is a
-- thing a player reads off the screen, not something the harness smuggles
-- out of the map table. Walking to a signed building is following a sign.
-- That is why this needs no walked-door restriction, and it is the same
-- reasoning that settles enter_shop. c.door stays as an override.
function OPS.heal(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  local function find_nurse()
    for _, npc in ipairs((G.overworld.npcs) or {}) do
      if tostring((npc.def or {}).name or ""):upper():find("NURSE") then
        return npc
      end
    end
  end
  local function hurt()
    local n = 0
    for _, m in ipairs(((G.save or {}).party) or {}) do
      if (tonumber(m.hp) or 0) < (tonumber((m.stats or {}).hp) or 0) then
        n = n + 1
      end
    end
    return n
  end
  local before = hurt()
  local nurse = find_nurse()
  local went_in = false
  if not nurse then
    local d = c.door
    if not (d and d.x and d.y) then
      local ow = G.overworld
      local md = ow and ow.map and G.data and G.data.maps
                  and G.data.maps[ow.map.id]
      for _, w in ipairs((md and md.warps) or {}) do
        if w.x and w.y
           and tostring(w.destMap or ""):find("POKECENTER") then
          d = { x = w.x, y = w.y }
          break
        end
      end
    end
    if not (d and d.x and d.y) then
      return false, "no Pokemon Center nurse here, and no Center door on "
        .. "this map"
    end
    went_in = OPS.use_warp(G, { x = d.x, y = d.y }) and true or false
    if not went_in then
      return false, ("could not get through the Center door at %s,%s")
        :format(tostring(d.x), tostring(d.y))
    end
    nurse = find_nurse()
  end
  if not nurse then
    return false, "went through the door but found no nurse inside"
  end
  local ok, why = OPS.interact(G, { x = nurse.cellX, y = nurse.cellY,
                                    answer = "yes", read_question = true })
  if not ok then return false, why or "could not reach the nurse" end
  for _ = 1, 60 do                       -- ride the heal ceremony out
    if G.stack:top() == G.overworld then break end
    U.tap(G, "a"); U.wait(6)
  end
  ui_back_out(G)
  local after = hurt()
  if after == 0 then
    return true, (went_in and "went into the Center and healed" or "healed")
      .. " — the whole party is at full HP"
  end
  return false, ("talked to the nurse but %d Pokemon %s still hurt")
    :format(after, after == 1 and "is" or "are")
end

-- THE ELEVATOR. The panel is a bg_event: face it, press A, and with the
-- LIFT KEY in the bag a floor list opens (engine/events/elevator.asm
-- DisplayElevatorFloorMenu). Choosing rewrites the car's exit warps and
-- hands control back -- you then WALK OUT of the car onto that floor,
-- which is why this op ends with you still inside it.
function OPS.elevator(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  if not c.floor then
    return false, "elevator needs floor=<label>, e.g. floor=\"B4F\""
  end
  local want = tostring(c.floor):upper()
  -- THE PANEL IS A SIGN. data/maps has it as
  -- signs = {{ text = "TEXT_ROCKETHIDEOUTELEVATOR", x = 1, y = 1 }} —
  -- not an object and not a fixture, which is where this looked first and
  -- would never have found it. Signs are usually flavour text, which is
  -- presumably why the run rode the car twice without pressing anything.
  local ow = G.overworld
  local md = ow and ow.map and G.data and G.data.maps
             and G.data.maps[ow.map.id]
  local px, py
  for _, sg in ipairs((md and md.signs) or {}) do
    if tostring(sg.name or sg.text or ""):upper():find("ELEVATOR") then
      px, py = sg.x, sg.y
    end
  end
  for _, f in ipairs(map_fixtures(G, ((G.overworld.map or {}).id)) or {}) do
    if not px and tostring(f.name or ""):upper():find("ELEVATOR") then
      px, py = f.x, f.y
    end
  end
  if not px then
    for _, npc in ipairs((G.overworld.npcs) or {}) do
      if tostring((npc.def or {}).name or ""):upper():find("ELEVATOR") then
        px, py = npc.cellX, npc.cellY
      end
    end
  end
  if not px then
    return false, "no elevator panel visible on this map"
  end
  local ok, why = OPS.interact(G, { x = px, y = py, floor = want })
  if not ok then return false, why or "could not reach the panel" end
  local t
  for _ = 1, 20 do
    t = ui_top(G)
    if t and t.items and t.title
       and tostring(t.title):upper():find("FLOOR") then break end
    U.tap(G, "a"); U.wait(6)
  end
  t = ui_top(G)
  if not (t and t.items) then
    ui_back_out(G)
    return false, "the panel opened no floor menu — the LIFT KEY is what "
      .. "it wants (it says so out loud without one)"
  end
  local idx, offer = nil, {}
  for i, it in ipairs(t.items) do
    local lab = tostring(it.label or ""):upper()
    offer[#offer + 1] = lab
    if lab == want or lab:find(want, 1, true) then idx = i end
  end
  -- A PANEL IS A DOORWAY THAT DOES NOT LOOK LIKE ONE. The car has two
  -- warp tiles and both of them lead to the floor you are already on,
  -- because gen1 REWRITES an elevator's warp destinations at runtime from
  -- this menu. So the floors are not warps in the map data at all and the
  -- door-counter is structurally blind to them: it reported nothing
  -- unopened inside CELADON_MART_ELEVATOR, a car serving five floors that
  -- the run rode four times and left four times.
  -- The menu on screen is the only place the floors exist, so record them
  -- the moment they are on screen. Learned by pressing, never read ahead.
  lift_floors[tostring((G.overworld.map or {}).id)] = offer
  if not idx then
    ui_back_out(G)
    return false, ("no floor called %s — it offers %s")
      :format(want, table.concat(offer, ", "))
  end
  ui_cursor_to(G, "index", idx)
  U.tap(G, "a"); U.wait(10)
  for _ = 1, 60 do              -- ride the shake out
    if G.stack:top() == G.overworld then break end
    U.tap(G, "a"); U.wait(5)
  end
  ui_back_out(G)
  return true, ("rode to %s — you are still IN the car; walk out of its "
    .. "door to arrive. This panel offers %s")
    :format(want, table.concat(offer, ", "))
end

-- CHOOSE WHO GOES OUT FIRST. There was no way to. Battles are played by a
-- policy rather than turn by turn, so the model's only lever on which
-- Pokemon fights is WHICH ONE LEADS — the first unfainted slot is sent
-- out — and nothing in the vocabulary could move a party member. The run
-- spent a whole day on CHARIZARD because CHARIZARD is slot 1, carrying an
-- EEVEE L25 and a MAGIKARP L9 it could neither field nor train: the
-- Magikarp cannot reach 20 without being sent out, and nothing else
-- raises it. That is a missing verb, not a missing idea.
--
-- Decision-free like the rest: WHICH two slots, and whether to swap at
-- all, is entirely the model's. The op drives the menu the player would.
function OPS.party_swap(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  local party = (G.save or {}).party or {}
  local a = math.floor(tonumber(c.a) or 0)
  local b = math.floor(tonumber(c.b) or 0)
  if a < 1 or b < 1 or a > #party or b > #party then
    return false, ("party_swap needs a= and b=, party slots 1..%d")
      :format(#party)
  end
  if a == b then
    return false, "those are the same slot"
  end
  local an = tostring((party[a] or {}).species or "?")
  local bn = tostring((party[b] or {}).species or "?")
  U.tap(G, "start"); U.wait(8)
  local menu = ui_top(G)
  if not (menu and menu.screenId == "StartMenu") then
    ui_back_out(G); return false, "start menu never opened"
  end
  local row
  for i, it in ipairs(menu.items or {}) do
    local l = it.label or ""
    if l:find("POK") and l:find("MON") then row = i break end
  end
  if not row or not ui_cursor_to(G, "index", row) then
    ui_back_out(G); return false, "no POKeMON row"
  end
  U.tap(G, "a"); U.wait(10)
  local pm = ui_top(G)
  if not (pm and pm.screenId == "PartyMenu") then
    ui_back_out(G); return false, "party menu never opened"
  end
  ui_cursor_to(G, "index", a)
  U.tap(G, "a"); U.wait(8)
  -- SWITCH lives on the same PartyMenu-INTERNAL submenu the field moves
  -- use (subItems/subIndex, not a pushed screen) — see OPS.field_move,
  -- which lost an afternoon to reading the mon rows instead.
  local pm2 = G.stack:top()
  local subs = pm2 and pm2.subItems
  local srow, seen = nil, {}
  for i, it in ipairs(subs or {}) do
    local lab = ((it.label or it.text or it.action or "") .. ""):upper()
    seen[#seen + 1] = lab
    if lab:find("SWITCH", 1, true) then srow = i break end
  end
  if not srow then
    ui_back_out(G)
    return false, "SWITCH was not offered in the menu (it lists: "
      .. table.concat(seen, ", ") .. ")"
  end
  for _ = 1, 40 do
    if not pm2.subIndex or pm2.subIndex == srow then break end
    U.tap(G, pm2.subIndex > srow and "up" or "down"); U.wait(3)
  end
  U.tap(G, "a"); U.wait(8)
  -- now the list is waiting for the partner
  ui_cursor_to(G, "index", b)
  U.tap(G, "a"); U.wait(10)
  ui_back_out(G)
  -- VERIFY AGAINST THE PARTY, not against the menu. A cursor that did not
  -- land leaves the order untouched and every tap still "succeeds".
  local after = (G.save or {}).party or {}
  local moved = tostring((after[a] or {}).species or "?") == bn
                and tostring((after[b] or {}).species or "?") == an
  if not moved then
    return false, ("the order did not change — slot %d is still %s")
      :format(a, tostring((after[a] or {}).species or "?"))
  end
  return true, ("%s is now slot %d and %s is slot %d%s")
    :format(bn, a, an, b,
            (a == 1 or b == 1)
              and " — slot 1 is who gets sent out first" or "")
end

function OPS.daycare_deposit(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  local save = G.save or {}
  local dc = save.daycare
  if dc and dc.mon then
    return false, "the day care is already raising "
      .. tostring(dc.mon.species) .. " — it only takes one at a time, so "
      .. "collect that one first"
  end
  local party = save.party or {}
  local slot = math.floor(tonumber(c.slot) or 0)
  if slot < 1 or slot > #party then
    return false, ("no party slot %d — the party has %d")
      :format(slot, #party)
  end
  if #party < 2 then
    return false, "that is your only Pokemon and the day care will not "
      .. "leave you with none"
  end
  local giving = party[slot]
  local ok, why = daycare_talk(G, slot)
  if not ok then return false, why end
  local pm
  for _ = 1, 20 do
    pm = ui_top(G)
    if pm and pm.screenId == "PartyMenu" then break end
    U.tap(G, "a"); U.wait(6)
  end
  pm = ui_top(G)
  if not (pm and pm.screenId == "PartyMenu") then
    ui_back_out(G)
    return false, "the day care man never asked which Pokemon"
  end
  ui_cursor_to(G, "index", slot)
  U.tap(G, "a"); U.wait(10)
  for _ = 1, 30 do
    if G.stack:top() == G.overworld then break end
    U.tap(G, "a"); U.wait(5)
  end
  ui_back_out(G)
  local now = (G.save or {}).daycare
  if now and now.mon then
    return true, ("left %s L%s at the day care; it gains 1 exp per step "
      .. "you walk"):format(tostring(now.mon.species),
                            tostring(now.mon.level))
  end
  return false, "the hand-over did not go through; "
    .. tostring(giving and giving.species or "it") .. " is still with you"
end

function OPS.daycare_withdraw(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  local save = G.save or {}
  local dc = save.daycare
  if not (dc and dc.mon) then
    return false, "the day care is not holding anything"
  end
  local party = save.party or {}
  if #party >= 6 then
    return false, "the party is full (6) — there is nowhere to put "
      .. tostring(dc.mon.species) .. " until one is deposited in the PC"
  end
  local cost = 100 * math.max(1, (tonumber(dc.mon.level) or 0)
                                 - (tonumber(dc.depositLevel) or 0) + 1)
  local money = tonumber(save.money) or 0
  if money < cost then
    return false, ("taking %s back costs %d and you have %d")
      :format(tostring(dc.mon.species), cost, money)
  end
  local want = dc.mon.species
  local ok, why = daycare_talk(G)
  if not ok then return false, why end
  for _ = 1, 40 do
    if G.stack:top() == G.overworld then break end
    U.tap(G, "a"); U.wait(5)
  end
  ui_back_out(G)
  local now = (G.save or {}).daycare
  if not (now and now.mon) then
    return true, ("took %s back for %d"):format(tostring(want), cost)
  end
  return false, tostring(want) .. " is still at the day care"
end

-- Level-grind primitive: stand in this map's wild grass and pace until an
-- encounter interrupts (or the step budget runs out). The EXECUTOR fights
-- each battle with the subgoal's policy and re-sends this op — the same
-- battle-retry machinery as traversal — until the plan's done_when (a
-- level gate) holds. Decision-free: the model decides WHERE (which map)
-- and the plan decides UNTIL; walking into grass is mechanics.
function OPS.grind(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
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
  -- The confirm can be EATEN in the opening-text race, leaving the phase
  -- sitting in moveSelect — and the text loop below used to count that as
  -- a resolved turn. Against Misty that made three phantom EMBERs: three
  -- "turns" with no damage dealt or taken, so the lead met her second mon
  -- at half health. Retry the confirm; if the move still will not submit
  -- (also the disabled-move and no-PP shapes), fail the op honestly so the
  -- caller picks something else instead of burning a phantom turn.
  for _ = 1, 8 do
    local nb = in_battle(G)
    if not nb or nb.phase ~= "moveSelect" then break end
    U.tap(G, "a"); U.wait(4)
  end
  local still = in_battle(G)
  if still and still.phase == "moveSelect" then
    return false, "move would not submit (disabled or out of PP?)"
  end
  -- play out the turn's text back to the next decision or battle end
  for _ = 1, 120 do
    local nb = in_battle(G)
    if not nb then return true, "battle ended" end
    if nb.phase == "menu" then return true end
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
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  local ow = G.overworld
  local tx, ty = c.x, c.y
  local want_facing
  if c.name and not tx then
    for _, npc in ipairs(ow.npcs or {}) do
      if (npc.def or {}).name == c.name then tx, ty = npc.cellX, npc.cellY end
    end
    if not tx then
      for _, f in ipairs(map_fixtures(G, ((ow.map or {}).id))) do
        if f.name == c.name then
          tx, ty, want_facing = f.x, f.y, f.facing
        end
      end
    end
    if not tx then return false, "object '" .. c.name .. "' not visible" end
  elseif tx then
    -- an x,y press on a fixture that only answers from one side must
    -- approach from that side (the separator ignores a press from the
    -- east; only standing below it, facing up, runs it)
    for _, f in ipairs(map_fixtures(G, ((ow.map or {}).id))) do
      if f.x == tx and f.y == ty then want_facing = f.facing end
    end
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
  if want_facing then
    local keep = {}
    for _, a in ipairs(adj) do
      if a[3] == want_facing then keep[#keep + 1] = a end
    end
    if #keep > 0 then adj = keep end
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
  -- Advance the interaction's own text. If the thing asks a QUESTION (a
  -- yes/no choice box), answer per c.answer — "yes" confirms (the gen1
  -- cursor rests on YES), "no" declines — and with NO answer given,
  -- decline deterministically and SAY SO. Leaving the prompt for whoever
  -- touched the UI next meant the fossil take-prompt was confirmed by an
  -- A-mash in one world and cancelled by the B-dismisser in the next —
  -- and the declined fossil left the corridor east shut.
  -- READ WHAT IS BEING SAID. The page reader lives in the outer settle
  -- loop, so dialogue advanced here — which is most of what an interact
  -- ever produces — was consumed without a word of it being recorded. The
  -- run talked to the sleepy old man blocking the road and kept nothing.
  local function note_page()
    local t = G.stack:top()
    if t and t.pages and t.pageIndex then
      local pg = t.pages[t.pageIndex]
      if type(pg) == "table" then
        local txt = table.concat(pg, " ")
        note_text(txt)
      end
    end
  end
  -- BUDGET THE SPEECH IN PROGRESS, NOT IN TAPS. This was a flat 60
  -- iterations of tap-A-and-wait-4, and a page of text takes far longer than
  -- four frames to type: Bill's four-page speech measured FORTY-TWO
  -- iterations per page, so the loop ran out on page 3 and returned "dialog
  -- still open". The next op in the same macro then refused with "a box was
  -- up and would not close" -- and that macro was
  -- [talk to Bill, run the Cell Separation System], the only unlock for the
  -- Cerulean guard and so the only road south out of the city. One
  -- undersized constant walled a whole run for two days.
  -- Stop when the box stops CHANGING (top of stack and page both still for
  -- ~400 frames), with a generous ceiling behind it. Nothing about which
  -- button or which box is decided here; only how long to keep pressing.
  local SETTLE_TAPS, SETTLE_STALL = 600, 100
  local function settle_dialog()
    local stall, seen_top, seen_idx = 0, nil, nil
    for _i = 1, SETTLE_TAPS do
      local t = G.stack:top()
      dlg_trace(G, "settle", _i)
      if t == seen_top and (t and t.pageIndex) == seen_idx then
        stall = stall + 1
        if stall > SETTLE_STALL then return true, "dialog still open" end
      else
        stall, seen_top, seen_idx = 0, t, (t and t.pageIndex)
      end
      note_page()
      -- STOP AT A COUNTER'S OWN MENU. This loop taps A on anything that is
      -- not a yes/no box, and a shop's BUY/SELL/QUIT is a MENU -- so
      -- talking to a mart clerk A-mashed straight into it, picked BUY
      -- (whatever the cursor sat on), and dived into the buy list. By the
      -- time interact returned there was no menu left, and sell reported
      -- "shop menu never opened" after the clerk had plainly said "Hi
      -- there! May I help you?". Callers that intend to DRIVE a counter
      -- ask to be handed it instead.
      if c.stop_at_menu and ui_shop_up(G) then return true end
      -- WHICH POKEMON IS NOT THE HARNESS'S CHOICE. A party picker inside a
      -- dialog got A-pressed like any other screen, which selects whoever
      -- is in slot 1 -- and after collecting CHARIZARD that slot held
      -- MAGIKARP, so a stray yes at the DAY-CARE MAN handed over the wrong
      -- Pokemon entirely. Ops that name a slot (use_item, daycare_deposit)
      -- drive this menu themselves; a bare interact must not.
      -- WHICH FLOOR IS NOT THE HARNESS'S CHOICE EITHER. The elevator
      -- panel opens a ListMenu ("WHICH FLOOR?", built from the floors
      -- whose warps reach this car); A-mashing it rides to whatever the
      -- cursor sat on. Same rule as the party picker: an op that has
      -- chosen says so, a bare interact backs out.
      if t and t.items and t.title and tostring(t.title):upper():find("FLOOR")
         and not c.floor then
        U.tap(G, "b"); U.wait(6)
        for _ = 1, 20 do
          if G.stack:top() == ow then break end
          U.tap(G, "b"); U.wait(4)
        end
        local names = {}
        for _, it in ipairs(t.items or {}) do
          names[#names + 1] = tostring(it.label or "?")
        end
        return true, "the elevator asked WHICH FLOOR and nothing here had "
          .. "chosen one — backed out. Floors it offered: "
          .. table.concat(names, ", ")
          .. ". Use {\"op\":\"elevator\",\"floor\":\"<one of those>\"}."
      end
      if t and t.screenId == "PartyMenu" and not c.slot then
        U.tap(G, "b"); U.wait(6)
        for _ = 1, 20 do
          if G.stack:top() == ow then break end
          U.tap(G, "b"); U.wait(4)
        end
        return true, "it asked WHICH POKEMON, and nothing here had chosen "
          .. "one — backed out. Use an op that names the slot (for the day "
          .. "care that is daycare_deposit with slot=N)."
      end
      if t == ow then return true end
      if t and (t.enemy or t.kind) then return true, "battle started" end
      if ui_is_choice(G) then
        -- who is being asked: the named target, else the tile pressed
        local who = c.name or (c.x and ("%s,%s"):format(tostring(c.x),
                                                        tostring(c.y)))
                    or "?"
        -- KEYED ON THE QUESTION, NOT THE QUESTIONER. Keying on who asked
        -- meant one read licensed every later blind "yes" to that NPC --
        -- and the DAY-CARE MAN asks two opposite questions depending on
        -- whether he is holding anything: "shall I raise one?" when empty,
        -- "do you want him back?" when full. Having read the second, the
        -- run answered yes to the first and handed over its MAGIKARP while
        -- trying to collect its CHARIZARD.
        local qkey = who .. "|" .. tostring(recent_text or "?")
        if c.answer ~= nil and not seen_question[qkey] and not c.read_question
        then
          -- LEAVE IT OPEN. Neither pressing A nor pressing B here is the
          -- model's judgement: `answer` arrived as boilerplate on 302 of
          -- 560 interacts (signposts included), and declining is just as
          -- much an answer as accepting. Stop with the box on screen and
          -- the words in recent_text; the executor puts the question to
          -- the model and presses whatever comes back.
          seen_question[qkey] = recent_text or true
          return true, ("%s is ASKING something and the box is STILL OPEN"
            ):format(who)
            .. ((recent_text and (" — \"" .. recent_text .. "\"")) or "")
            .. (". answer=\"" .. tostring(c.answer) .. "\" was not used, "
                .. "because it was set before the question could be read.")
        end
        if c.answer == "yes" then
          U.tap(G, "a"); U.wait(6)
        elseif c.answer ~= nil then
          U.tap(G, "b"); U.wait(6)
        else
          -- QUOTE THE QUESTION. Saying only that one was asked left the
          -- model inferring what it had declined from whatever it touched,
          -- and recent_text is cleared on return to free roam so the words
          -- were gone by the next observation too. The text is on screen;
          -- an honest choice needs to know what is being chosen.
          -- Same again with no answer supplied: the old code declined
          -- deterministically, which lost the Dome Fossil prompt in one
          -- world. Hold the box; the question gets asked properly.
          local asked = recent_text
          seen_question[who .. "|" .. tostring(asked or "?")] = asked or true
          return true, ("%s is ASKING something and the box is STILL OPEN"
            ):format(who)
            .. ((asked and (" — \"" .. asked .. "\"")) or "")
            .. ". No answer was supplied with the interact."
        end
      else
        U.tap(G, "a"); U.wait(4)
      end
    end
    return true, "dialog still open"
  end
  -- retry across ambient-dialog interruptions (e.g. the lab rival's timed
  -- "fed up with waiting"): clear any text box, then approach and press.
  for _ = 1, 4 do
    for _ = 1, 12 do          -- clear any pending text
      if G.stack:top() == ow then break end
      U.tap(G, "a"); U.wait(3)
    end
    if G.stack:top() ~= ow then return false, "stuck in a menu/dialog" end
    if press_from_adjacent() then return settle_dialog() end
    for _, a in ipairs(adj) do
      OPS.walk_to(G, { x = a[1], y = a[2], max_steps = 60 })
      if G.stack:top() == ow and p.cellX == a[1] and p.cellY == a[2] then
        break
      end
    end
    if press_from_adjacent() then return settle_dialog() end
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
-- Re-teach the names this world already learned. Region identity is the
-- one thing that must survive a restart: the run walked out of the
-- trashed house once and learned that the far side is a different place,
-- and without this it forgets that every time the executor relaunches and
-- has to walk it again to find out. The executor hands back the anchors it
-- stored; the component walk in observe spreads each one over its ground.
function OPS.seed_regions(G, c)
  local n = 0
  for mid, cells in pairs(c.regions or {}) do
    local known = region_of[mid]
    if not known then known = {}; region_of[mid] = known end
    for cell, name in pairs(cells) do
      if known[cell] == nil then known[cell] = name; n = n + 1 end
    end
  end
  return true, ("seeded %d remembered region cell(s)"):format(n)
end

function OPS.map_probe(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
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
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
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
        if type(pg) == "table" then
          note_text(table.concat(pg, " "))
        end
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
    -- NEVER SIT IN THE CABLE CLUB LINK SCREENS. Two reasons, and they
    -- point the same way. Practically, a link session needs a SECOND
    -- PLAYER: there is none, so every one of these screens can only stall
    -- the run (the Cable Club save prompt already held a campaign for 23
    -- escalations). And they PUT AN ADDRESS ON SCREEN -- the joiner's
    -- entry field comes prefilled with this machine's own LAN IP, and a
    -- host shows "ip:port" for the friend to type. It is a private-range
    -- address and online play uses a relay room code rather than a public
    -- one, so nothing routable is exposed, but it is still this machine's
    -- address sitting in frame, and this run is meant to be streamed.
    -- Backing out costs the model nothing it can use: talking to the
    -- LINK_RECEPTIONIST still works, her words still reach the ledger,
    -- and saying yes is still hers to choose -- the session just never
    -- opens behind it.
    do
      local LINK_STAGES = {
        menu = true, lanMenu = true, onlineMenu = true, addrEntry = true,
        hosting = true, onlineJoining = true, joining = true,
        notice = true, battleOptions = true,
      }
      for _ = 1, 12 do
        local t = G.stack and G.stack:top()
        if not (t and t.stage and LINK_STAGES[t.stage]) then break end
        U.tap(G, "b"); U.wait(6)
      end
    end
    -- ONE PLACE, BECAUSE THERE ARE SEVEN OPS. buy, sell, use_item, toss,
    -- pc_item, battle_item and catch all take an item name straight from
    -- the model and all did their own exact-string lookup against it —
    -- seven copies of the same comparison, which is seven chances for the
    -- next one written to forget. Canonicalise where the command arrives
    -- and every op downstream is holding an id the game recognises.
    cmd.item = canon_item(G, cmd.item)
    cmd.ball = canon_item(G, cmd.ball)
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
