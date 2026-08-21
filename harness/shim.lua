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
-- A FADE IS NOT A BOX. Every map change pushes src/render/Transition — a
-- fade with `phase`/`t`/`frames` and none of a screen's other marks — and
-- it ends on its own after a few frames. Pressing B at one does nothing,
-- so "a box was up and would not close" was the wrong sentence for it:
-- after a lift ride the next op met the tail of the fade, reported a
-- stuck box, and the model spent a round tapping B at a screen nobody
-- could have closed. Wait for it instead; that is all it ever needed.
local function _is_fade(t)
  return t ~= nil and t.phase ~= nil and t.frames ~= nil
     and t.map == nil and t.items == nil
end
local function need_overworld(G)
  if G.overworld and G.stack:top() == G.overworld then return true end
  for _ = 1, 60 do
    if not _is_fade(G.stack and G.stack:top()) then break end
    coroutine.yield()
  end
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
          -- ...AND WHEN THE GROUND CARRIES TWO NAMES, COUNT IT. A merge --
          -- the fossil taken off the corridor it blocked, a boulder
          -- pushed, a tree cut -- leaves two minted names painted over one
          -- component, and `pairs` handed back whichever the hash reached
          -- first. So Mt Moon 1F answered to 2,2 on one arrival and 3,2 on
          -- the next; the frontier walk then aimed at 2,2, a name the
          -- world had stopped minting, and reported "the walk did not
          -- arrive" standing in the very room it asked for. The name most
          -- of the reachable ground already carries is the one this place
          -- answers to; ties go to the topmost-then-leftmost cell, the
          -- same rule a fresh mint uses.
          local votes = {}
          for k in pairs(rreach) do
            local v = known[k]
            if v then votes[v] = (votes[v] or 0) + 1 end
          end
          local bn, byy, bxx
          for v, n in pairs(votes) do
            local vx, vy = v:match("^(-?%d+),(-?%d+)$")
            vx, vy = tonumber(vx) or 0, tonumber(vy) or 0
            if not bn or n > bn
               or (n == bn and (vy < byy or (vy == byy and vx < bxx))) then
              bn, byy, bxx, name = n, vy, vx, v
            end
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
      -- WHAT IT LOOKS LIKE IS ON THE SCREEN. Every way out was reported
      -- as "door (x,y)" whatever it was drawn as, so a stairwell, a
      -- ladder, a fall-through hole and Silph's teleport PADS all read
      -- alike — while a player tells them apart at a glance, and a floor
      -- littered with pads is a different problem from a floor with one
      -- staircase. The engine already names them from the tile under the
      -- cell, the same way pokered does: isDoorTileCell (a door),
      -- warpPadOrHoleAt ("pad"/"hole", IsPlayerStandingOnWarpPadOrHole),
      -- and a warp tile that is neither is the stair/ladder case its own
      -- comment names. Says nothing about where any of them GOES.
      local lm = G.overworld and G.overworld.map
      -- WHAT IS DRAWN ON A WARP TILE, SETTLED BY LOOKING AT IT.
      -- data/tilesets/door_tile_ids.asm is the list of tiles that get the
      -- opening-door ANIMATION, not the list of tiles drawn as a door, so
      -- every other warp tile fell through to a catch-all that called it
      -- "stairs" — and the ledger offered the six S.S. Anne cabin doorways
      -- and the kitchen door as "stairs/ladder", six fake staircases
      -- drowning the one real staircase on that deck (user, at the
      -- screen: "staircases? there should be three; the rest are all
      -- doors").
      --
      -- Every tileset:tile pair that reached that catch-all — 55 of them —
      -- was rendered from assets/generated/tilesets/*.png in a map that
      -- uses it. FIFTEEN are staircases or ladders. All the rest are
      -- doorways, exit mats and cave mouths: the exit mat of every house,
      -- Center, Mart and gym, the gate doorways, the cabin doors, the
      -- Vermilion pier. So the catch-all is a DOOR and the stairs are the
      -- list, which is the way round the game actually is.
      local STAIR_TILES = {
        CAVERN       = { [24] = true, [26] = true },   -- cave ladders
        CEMETERY     = { [19] = true, [27] = true },   -- Pokemon Tower
        DOJO         = { [74] = true },                -- Lance's room
        FACILITY     = { [19] = true },
        GATE         = { [26] = true, [28] = true },
        MUSEUM       = { [26] = true, [28] = true },
        REDS_HOUSE_1 = { [28] = true },
        REDS_HOUSE_2 = { [26] = true },
        SHIP         = { [55] = true, [57] = true },   -- NOT 74 or 52,
                                                       -- which are cabin
                                                       -- doorways
        UNDERGROUND  = { [19] = true },
      }
      local function warp_look(x, y)
        if lm and lm.isDoorTileCell and lm:isDoorTileCell(x, y) then
          return "door"
        end
        if lm and lm.warpPadOrHoleAt then
          local k = lm:warpPadOrHoleAt(x, y)
          if k then return tostring(k) end     -- "pad" | "hole"
        end
        -- A LANDING IS NOT A WAY OUT. Some warp entries sit on plain floor:
        -- they are where something else PUTS you, not something you can
        -- take. SILPH_CO_1F 16,10 is the ROM's landing for 3F's pad — tile
        -- 1, no pad and no door drawn on it — and standing on it does
        -- nothing, which is exactly what the run kept reporting ("stepped
        -- through but no warp fired") while the ledger offered it as the
        -- floor's one untried exit. The map's OUTER EDGE is the exception:
        -- a town door at the bottom row is not a warp tile either and does
        -- work, because you step off the map there.
        local edge = (x <= 0 or y <= 0
                      or (lm and lm.widthCells and x >= lm.widthCells - 1)
                      or (lm and lm.heightCells and y >= lm.heightCells - 1))
        if not edge and lm and lm.isWarpTileCell
           and not lm:isWarpTileCell(x, y) then
          -- ...BUT MOST OF THEM ARE NOT LANDINGS AT ALL. The rule above was
          -- written from ONE example (SILPH_CO_1F 16,10, tile 1, floor on
          -- all four sides) and it hid 60 real ways out of this game: every
          -- route gate, all three Rocket Hideout lift doors, the S.S. Anne
          -- cabin doors and its bow, and both cells of the VERMILION dock
          -- -- so the run stood in Vermilion 56 times with the S.S. TICKET
          -- in the bag reading "FULLY WORKED: nothing here is untried",
          -- and went hunting the gym door behind a CUT tree instead.
          -- src/world/Warp.lua's own comment names them: "the player
          -- stands on a warp cell and the extra check passes -- route-gate
          -- doorways, the Vermilion dock entrance". So ask the engine's
          -- rule rather than guessing from the tile: if standing here and
          -- pressing on WOULD fire it, it is a way through. What is left
          -- after that -- 7 of 67 -- are the real landings.
          local okw, WarpM = pcall(require, "src.world.Warp")
          local carpets = G.data and G.data.field
                          and G.data.field.warpCarpets
          if okw and WarpM and WarpM.extraCheck then
            for _, dn in ipairs({ "down", "up", "left", "right" }) do
              local okc, fires = pcall(WarpM.extraCheck, lm, carpets,
                                       x, y, dn)
              if okc and fires then return "door" end
            end
          end
          return "landing"
        end
        local _st = STAIR_TILES[md and md.tileset]
        if _st and lm and lm.cellTile and _st[lm:cellTile(x, y)] then
          return "stairs"
        end
        return "door"
      end
      -- ...AND A LANDING IS NOT SHOWN AT ALL. It is drawn as ordinary
      -- floor (user, looking at it: "it looks like an ordinary block not a
      -- warp"), so a player standing on that tile sees nothing to take —
      -- and listing it is both misleading and a peek at the warp table
      -- nobody could have read off the screen. SILPH_CO_1F 16,10 is the
      -- landing for 3F's pad; offered as this floor's one untried exit it
      -- drew the run back round after round, each time reporting "stepped
      -- through but no warp fired". Arrivals still work; you simply are
      -- not told there is a door where there is no door.
      local _n = 0
      for _, w in ipairs(md.warps) do
        local _look = warp_look(w.x, w.y)
        if _look ~= "landing" then
          local dest = w.destMap
          if dest == "LAST_MAP" and lastOut then dest = lastOut end
          _n = _n + 1
          o.map.warps[_n] = { x = w.x, y = w.y, dest = dest,
                              look = _look,
                              reachable = reach[w.x .. "," .. w.y] and true
                                          or false }
        end
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
    -- an ARROW TILE is not a stand: you arrive and are slid away, and
    -- walk_to will not end on one — so a thing whose only neighbours are
    -- arrows is not reachable however full the fill looks (B2F's item at
    -- 3,21 read reachable and every walk answered "no path")
    local _spin = {}
    for _, e in ipairs((G.data and G.data.field and G.data.field.spinners
                        and G.data.field.spinners[map.id]) or {}) do
      _spin[e.x .. "," .. e.y] = true
    end
    -- ...AND NEITHER IS A WARP TILE. The arrow-tile rule above is exactly
    -- the pad's rule too: you arrive and are taken somewhere else, so it
    -- is not a spot to stand and press from — and warp_block already
    -- forbids a walk from ever ROUTING over one. Silph's floors are laid
    -- out around teleport pads, and an item whose only neighbours are pads
    -- read "reachable" while every walk to it answered no path. Same
    -- disagreement 9f8e5e9 settled for doors, one level over: what the
    -- observation calls reachable must be what a walk can actually do.
    local _warp = {}
    for _, w in ipairs((md and md.warps) or {}) do
      _warp[w.x .. "," .. w.y] = true
    end
    -- WHY IT CANNOT BE WALKED TO, when the answer is on the tile next to
    -- it. "not walkable-to right now" reads as impossible; "there is a pad
    -- beside it" reads as a way in you have not used. Silph's 5F items sit
    -- past teleport pads, and a pad is a thing you USE, not a wall (user:
    -- "the item on floor five should read as reachable just with that
    -- teleport in the way"). Says what is on the tile, never how to use it.
    local function why_far(x, y)
      local lm2 = G.overworld and G.overworld.map
      if not (lm2 and lm2.warpPadOrHoleAt) then return nil end
      for _, d in ipairs({ {0, 1}, {0, -1}, {1, 0}, {-1, 0} }) do
        local k = lm2:warpPadOrHoleAt(x + d[1], y + d[2])
        if k == "pad" then
          return ("a WARP PAD at %d,%d is beside it — a walk cannot cross "
                  .. "one, but a pad is a thing you step on, not a wall")
                 :format(x + d[1], y + d[2])
        elseif k == "hole" then
          -- A HOLE IS NOT A PAD. You drop through it to the floor below
          -- and there is no going back up the way you came, so a hole
          -- beside a thing is not a way IN to that thing the way a pad
          -- can be (user: "the hole is one-way down, but the warppad is
          -- both ways").
          return ("a HOLE at %d,%d is beside it — a hole is a way DOWN "
                  .. "only: you drop to the floor below and cannot climb "
                  .. "back up it"):format(x + d[1], y + d[2])
        end
      end
      return nil
    end
    -- ...EXCEPT THE TILE YOU ARE ON. Excluding pads as stands is right for
    -- ROUTING — a walk cannot cross one — but it was applied to the cell
    -- the party is standing on too, so arriving by pad and standing right
    -- beside a thing reported "not walkable-to right now" about something
    -- within arm's reach (user, watching 5F: "literally happened to end up
    -- right next to it the right way and didnt pick it up"). Where you
    -- already are is always somewhere you can act from.
    local _here_k = (p and p.cellX and (p.cellX .. "," .. p.cellY)) or nil
    local function stand_ok(k)
      if _here_k and k == _here_k then return true end
      return objreach[k] and not _spin[k] and not _warp[k]
    end
    local function adjacent_reachable(x, y, over_counter)
      if stand_ok((x - 1) .. "," .. y) or stand_ok((x + 1) .. "," .. y)
         or stand_ok(x .. "," .. (y - 1)) or stand_ok(x .. "," .. (y + 1))
      then return true end
      -- the distance-2 stand exists for talking ACROSS A COUNTER, which
      -- only PEOPLE do (the nurse, the clerk). Applying it to fixtures
      -- called a slot machine boxed in by its neighbours "reachable" —
      -- the tile between is another machine, and the engine only reads
      -- the tile the player faces.
      if over_counter == false then return false end
      -- ...AND THE TILE BETWEEN MUST BE A COUNTER. This reach exists for
      -- one reason — gen 1 talks ACROSS a counter — but it only ever
      -- checked that nobody was standing in the middle, so ANY gap of one
      -- cell qualified: a wall, a desk, or Silph's card-key shutters. Then
      -- an item locked behind a shutter read "reachable" and every walk to
      -- it answered no path. The engine names counter tiles itself
      -- (Map:isCounterCell, the same test that lets you talk to a mart
      -- clerk), so ask it rather than assuming the gap is friendly.
      local over = { { x, y + 2, x, y + 1 }, { x, y - 2, x, y - 1 },
                     { x - 2, y, x - 1, y }, { x + 2, y, x + 1, y } }
      for _, o in ipairs(over) do
        local mid_ok = true
        if map and map.isCounterCell then
          mid_ok = map:isCounterCell(o[3], o[4])
        end
        if stand_ok(o[1] .. "," .. o[2]) and mid_ok
           and not occupied_cell(o[3], o[4]) then
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
        -- WHAT IS IN THE BALL IS NOT ON THE SCREEN. The map data names an
        -- item object by its contents (ROUTE2_HP_UP, OAKSLAB_CHARMANDER_
        -- POKE_BALL) and that name reached every prompt, ledger and plan
        -- since objects were first listed — the ROM telling the model what
        -- is inside a ball it has only seen from the outside. A player sees
        -- a Poke Ball on the ground at a spot; that is all the harness may
        -- say. Named by position (items do not move); the real name still
        -- resolves in interact so distilled macros keep replaying, but it
        -- is never emitted (user, 2026-08-18: "only 'item at x,y'").
        name = ("ITEM_%d_%d"):format(npc.cellX or 0, npc.cellY or 0)
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
        why = (not adjacent_reachable(npc.cellX, npc.cellY))
              and why_far(npc.cellX, npc.cellY) or nil,
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
      -- A VENDING MACHINE IS A MACHINE, NOT A NOTICE BOARD. It rides in
      -- md.signs because that is how the ROM stores it, but pressing it
      -- opens a purchase list and hands over an item, which is the whole
      -- of what a fixture is here. Filed as a sign, it sorted with the
      -- floor plaques: on the Celadon roof, with the subgoal has_item
      -- FRESH_WATER, an NPC outranked three untouched drink machines.
      -- The name is the game's own label, already printed to the model.
      -- ...AND AN ELEVATOR PANEL, for the same reason: pressing it opens
      -- the floor list and rides. Filed as a sign it went "pressed" once
      -- and the car then read FULLY WORKED, so the one message naming the
      -- floors and the op scrolled away and Silph's car was entered and
      -- left 31 times.
      local kind = (nm:find("VENDING_MACHINE") or nm:find("ELEVATOR"))
                   and "fixture" or "sign"
      o.map.objects[#o.map.objects + 1] = {
        x = sg.x, y = sg.y, kind = kind, name = nm,
        reachable = adjacent_reachable(sg.x, sg.y, false),
      }
    end
    -- The comment above promised Bill's separator; md.signs never
    -- contained it (it is a hidden_event, not a sign). These are the
    -- machines the player can SEE — see map_fixtures.
    for _, f in ipairs(map_fixtures(G, map.id)) do
      o.map.objects[#o.map.objects + 1] = {
        x = f.x, y = f.y, kind = "fixture", name = f.name,
        reachable = adjacent_reachable(f.x, f.y, false),
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
                reachable = adjacent_reachable(cx, cy, false),
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
    -- THE GHOST IS A GHOST. Without the SILPH SCOPE the Pokemon Tower's
    -- foe is drawn and named "GHOST" on screen (BattleState:makeGhost); the
    -- battle table still holds the real species, and side() read it -- so
    -- the observation called it MAROWAK L30 to a player who could not
    -- have known. Name it as the screen does and hide what the screen
    -- hides. o.battle.ghost (a scalar on the state) rides along as-is.
    if top.ghost and o.battle.foe then
      local f = o.battle.foe
      f.species, f.types, f.moves, f.stats, f.boosts = "GHOST", nil, {}, nil, nil
    end
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
    -- ...but a move list is not a yes/no: the level-up MoveLearnMenu in
    -- its selecting state has a cursor and no items table, and read as a
    -- question — an A pressed as "yes" would forget whatever the cursor
    -- sat on. It is a list; the executor puts it to the model as one.
    if top.screenId == "MoveLearnMenu" and top.selecting then
      o.ui.is_choice = false
    end
    -- WHICH MOVE TO FORGET IS THE MODEL'S CHOICE, and it needs the list.
    -- A level-up MoveLearnMenu in its selecting state (the yes was given)
    -- shows four moves and CANCEL; scalars() drops top.mon, so say who is
    -- learning, what, and what it knows, by name.
    if top.screenId == "MoveLearnMenu" and top.mon then
      local mv = {}
      for i, m in ipairs(top.mon.moves or {}) do
        mv[i] = tostring(type(m) == "table" and m.id or m)
      end
      o.ui.learner = tostring(top.mon.species)
      o.ui.learner_slot = nil
      for i, m in ipairs((G.save and G.save.party) or {}) do
        if m == top.mon then o.ui.learner_slot = i end
      end
      o.ui.new_move = tostring(top.newMoveId)
      o.ui.moves = mv
      -- (top.selecting / top.index ride along from scalars())
    end
  else
    o.mode = "boot"
  end
  -- THE SAFARI GAME IS A CLOCK AND A BALL COUNT, and neither was in the
  -- observation: the run paid its 500, walked in, and had no way to know
  -- it was on a 500-step timer with 30 SAFARI BALLs — both of which the
  -- game shows on screen the moment either is asked about. Ends by itself
  -- when the steps run out or you leave.
  do
    local sf = (G.save or {}).safari
    if sf then
      o.safari = { balls = sf.balls, steps = sf.steps }
    end
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
  -- ...AND WHAT IT IS HOLDING THAT IS ALIVE (user, 2026-08-17). Without
  -- it every deposit is a one-way door: a Pokemon put away stops existing
  -- as far as the run is concerned, so "the party holds a WATER type"
  -- cannot be answered by the WATER type already in storage, and a full
  -- party has no visible way to make room for the one it just walked to.
  --
  -- THIS IS RECALL, NOT READING AHEAD, and the difference is the whole
  -- rule. I flagged it as borderline alongside enter_shop; the user's
  -- ruling was that perfect recall is an advantage a bot need not be
  -- hobbled out of, and on inspection it is not even close to the line.
  -- EVERY mon in a box got there by being caught or deposited, both of
  -- which the run did and was told about ("...was sent to BILL'S PC!").
  -- Nothing here is state the run has never looked at. enter_shop is
  -- genuinely different: it reads the objects of a map nobody has entered
  -- and decides where the body goes. Remembering what you did is free.
  -- Knowing what is behind a door you have not opened is not.
  --
  -- Species and level only, which is exactly what a box row prints. No
  -- moves, no stats: those need the summary screen opened on that mon,
  -- and the model can open it.
  -- `index` is the row number WITHIN its box, which is what pc_withdraw
  -- and pc_release address. Listing them without it would be describing a
  -- shelf with no way to point at anything on it.
  o.pc_mons = {}
  local _boxes = (G.save and G.save.boxes) or {}
  for bi = 1, 12 do
    for mi, m in ipairs(_boxes[bi] or {}) do
      o.pc_mons[#o.pc_mons + 1] = {
        species = m.species, level = m.level, box = bi, index = mi }
    end
  end
  o.pc_box = (G.save and G.save.currentBox) or 1
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
-- SCRIPT TILES, LEARNED BY STEPPING ON THEM. A map's coordinate events
-- (the Pokemon Tower ghost at 6F (10,16), the badge guards, the rival
-- ambushes) are Lua onStep functions in the engine, not data the shim can
-- read -- so the pathfinder walked over them as plain floor. The ghost's
-- script pushes you one step off its tile after a flee, and the next
-- BFS toward anything whose shortest path crossed (10,16) stepped straight
-- back on: "Be gone... Intruders..." twelve times a second, on a walk that
-- was trying to LEAVE. Remember, per map, every cell whose step put a text
-- box up (a battle alone is a wild encounter, not a script), and route
-- around such cells when any other way exists. Only when a script tile is
-- the only way -- or the destination itself -- is it stepped on, and then
-- the model is told what came up. In-process memory: relearned once per
-- game start, which costs one firing.
local TRIGGERS = {}
local function trigger_cells(G)
  local mid = G.overworld and G.overworld.map and G.overworld.map.id
  if not mid then return {} end
  TRIGGERS[mid] = TRIGGERS[mid] or {}
  return TRIGGERS[mid]
end
local function is_warp_cell(md, x, y)
  for _, w in ipairs((md and md.warps) or {}) do
    if w.x == x and w.y == y then return true end
  end
  return false
end

local function walk(G, dir, steps)
  local ow = G.overworld
  for step = 1, steps do
    local p = ow.player
    if p.facing ~= dir then
      U.tap(G, dir)            -- gen1 tap-to-face
      U.wait(4)
    end
    local sx, sy = p.cellX, p.cellY
    local map_before = ow.map and ow.map.id
    local moved = false
    for _ = 1, 60 do
      table.insert(G.input.pressQueue, dir)
      G.input.state[dir] = true
      coroutine.yield()
      if p.cellX ~= sx or p.cellY ~= sy then moved = true break end
    end
    -- ON A SLOPE THE RELEASE IS THE COST. Route 17 moves you one cell
    -- SOUTH on any idle poll while on the bike, so the four settle frames
    -- between steps give the road a free push back: a northward walk_to
    -- lost a cell for every cell it made and read as "no path". Hold the
    -- direction across the settle when the slope is against us.
    local _slope = false
    for _, mm in ipairs(((G.data and G.data.field
                          and G.data.field.forcedMovement) or {}).slopeMaps
                        or {}) do
      if mm == (ow.map and ow.map.id) then _slope = true end
    end
    if _slope and dir == "up" and (G.save or {}).onBike then
      U.wait(4)                -- settle with the direction still held
      G.input.state[dir] = false
    else
      G.input.state[dir] = false
      U.wait(4)                -- settle into the cell
    end
    if moved and ow.map and ow.map.id == map_before then
      local top = G.stack:top()
      if top and top ~= ow and not (top.enemy or top.kind)
         and not is_warp_cell(ow.map.def, p.cellX, p.cellY) then
        local t = trigger_cells(G)
        local k = p.cellX .. "," .. p.cellY
        t[k] = (t[k] or 0) + 1
      end
    end
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

-- A BUSH IS TERRAIN, NOT AN OBJECT, so the "who is standing where you
-- would have to stand" reports never saw one: a CUT_TREE across the only
-- approach to an item read as a bare "no reachable tile adjacent to
-- target" and the run pressed at it again and again with CUT in the bag
-- and taught. Same tile test cross() uses for its seam report.
-- A SHUTTERED DOOR IS DRAWN ON THE SCREEN. Silph's floors are divided by
-- card-key shutters (field.cardKeyDoors: doorTiles 24/36, and 11F's own
-- tile 94), and a walk treats one as plain wall — so every report said
-- "no path" and named nothing, while a player sees a closed door. Naming
-- it says only what is on screen; what opens it is nobody's business here.
local function shut_door_at(G, x, y)
  local lm = G.overworld and G.overworld.map
  local ck = G.data and G.data.field and G.data.field.cardKeyDoors
  if not (lm and ck and lm.cellTile) then return false end
  local onList = false
  for _, m in ipairs(ck.maps or {}) do
    if m == lm.id then onList = true break end
  end
  if not onList then return false end
  local t = lm:cellTile(x, y)
  if lm.id == "SILPH_CO_11F" then
    return ck.silphCo11F and t == ck.silphCo11F.doorTile
  end
  for _, dt in ipairs(ck.doorTiles or {}) do
    if t == dt then return true end
  end
  return false
end

-- A PAD IS A BLOCKER TOO, AND A DIFFERENT KIND. Silph's floors are cut up
-- by teleport pads, and a walk will not cross one — correctly: stepping on
-- it takes you somewhere. So the ground beyond a pad reads "unreachable"
-- with nothing said, and that reads as impossible rather than as not-on-
-- foot (user, watching 5F: "it sees from its perspective that its
-- unreachable because the only way is one tile wide and crosses over a
-- pad which bfs wont walk over, but it is reachable"). Say what is there.
-- What to DO about a pad stays the model's: this names the tile, not a
-- route through it.
local function pad_at(G, x, y)
  local lm = G.overworld and G.overworld.map
  if not (lm and lm.warpPadOrHoleAt) then return nil end
  return lm:warpPadOrHoleAt(x, y)          -- "pad" | "hole" | nil
end

local function cut_bush_at(G, x, y)
  local lm = G.overworld and G.overworld.map
  local ts = lm and lm.def and lm.def.tileset
  local want = (ts == "OVERWORLD" and 0x3d) or (ts == "GYM" and 0x50) or nil
  if not (lm and want and lm.cellTile) then return false end
  return lm:cellTile(x, y) == want and not lm:isWalkableCell(x, y)
end
-- ...AND A BUSH IN THE MIDDLE OF THE WAY, not just against the target.
-- Route 12's ITEM_5_89 sits past a CUT_TREE that is nowhere near the item
-- itself, so naming only the four approach tiles still said nothing. Walk
-- the map for bushes that touch ground you CAN reach -- those are the ones
-- standing between you and everything behind them -- and name the few
-- closest to what you were reaching for. Which to cut, or whether to go
-- round, stays the model's.
local function bushes_blocking(G, tx, ty, reach)
  local out = {}
  local lm = G.overworld and G.overworld.map
  local W, H = (lm and lm.widthCells) or 0, (lm and lm.heightCells) or 0
  for cy = 0, math.min(H - 1, 127) do
    for cx = 0, math.min(W - 1, 127) do
      if cut_bush_at(G, cx, cy) or shut_door_at(G, cx, cy)
         or pad_at(G, cx, cy) then
        local touches = false
        for _, d in ipairs({ {0, 1}, {0, -1}, {1, 0}, {-1, 0} }) do
          if reach[(cx + d[1]) .. "," .. (cy + d[2])] then touches = true end
        end
        if touches then
          out[#out + 1] = { x = cx, y = cy,
                            d = math.abs(cx - tx) + math.abs(cy - ty) }
        end
      end
    end
  end
  table.sort(out, function(a, b) return a.d < b.d end)
  local txt = {}
  for i = 1, math.min(#out, 3) do
    local _k = pad_at(G, out[i].x, out[i].y)
    txt[i] = (_k == "pad"
                and ("a WARP PAD at (%d,%d) — a walk will not cross one, "
                     .. "stepping on it takes you somewhere")
              or _k == "hole"
                and ("a HOLE at (%d,%d) — a way DOWN only: you drop to the "
                     .. "floor below and cannot come back up it")
              or shut_door_at(G, out[i].x, out[i].y)
                and ("a CLOSED DOOR at (%d,%d)")
              or ("CUT_TREE (a bush CUT clears) at (%d,%d)"))
      :format(out[i].x, out[i].y)
  end
  return txt
end


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
  -- A DOOR IS AN ENDPOINT, NOT A CORRIDOR. warp_block already says a walk
  -- may never pass THROUGH a warp tile — it fires on the step — but this
  -- fill walked straight over them, so `reachable` was computed along
  -- routes no walk can take. Route 7's east side is eight cells and the
  -- gate doors at 11,9/11,10 are on the far side of the building, yet the
  -- ledger offered them as plain available doors and use_warp answered
  -- "no path" every time. A warp cell stays REACHABLE (you can step onto
  -- it) and is not expanded FROM. Only for the warp-reachability fill:
  -- region identity (no_ledges) keeps its own shape, since re-minting
  -- every region id mid-run would orphan the whole walked graph.
  local THROUGH = nil
  if not no_ledges then
    THROUGH = {}
    for _, w in ipairs((ow.map.def and ow.map.def.warps) or {}) do
      THROUGH[key(w.x, w.y)] = true
    end
    -- ...BUT NOT THE ONE YOU ARE STANDING ON. "A door is an endpoint, not
    -- a corridor" is about routing THROUGH a warp; the cell under your own
    -- feet is where you already are, and you can step off it in any
    -- direction. Applied to the origin it collapsed the whole fill to a
    -- single tile whenever the party stood on a pad — so on Silph's pads
    -- everything in the room read "not walkable-to right now" and the
    -- region fingerprint was minted from one cell (user: "it was on the
    -- pad, which i think has been conflated with the main area").
    THROUGH[key(p.cellX, p.cellY)] = nil
  end
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
            if not (THROUGH and THROUGH[key(nx, ny)]) then
              q[#q + 1] = { x = nx, y = ny }
            end
          end
        elseif not no_ledges then
          local lx, ly = ledge_landing(G, ow.map, cur.x, cur.y, dn)
          if lx and not seen[key(lx, ly)] then
            seen[key(lx, ly)] = true
            if not (THROUGH and THROUGH[key(lx, ly)]) then
              q[#q + 1] = { x = lx, y = ly }
            end
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

local function bfs_dir_pass(G, tx, ty, wblock)
  local Collision = require("src.world.Collision")
  local ow = G.overworld
  local p = ow.player
  local key = function(x, y) return x .. "," .. y end
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
  -- WHY THERE IS NO PATH, in the same words the seam report uses. "no
  -- path" was the least informative sentence the harness could produce and
  -- the most often produced: use_warp hands it straight back ("couldn't
  -- reach the warp tile (no path)") and the model is left to invent a
  -- cause. Say how far the walk got, which reachable cell came closest,
  -- and what stands between that ground and the rest of the map.
  local nseen, bx, by, best = 0, nil, nil, 1e9
  for k in pairs(seen) do
    nseen = nseen + 1
    local cx, cy = k:match("^(-?%d+),(-?%d+)$")
    if cx then
      cx, cy = tonumber(cx), tonumber(cy)
      local d = math.abs(cx - tx) + math.abs(cy - ty)
      if d < best then best, bx, by = d, cx, cy end
    end
  end
  local said = ("no path — the ground you can walk from here is %d cell(s) "
    .. "and the closest it comes to %d,%d is %s,%s"):format(
      nseen, tx, ty, tostring(bx), tostring(by))
  local fence = {}
  for _, npc in ipairs(ow.npcs or {}) do
    local nx, ny = npc.cellX, npc.cellY
    if nx and ny then
      for _, d in ipairs({ {0, 1}, {0, -1}, {1, 0}, {-1, 0} }) do
        if seen[key(nx + d[1], ny + d[2])] and #fence < 4 then
          local mv = ((npc.def or {}).movement) or "STAY"
          fence[#fence + 1] = ("%s (a person, %s) at %d,%d"):format(
            tostring((npc.def or {}).name or "someone"),
            mv == "WALK" and "who wanders"
              or "standing still — they do not wander", nx, ny)
          break
        end
      end
    end
  end
  for _, b in ipairs(bushes_blocking(G, tx, ty, seen)) do
    if #fence < 6 then fence[#fence + 1] = b end
  end
  if #fence > 0 then
    said = said .. ". Standing against that ground: " ..
      table.concat(fence, ", ")
  end
  return nil, said
end

local function bfs_dir(G, tx, ty)
  local p = G.overworld.player
  if p.cellX == tx and p.cellY == ty then return nil, "arrived" end
  local wblock = warp_block(G, tx, ty)
  -- first around every learned script tile (bar the destination itself);
  -- only if that leaves no way at all, straight through
  local trig = trigger_cells(G)
  local any = false
  local soft = {}
  for k in pairs(wblock) do soft[k] = true end
  for k in pairs(trig) do
    if k ~= (tx .. "," .. ty) then soft[k] = true; any = true end
  end
  if any then
    local dir = bfs_dir_pass(G, tx, ty, soft)
    if dir then return dir end
  end
  return bfs_dir_pass(G, tx, ty, wblock)
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

-- `skip` takes the Nth walkable cell of that seam instead of the nearest.
-- A SEAM IS A ROW, NOT A DOOR. Route 13's west edge is 27 cells long and
-- this BFS always returned the nearest one, so the crossing landed on the
-- same Route 14 cell every time -- row 6, a one-tile corridor with a STAY
-- trainer parked at 15,6 four cells along it. Ignoring people that map is
-- ONE 486-cell area; with him standing there the landing is a four-cell
-- pocket whose only way on is back the way you came, and 93 visits later
-- the run still re-crossed into it. Rows 4 and 8 are open the whole way.
-- Which cell of a seam to walk to is pathfinding, same as the route to it;
-- the direction stays the model's.
local function bfs_to_edge(G, dir, skip)
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
  local skipn = tonumber(skip) or 0
  local nfound = 0
  -- the (skip+1)-th qualifying cell; BFS order means "farther along" is
  -- also "farther to walk", which is the right order to try them in
  local function take(x, y)
    nfound = nfound + 1
    if nfound > skipn then return x, y end
    return nil
  end
  if hit(p.cellX, p.cellY) and landing_ok(G, dir, p.cellX, p.cellY) then
    local rx, ry = take(p.cellX, p.cellY)
    if rx then return rx, ry end
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
  -- LEDGES ARE ONE-WAY, AND UPHILL THEY ARE A WALL. Cycling Road is a
  -- ladder of them: the run rode down to Fuchsia and then planned to walk
  -- back up, which cannot be done — and the failure said only "no walkable
  -- path", which reads as a pathing problem to solve rather than a rule of
  -- the world. Count the ledge tiles standing between the ground you can
  -- reach and the edge you asked for, and say what a ledge is.
  local ledge_tiles = {}
  do
    local ts = ow.map and ow.map.def and ow.map.def.tileset
    for _, lg in ipairs((G.data and G.data.field and G.data.field.ledges)
                        or {}) do
      if (lg.tileset or "OVERWORLD") == ts and lg.input == dir then
        ledge_tiles[lg.ledgeTile] = true
      end
    end
  end
  local nwall_ledge = 0
  -- WATER IS NOT A WALL IF SOMEBODY CAN SURF. The pathfinder asks the
  -- engine, which blocks water for a walker, so an ocean between here and
  -- the seam came back as a flat "no walkable path" — the one fact that
  -- would change the answer (a party member knows SURF) never said.
  local nwater = 0
  local knows_surf = false
  for _, mon in ipairs((G.save or {}).party or {}) do
    for _, mv in ipairs(mon.moves or {}) do
      if tostring(type(mv) == "table" and mv.id or mv) == "SURF" then
        knows_surf = true
      end
    end
  end
  -- ...AND CYCLING ROAD IS NOT LEDGES AT ALL. On a slope map the bike is
  -- pulled one cell SOUTH on every idle poll (OverworldController:1251,
  -- Game.data.field.forcedMovement.slopeMaps) unless A or B is held, so a
  -- northward walk is undone as fast as it is made. Walking is not the
  -- thing that is failing; the map is.
  local on_slope = false
  do
    local fm = G.data and G.data.field and G.data.field.forcedMovement
    for _, mm in ipairs((fm and fm.slopeMaps) or {}) do
      if mm == (ow.map and ow.map.id) then on_slope = true end
    end
  end
  local best, bestx, besty = 1e9, nil, nil
  local function dist(x, y)
    if dir == "up" then return y end
    if dir == "down" then return (H - 1) - y end
    if dir == "left" then return x end
    return (W - 1) - x
  end
  local function note(x, y)
    nseen = nseen + 1
    -- does the cell one step toward the wanted edge hold a ledge? then a
    -- ledge is what stands between this ground and that edge
    do
      local d2 = DIRS[dir]
      if d2 and ow.map and ow.map.cellTile then
        local t2 = ow.map:cellTile(x + d2[1], y + d2[2])
        if ledge_tiles[t2] then nwall_ledge = nwall_ledge + 1 end
      end
      if d2 and ow.map and ow.map.isWaterCell
         and ow.map:isWaterCell(x + d2[1], y + d2[2]) then
        nwater = nwater + 1
      end
    end
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
                local rx, ry = take(sx, sy)
                if rx then return rx, ry end
              end
              queue[#queue + 1] = { x = sx, y = sy }
            end
          else
            note(nx, ny)
            if hit(nx, ny) then
              if landing_ok(G, dir, nx, ny) then
                local rx, ry = take(nx, ny)
                if rx then return rx, ry end
              else
                edge_rejected = edge_rejected + 1
              end
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
              if landing_ok(G, dir, lx, ly) then
                local rx, ry = take(lx, ly)
                if rx then return rx, ry end
              else
                edge_rejected = edge_rejected + 1
              end
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
  -- ONE-SHOT DIAGNOSTIC (ours, not the model's): when a seam walk ends in
  -- a small pocket, dump the tile ids on its boundary. Route 14 is stacked
  -- with ledge rows and the BFS reported ZERO ledge hops, which is either
  -- "no ledge touches this nook" or "our ledge-tile match is wrong for this
  -- tileset" — and those need opposite fixes.
  if nseen <= 24 and ow.map and ow.map.cellTile then
    local edge_tiles = {}
    for k in pairs(seen) do
      local sx, sy = k:match("^(-?%d+),(-?%d+)$")
      sx, sy = tonumber(sx), tonumber(sy)
      for dn, d in pairs(DIRS) do
        local nx2, ny2 = sx + d[1], sy + d[2]
        if not seen[nx2 .. "," .. ny2] and ow.map:inBounds(nx2, ny2) then
          edge_tiles[#edge_tiles + 1] = ("%s:%d@%d,%d"):format(
            dn, ow.map:cellTile(nx2, ny2), nx2, ny2)
        end
      end
    end
    print(("[pocket] %s %d cells, tileset=%s, boundary tiles: %s"):format(
      tostring(ow.map.id), nseen, tostring(ow.map.def and ow.map.def.tileset),
      table.concat(edge_tiles, " ", 1, math.min(#edge_tiles, 24))))
  end
  return nil, nil, ("BFS from %d,%d walked %d cells (%d ledge hop%s, %d arrow-tile "
    .. "slide%s); closest to "
    .. "the %s edge was %s,%s, still %d cell%s short%s")
    :format(p.cellX, p.cellY, nseen, nledge, nledge == 1 and "" or "s",
            nspin, nspin == 1 and "" or "s", dir, tostring(bestx), tostring(besty), best,
            best == 1 and "" or "s",
            edge_rejected > 0
              and ("; it DID reach the edge " .. edge_rejected
                   .. "x but the landing on the far side was refused")
              or "")
    .. ((on_slope and (dir == "up" or dir == "north"))
        and (". THIS MAP IS A SLOPE: on the bike here the game moves you "
             .. "one cell SOUTH whenever no direction is being held. "
             .. "Walking north still works while you keep walking — the "
             .. "drift only takes back the ground you stop on, so a walk "
             .. "up costs more steps than a walk down, and pausing loses "
             .. "some of it")
        or "")
    .. ((nwater > 0)
        and ((". %d WATER cell(s) lie between the ground you can reach and "
              .. "that edge%s"):format(nwater,
             knows_surf
               and (" — and a party Pokemon knows SURF: {\"op\":\"field_move"
                    .. "\",\"move\":\"SURF\",\"x\":N,\"y\":N} at a water "
                    .. "tile you are standing beside puts you on it, and "
                    .. "from there water is walkable")
               or " — nobody in the party can SURF, so water is a wall"))
        or "")
    .. (nwall_ledge > 0
        and (". " .. nwall_ledge .. " LEDGE tile(s) stand between the "
             .. "ground you can reach and that edge — a ledge is a ONE-WAY "
             .. "drop: it can be hopped DOWN and never climbed, so this "
             .. "direction is not a way back")
        or ""), bestx, besty, seen, nseen
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

-- A COUNTER AND A PC ARE NOT THINGS YOU PRESS A ON (user, 2026-08-17).
-- Assigned once the ui_* helpers below exist; declared here because the
-- generic key ops are defined above them.
--
-- WHAT THIS IS FOR. The run bought FIFTEEN POKE BALLs without ever
-- proposing a buy op: menu(index=1) picked BUY and a boilerplate
-- answer="yes" rode the "That'll be 200. OK?" confirmations, one ball per
-- cycle, 3175 money down to 175, every trace line reading "ok (moved,
-- dialog still open)". Nothing about that was a decision. The same shape
-- can deposit or release a Pokemon by accident now that the boxes are
-- writable, and a released Pokemon does not come back.
--
-- THIS IS THE FILE'S OWN RULE, not a new one. A bare interact already
-- refuses to drive a party picker ("WHICH POKEMON IS NOT THE HARNESS'S
-- CHOICE") and an elevator's floor list ("WHICH FLOOR IS NOT THE
-- HARNESS'S CHOICE EITHER"), for exactly this reason: an op that has
-- chosen says so, a bare press has not chosen anything. A shop counter
-- and PC storage are the same kind of screen and were the only ones left
-- open to blind pressing.
--
-- IT REMOVES NO CAPABILITY. Everything reachable by mashing is reachable
-- through buy/sell/store_item/retrieve_item/pc_deposit/pc_withdraw/
-- pc_release, and those say WHAT and HOW MANY, which is the part that was
-- being lost. The PC's own top-level list is deliberately NOT guarded, so
-- navigating it — PROF.OAK's dex rating, SEE YA — still works.
local ui_transaction_up
local function hands_off(G, c)
  -- B IS ALWAYS ALLOWED. It closes a screen and cannot spend anything, and
  -- without it this guard is a trap: menu(index=2) opened the item PC, and
  -- from inside it every menu/tap/mash was refused, so the run could not
  -- get back to row 1 to pick the box menu it actually wanted. It was
  -- doing the right thing and had no way to act on it.
  if c and c.btn == "b" then return nil end
  local kind = ui_transaction_up and ui_transaction_up(G)
  if kind == "shop" then
    -- SHORT, because this fires on every press and the prompt's budget is
    -- its order. The 15-POKE_BALL story is the JUSTIFICATION and it lives
    -- in the comment above, not in front of the model 392 characters at a
    -- time. See also the caller, which leads with what was actually SAID.
    return "that is a shop COUNTER. Trade with {\"op\":\"buy\",...} or "
      .. "{\"op\":\"sell\",...}; {\"op\":\"tap\",\"btn\":\"b\"} "
      .. "steps out. Left open, nothing bought."
  elseif kind == "pc" then
    return "that is PC STORAGE. Use store_item / retrieve_item / "
      .. "pc_deposit{slot} / pc_withdraw{index,box} / "
      .. "pc_release{index,species}; {\"op\":\"tap\",\"btn\":\"b\"} "
      .. "steps out. Left open, nothing moved."
  end
  return nil
end

function OPS.tap(G, c)
  local no = hands_off(G, c)
  if no then return false, no end
  U.tap(G, c.btn or "a")
  return true
end

function OPS.mash_a(G, c)
  local no = hands_off(G)
  if no then return false, no end
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
  -- CLIMBING A SLOPE: HOLD UP WHERE UP IS OPEN, STEP ROUND WHERE IT IS NOT.
  -- On a slope map the game moves you one cell downhill on every poll with
  -- no direction held, so releasing the d-pad between cells (which walk_to
  -- does) gives the road a free push back. Holding UP blindly is no good
  -- either: the road bends, and against a fence the hold just stalls —
  -- which is what "goes up a bit then thrashes" looks like. So: while the
  -- BFS says north, HOLD it until the row actually changes; when the BFS
  -- says anything else, take one ordinary step and resume.
  local _slope_map = false
  for _, mm in ipairs(((G.data and G.data.field
                        and G.data.field.forcedMovement) or {}).slopeMaps
                      or {}) do
    if mm == startMap then _slope_map = true end
  end
  local function _step(dir)
    if not (_slope_map and dir == "up") then return walk(G, dir, 1) end
    local y0, st = p.cellY, 0
    G.input.state["up"] = true
    for _ = 1, 240 do
      table.insert(G.input.pressQueue, "up")
      coroutine.yield()
      if G.stack:top() ~= ow then break end
      if (ow.map and ow.map.id) ~= startMap then break end
      if p.cellY < y0 then break end
      st = st + 1
      if st > 90 then break end          -- north is walled here: go round
    end
    G.input.state["up"] = false
    return p.cellY < y0
  end
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
      -- OPT IN TO SWIMMING. `surf=true` says: if the way on is water, get
      -- on it. The harness does the mechanics (find the water tile beside
      -- ground we can reach, stand at it, use the move); WHETHER to swim —
      -- water has its own wild encounters and its own places to be dumped
      -- — stays the model's, exactly like intent= on grind.
      if c.surf and not p.surfing then
        local knows = false
        for _, mon in ipairs((G.save or {}).party or {}) do
          for _, mv in ipairs(mon.moves or {}) do
            if tostring(type(mv) == "table" and mv.id or mv) == "SURF" then
              knows = true
            end
          end
        end
        if not knows then
          return false, "no party Pokemon knows SURF, so water cannot be "
            .. "crossed (" .. tostring(why) .. ")"
        end
        local reach = warp_reach(G) or {}
        local bx, by, bland, bd
        for k in pairs(reach) do
          local sx, sy = k:match("^(-?%d+),(-?%d+)$")
          sx, sy = tonumber(sx), tonumber(sy)
          for _, d in pairs(DIRS) do
            local wx, wy = sx + d[1], sy + d[2]
            if ow.map.isWaterCell and ow.map:inBounds(wx, wy)
               and ow.map:isWaterCell(wx, wy) then
              local dd = math.abs(wx - c.x) + math.abs(wy - c.y)
              if not bd or dd < bd then
                bd, bx, by, bland = dd, wx, wy, { sx, sy }
              end
            end
          end
        end
        if not bx then
          return false, "nothing here is water to surf on ("
            .. tostring(why) .. ")"
        end
        OPS.walk_to(G, { x = bland[1], y = bland[2], max_steps = 200 })
        local ok2, why2 = OPS.field_move(G, { move = "SURF", x = bx, y = by })
        if not ok2 then
          return false, "could not get onto the water: " .. tostring(why2)
        end
        dir = bfs_dir(G, c.x, c.y)
        if not dir then
          return false, "even on the water there is no path to (" .. c.x
            .. "," .. c.y .. ")"
        end
      else
        return why == "arrived", why
      end
    end
    local moved
    for attempt = 1, 3 do
      moved = _step(dir)
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
  -- A LADDER YOU ARRIVED ON DOES NOT FIRE UNDER YOUR FEET. A warp triggers
  -- on the step ONTO it, so the tile the last warp deposited you on is
  -- inert until you leave and come back. use_warp aimed at the tile you are
  -- already standing on skipped the walk entirely and fell through to the
  -- press loop, which is written for map-EDGE doorways (stand on the mat,
  -- press into the wall) and does nothing for a ladder in the middle of a
  -- cave floor. Step off to a plain neighbouring cell first and let the
  -- ordinary walk-onto path -- the one that works -- do the work.
  local function step_off(x, y)
    local okc2, Collision2 = pcall(require, "src.world.Collision")
    if not okc2 then return end
    local warps = {}
    for _, w in ipairs(((ow.map and ow.map.def) or {}).warps or {}) do
      warps[w.x .. "," .. w.y] = true
    end
    for _, dn in ipairs({ "down", "up", "left", "right" }) do
      local d = DIRS[dn]
      local nx, ny = x + d[1], y + d[2]
      if not warps[nx .. "," .. ny]
         and Collision2.canMove(ow.map, ow.entities, p, dn) then
        OPS.walk_to(G, { x = nx, y = ny, max_steps = 4 })
        return
      end
    end
  end
  local function attempt(x, y)
    local stepped = false
    if p.cellX == x and p.cellY == y then
      step_off(x, y)
      stepped = (p.cellX ~= x or p.cellY ~= y)
    end
    -- ...AND THAT CROSSING IS NOT AN UNKNOWN DOOR. "crossed mid-walk"
    -- means the walk passed over a warp that was not the one we aimed at,
    -- so the executor is told to file no edge. When WE stepped the party
    -- one cell off the tile it asked for and walked it straight back, the
    -- door that fired is the door we aimed at, and the edge is knowable.
    local function crossed()
      if (ow.map and ow.map.id) == startMap then return nil end
      if stepped then return true, "warped" end
      return true, "crossed mid-walk (door unknown)"
    end
    -- Three passes, yielding ground between them: pass 1 is the plain
    -- walk, and each retry backs off a tile first so an NPC pinned by the
    -- player has somewhere to go. cross() is already NPC-robust this way
    -- (it re-BFSes across rounds); a door needs the same patience.
    for pass = 1, 3 do
      if p.cellX ~= x or p.cellY ~= y then
        local _wok, _wwhy = OPS.walk_to(
          G, { x = x, y = y, max_steps = c.max_steps or 400 })
        walk_why = _wwhy or walk_why
        local _ok, _why = crossed()
        if _ok then return _ok, _why end
      end
      if p.cellX == x and p.cellY == y then break end
      if pass < 3 then yield_ground(G) end
      local _ok, _why = crossed()
      if _ok then return _ok, _why end
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
    -- ...AND IF THE ENGINE WILL SAY WHICH WAY FIRES IT, ASK. A gate doorway
    -- or the Vermilion pier fires on a BLOCKED step toward a carpet tile
    -- (Warp.extraCheck), and which direction that is has nothing to do
    -- with which map edge the tile is near -- Route 7's east gate wants
    -- "right", Route 8's wants "left", the dock wants "down". Guessing
    -- costs three presses and three walks back onto the tile, each of
    -- which can drift the party off it.
    do
      local okw, WarpM = pcall(require, "src.world.Warp")
      local carpets = G.data and G.data.field and G.data.field.warpCarpets
      local lm = ow.map
      if okw and WarpM and WarpM.extraCheck and lm then
        for _, dn in ipairs({ "down", "up", "left", "right" }) do
          local okc, fires = pcall(WarpM.extraCheck, lm, carpets, x, y, dn)
          if okc and fires then
            local head = { dn }
            for _, d2 in ipairs(order) do
              if d2 ~= dn then head[#head + 1] = d2 end
            end
            order = head
            break
          end
        end
      end
    end
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
        -- A WARP CAN LAND YOU ON THE SAME MAP. Silph's floors are stitched
        -- with pad PAIRS that lead back to the floor they sit on:
        --   warp  3,11 -> SILPH_CO_8F   warp 11,9 -> SILPH_CO_8F
        -- step on one and you are standing on the other, same map id. The
        -- fire test only ever asked "did the map change", so every one of
        -- those reported "stepped through but no warp fired" while firing
        -- perfectly — and the ledger wrote them off. Teleported is: no
        -- longer on the tile we stepped onto, and not merely one step from
        -- it either.
        -- READ THE PLAYER FRESH. The engine swaps state objects on a map
        -- load — the lift probe caught exactly that, a stack top whose
        -- overworld table was a different address from G.overworld — so a
        -- player captured at op start can go stale the moment a warp
        -- fires, and a stale cellX/cellY never moves however far you were
        -- taken.
        local _pp = (G.overworld and G.overworld.player) or p
        if math.abs((_pp.cellX or 0) - x) + math.abs((_pp.cellY or 0) - y) > 1
           and not _pp.moving then
          G.input.state[dir] = false
          U.wait(20)
          return true
        end
      end
      G.input.state[dir] = false
      U.wait(4)
    end
    do
      local _pp = (G.overworld and G.overworld.player) or p
      print(("[warp] no fire at %d,%d — player now %s,%s map=%s")
        :format(x, y, tostring(_pp.cellX), tostring(_pp.cellY),
                tostring((G.overworld.map or {}).id)))
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
  local _px0, _py0 = p.cellX, p.cellY
  for _, t in ipairs(tiles) do
    local ok, w = attempt(t.x, t.y)
    if ok or (ow.map and ow.map.id) ~= startMap then
      -- say WHERE a same-map warp put you; "warped" alone reads like
      -- nothing happened when the map id is unchanged
      if (ow.map and ow.map.id) == startMap then
        local _pp = (G.overworld and G.overworld.player) or p
        return true, ("warped — same map, you are now at %d,%d")
          :format(_pp.cellX or -1, _pp.cellY or -1)
      end
      return true, "warped"
    end
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
          -- SAY WHICH KIND OF PERSON, same as the seam report. A posted
          -- guard and a passer-by both "stand in front of a door", and
          -- the advice for them is opposite: one has a reason to give,
          -- the other will have wandered off in a moment. Saffron's
          -- ROCKET7 is movement=WALK, drifted in front of the Pokemon
          -- Center, and the run wrote the Center off as blocked.
          local _mv = ((npc.def or {}).movement) or "STAY"
          blockers[#blockers + 1] = ("%s at (%d,%d)%s")
            :format(nm, npc.cellX, npc.cellY,
                    _mv == "WALK" and " (who wanders)" or "")
          blockers[nm] = true
          if _mv == "WALK" then blockers.mover = true end
        end
      end
    end
  end
  if #blockers > 0 then
    return false, "couldn't reach the warp tile — somebody is standing by "
      .. "it: " .. table.concat(blockers, ", ")
      .. (blockers.mover
          and ". Someone marked (who wanders) walks a patch of ground and "
              .. "is not posted there — they move, so the same door often "
              .. "opens on a later try."
          or ". People who stand in front of doors in this game usually "
              .. "say why; interact with them to hear it.")
  end
  -- NOT A DOOR OF THIS MAP AT ALL. Standing in Vermilion, use_warp(17,13)
  -- — Route 6's underground-path door — failed as "couldn't reach the
  -- warp tile (no path)", which reads as a blocked road when the truth is
  -- a different map's coordinates. Doors are per map; say whose these are
  -- not, and which doors ARE here.
  do
    local md2 = G.data and G.data.maps and G.data.maps[startMap]
    local is_door = false
    for _, w in ipairs((md2 and md2.warps) or {}) do
      if w.x == c.x and w.y == c.y then is_door = true break end
    end
    if not is_door then
      local here = {}
      for _, w in ipairs((md2 and md2.warps) or {}) do
        here[#here + 1] = ("(%d,%d)"):format(w.x, w.y)
      end
      return false, ("there is no door at (%d,%d) on %s — door coordinates "
        .. "belong to ONE map. For a door on a map you have walked, say "
        .. "{\"op\":\"use_warp\",\"map\":\"THAT_MAP\",\"x\":..,\"y\":..} "
        .. "and you are walked there first over walked ground. "
        .. "Doors on this map: %s")
        :format(c.x, c.y, tostring(startMap),
                #here > 0 and table.concat(here, ", ") or "none")
    end
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
  local seen_cells, nseen_cells
  for round = 1, 4 do
    ex, ey, bfs_why, stallx, stally, seen_cells, nseen_cells =
      bfs_to_edge(G, dir, c.skip)
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
        -- ACTIONABLE IS A TIE-BREAK, NOT A TRUMP. A cuttable bush thirty
        -- cells away was ranked above the trainer standing ON the cell the
        -- walk stopped at, so the report opened with three bushes and
        -- buried the one thing in the way. Nearness first; being
        -- actionable is worth a couple of cells, not the top of the list.
        blockers[#blockers + 1] = { s = ("%s at %d,%d"):format(tag, x, y),
                                    d = actionable and math.max(0, d - 3) or d }
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
    -- ...AND A PERSON BESIDE THE STALL POINT COUNTS WHEREVER THE STALL IS.
    -- The near-seam band is 12 cells; Route 9's walk from Cerulean stalled
    -- at 4,8 with the east seam 55 cells off, and the one thing next to
    -- 4,8 -- whoever was standing in the corridor -- failed the band test
    -- and went unnamed, while a trainer at 48,8 was reported as "near
    -- that edge, though not what stopped you". Name what is next to where
    -- the walk stopped first; the band still covers the rest.
    -- ...AND WHOEVER STANDS AT THE EDGE OF A SMALL POCKET. Route 12 from
    -- the Route 11 gate is a 14-cell pocket with a sleeping SNORLAX on its
    -- one road north; the stall point (the cell nearest the seam) was two
    -- cells from the seam and nowhere near the Snorlax, so the report read
    -- "Nothing this map lists sits against that edge". When the ground
    -- reachable is small, anyone adjacent to ANY of it is what fences it.
    local pocket = (seen_cells and nseen_cells and nseen_cells <= 60)
      and seen_cells or nil
    local function fences_pocket(nx, ny)
      if not pocket then return false end
      return pocket[(nx + 1) .. "," .. ny] or pocket[(nx - 1) .. "," .. ny]
        or pocket[nx .. "," .. (ny + 1)] or pocket[nx .. "," .. (ny - 1)]
    end
    local fence = {}
    -- ...AND A BUSH IS AS MUCH A FENCE AS A PERSON. Route 14 dropped the
    -- run into a four-cell nook whose edge is cut trees; the report named
    -- nobody, because only NPCs were scanned, and read as "no walkable
    -- path" with no cause at all.
    if pocket then
      local ts2 = lm and lm.def and lm.def.tileset
      local want2 = (ts2 == "OVERWORLD" and 0x3d) or (ts2 == "GYM" and 0x50)
      if want2 and lm and lm.cellTile then
        local W3, H3 = map_dims_cells(G)
        for cy = 0, math.min(H3 - 1, 71) do
          for cx = 0, math.min(W3 - 1, 71) do
            if lm:cellTile(cx, cy) == want2 and not lm:isWalkableCell(cx, cy)
               and fences_pocket(cx, cy) then
              fence[#fence + 1] = ("CUT_TREE (a bush CUT clears) at (%d,%d)")
                :format(cx, cy)
            end
          end
        end
      end
    end
    for _, npc in ipairs((ow.npcs) or {}) do
      local nx, ny = npc.cellX, npc.cellY
      if nx and ny then
        local by_stall = stallx and stally
          and (math.abs(nx - stallx) + math.abs(ny - stally)) <= 1
        if fences_pocket(nx, ny) and not by_stall then
          fence[#fence + 1] = ("%s at %d,%d"):format(
            tostring((npc.def or {}).name or "someone"), nx, ny)
        elseif by_stall or near_seam(nx, ny) then
          -- ...AND SAY WHICH KIND OF PERSON. Every sprite was labelled
          -- "who moves", which for a STAY trainer is a lie the model can
          -- act on: it waits for someone to wander off who never will.
          -- The engine keeps the movement in the object data and the
          -- reach fill already reads it.
          local _mv = ((npc.def or {}).movement) or "STAY"
          add(tostring((npc.def or {}).name or "someone")
              .. (_mv == "WALK" and " (a person, who wanders)"
                  or " (a person, standing still — they do not wander)"),
              nx, ny)
        end
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
    if #fence > 0 then
      said = said .. (" The ground you can reach from here is only %d "
        .. "cell(s), and standing at its edge: %s."):format(
          nseen_cells or 0, table.concat(fence, ", "))
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
    -- ...AND WHAT *IS* REACHABLE FROM WHERE YOU STAND. A seam that cannot
    -- be walked to ended the report there, so a run that had just CUT its
    -- way onto new ground read "no path" and gave the map up — while the
    -- doors it could walk to sat unmentioned three lines from the failure.
    -- The executor's ledger says which have been TAKEN; the shim can at
    -- least say which exist and are reachable right now.
    do
      local md3 = G.data and G.data.maps and G.data.maps[startMap]
      local reach = warp_reach(G) or {}
      local open_doors = {}
      for _, w in ipairs((md3 and md3.warps) or {}) do
        local k = w.x .. "," .. w.y
        if reach[k] then open_doors[#open_doors + 1] = ("(%d,%d)"):format(w.x, w.y) end
      end
      if #open_doors > 0 then
        said = said .. (" You are not shut in: %d door(s) on this map CAN "
          .. "be walked to from where you stand — %s. The ledger says which "
          .. "of them you have already opened."):format(
            #open_doors, table.concat(open_doors, ", "))
      end
    end
    return false, ("the %s seam of %s (to %s) cannot be walked to from "
      .. "here — no walkable path reaches it."):format(
        cmap[dir], tostring(startMap), tostring(dest and dest.map or "?"))
      .. (bfs_why and (" " .. bfs_why .. ".") or "") .. said
  end
  if p.cellX ~= ex or p.cellY ~= ey then
    for round = 1, 3 do
      -- A STEP BUDGET MUST FIT THE MAP. 200 was fine for a town and is
      -- nothing on Cycling Road: Route 17 is 144 cells tall, so a climb
      -- from the bottom needs more steps than the budget allowed and the
      -- walk reported "stuck" having barely moved. Scale it to the
      -- distance actually being walked (and keep a floor for short hops).
      local _need = math.abs((ex or 0) - p.cellX) + math.abs((ey or 0) - p.cellY)
      OPS.walk_to(G, { x = ex, y = ey, surf = c.surf,
                       max_steps = c.max_steps or math.max(200, _need * 3) })
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
      -- WHY the walk could not start. Two rules of this map can stop it
      -- and they read identically from outside: LEDGES (one-way drops that
      -- cannot be climbed) and a SLOPE (the bike is pushed back whenever
      -- no direction is held). Both are in the engine's own field data.
      local why2 = ""
      do
        local ts = ow.map and ow.map.def and ow.map.def.tileset
        local lt = {}
        for _, lg in ipairs((G.data and G.data.field
                             and G.data.field.ledges) or {}) do
          if (lg.tileset or "OVERWORLD") == ts then lt[lg.ledgeTile] = true end
        end
        local nl = 0
        if ow.map and ow.map.cellTile then
          local step = (ey < p.cellY) and -1 or 1
          for yy = p.cellY, ey, step do
            if lt[ow.map:cellTile(p.cellX, yy)] then nl = nl + 1 end
          end
        end
        local slope = false
        for _, mm in ipairs(((G.data and G.data.field
                              and G.data.field.forcedMovement) or {}).slopeMaps
                            or {}) do
          if mm == (ow.map and ow.map.id) then slope = true end
        end
        if nl > 0 then
          why2 = why2 .. (" — %d LEDGE tile(s) lie along that line, and a "
            .. "ledge is a ONE-WAY drop: it can be hopped down, never "
            .. "climbed"):format(nl)
        end
        if slope then
          why2 = why2 .. " — and this map is a SLOPE: on the bike the game "
            .. "moves you one cell downhill whenever no direction is held"
        end
        if why2 ~= "" then
          why2 = why2 .. ". If both halves of that are true of the way you "
            .. "want, this road runs one way and the way back is another road"
        end
      end
      return false, ("couldn't reach %s edge gap (%d,%d), stuck at (%d,%d) "
        .. "— %d cell(s) of walking still to do%s")
        :format(tostring(c.dir), ex, ey, p.cellX, p.cellY,
                math.abs(ex - p.cellX) + math.abs(ey - p.cellY), why2)
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
    -- A SLOT MACHINE MID-SPIN IGNORES B: its spinup/spin/payout/flash
    -- stages only advance on A (each A stops a wheel), and B exits only
    -- from the bet / one-more / intro prompts. B-mashing here held the
    -- run hostage for a whole attempt ("tap(btn=b): NO visible effect"
    -- x rounds). Ride the spin out with A, then B leaves as normal.
    if t and t.screenId == "SlotMachine"
       and t.stage ~= "bet" and t.stage ~= "onemore"
       and t.stage ~= "intro" then
      U.tap(G, "a"); U.wait(6)
    else
      U.tap(G, "b"); U.wait(6)
    end
    if t == seen_top and (t and t.pageIndex) == seen_idx then
      stall = stall + 1
      if stall > 100 then return false end
    else
      stall, seen_top, seen_idx = 0, t, (t and t.pageIndex)
    end
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

-- WHICH SCREENS A BLIND PRESS CAN SPEND SOMETHING ON. Assigned into the
-- forward-declared local near OPS.tap; see hands_off there for why.
--
-- The two engine screens that MOVE things carry their own ids (BoxMenu,
-- PlayerPC), and the lists they push are raw ListMenus that keep the title
-- they were built with ("BOX 3 (WITHDRAW)", "PARTY (DEPOSIT)", "DEPOSIT
-- ITEM"). The PC's own top-level list is neither and stays open on
-- purpose: choosing PROF.OAK's dex rating or SEE YA moves nothing.
function ui_transaction_up(G)
  if ui_shop_up(G) then return "shop" end
  local t = ui_top(G)
  if not t then return nil end
  local sid = tostring(t.screenId or "")
  if sid == "BoxMenu" or sid == "PlayerPC" then return "pc" end
  local title = tostring(t.title or ""):upper()
  if title:find("^BOX %d") or title:find("^PARTY %(DEPOSIT")
     or title == "DEPOSIT ITEM" or title == "WITHDRAW ITEM" then
    return "pc"
  end
  return nil
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
  -- A FIELD ITEM ACTS ON WHAT YOU ARE STANDING BESIDE, and the game says
  -- so in its own words when there is nothing there ("Now, that's a catchy
  -- tune!" / "It won't have any effect"). The op reported a flat "used
  -- POKE_FLUTE" either way, so playing it three maps from the thing it was
  -- meant for looked exactly like the thing refusing it. Report the
  -- no-effect as a no-effect and name the rule — WHAT it acts on stays the
  -- model's knowledge; the harness only says where you were standing.
  do
    local said = tostring(recent_text or last_text or "")
    if said:find("catchy tune") or said:find("won't have any effect")
       or said:find("no effect") then
      local p2 = G.overworld.player
      return true, ("used " .. c.item .. " and NOTHING HAPPENED — the game "
        .. "said \"" .. said:gsub("\n", " ") .. "\". A field item acts on "
        .. "what you are standing RIGHT NEXT TO, and from (%d,%d) there was "
        .. "nothing for it to act on."):format(p2.cellX, p2.cellY)
    end
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
      -- SAY WHAT IS IN THE WAY, and whether the tree is even on ground we
      -- can reach. "No reachable tile adjacent" is the same sentence for
      -- "somebody is standing there", "it is across a fence" and "it is in
      -- another part of this map" — three different problems, and the run
      -- re-pressed CUT at a tree on the far side of Route 14's ledges for
      -- a whole attempt.
      local occ = {}
      for _, a in ipairs(adj) do
        for _, npc in ipairs(ow.npcs or {}) do
          if npc.cellX == a[1] and npc.cellY == a[2] then
            occ[#occ + 1] = ("%s at (%d,%d)"):format(
              tostring((npc.def or {}).name or "someone"), a[1], a[2])
          end
        end
      end
      local reach = warp_reach(G) or {}
      local any_side = false
      for _, a in ipairs(adj) do
        if reach[a[1] .. "," .. a[2]] then any_side = true end
      end
      for _, a in ipairs(adj) do
        if cut_bush_at(G, a[1], a[2]) then
          occ[#occ + 1] = ("CUT_TREE (a bush CUT clears) at (%d,%d)")
            :format(a[1], a[2])
        end
      end
      if #occ > 0 then
        return false, "no reachable tile adjacent to the target — standing "
          .. "on the tiles you would use it from: " .. table.concat(occ, ", ")
      end
      if not any_side then
        local _b = bushes_blocking(G, c.x, c.y, reach)
        return false, ("no reachable tile adjacent to the target — none of "
          .. "the four tiles around (%d,%d) is ground you can walk to from "
          .. "where you stand, so that %s is in a part of this map you "
          .. "cannot reach from here.%s"):format(
            c.x, c.y, tostring(mv),
            #_b > 0 and (" Standing between the ground you can reach and "
              .. "the rest of this map: " .. table.concat(_b, ", ") .. ".")
              or "")
      end
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
      -- THE GAME REFUSED THE MOVE, IN WORDS. "There isn't anything to
      -- CUT!" drops back into the party menu, where the A-mash below
      -- opened a mon's SUMMARY and the op returned true, "used CUT" —
      -- a stuck screen and a lie in one. The sentence on screen is the
      -- verdict; close everything and hand it over.
      if said:find("isn't anything") or said:find("can't be used")
         or said:find("Oak's words") then
        ui_back_out(G)
        return false, mv .. " did nothing here — the game says: \""
          .. said:gsub("\n", " ") .. "\""
      end
    end
    U.tap(G, "a"); U.wait(5)
  end
  -- honest exit: if the screen never returned to the overworld, say so
  -- (and clean up) instead of reporting the move used
  if G.stack:top() ~= ow then
    local t = G.stack:top()
    -- FLY ENDS IN A CHOICE, AND CHOICES ARE THE MODEL'S. Selecting FLY
    -- opens the destination list (src/ui/FlyMenu.lua: a plain ListMenu of
    -- the towns the save records as VISITED), and this exit backed out of
    -- it and reported "FLY did not fire" — so the move was unusable from
    -- the moment it was taught. Same rule as the vending machine, the PC
    -- and the elevator panel: leave the list OPEN, number the rows as they
    -- read on screen, and say how to choose. The harness flies nowhere on
    -- its own, and the list only ever offers towns already visited.
    if t and t.items and t.items[1] then
      local labels = {}
      for i, r in ipairs(t.items) do
        labels[#labels + 1] = ("%d=%s"):format(
          i, tostring(r.label or r.value or "?"))
      end
      return true, ("%s opened a list%s: %s. Nothing was chosen and it is "
        .. "left OPEN. Pick a row with {\"op\":\"menu\",\"index\":N}, "
        .. "or {\"op\":\"tap\",\"btn\":\"b\"} to leave it."):format(
          mv, t.title and (" (" .. tostring(t.title) .. ")") or "",
          table.concat(labels, ", "))
    end
    if not (t and (t.enemy or t.kind)) then
      ui_back_out(G)
      if G.stack:top() ~= ow then
        return false, mv .. " left a screen up that would not close"
      end
      return false, mv .. " did not fire (the menus closed without it)"
    end
  end
  U.wait(24)   -- the cut animation finishes after the text closes
  return true, "used " .. mv .. (said and (" — " .. said) or "")
end

-- Toss items from the bag. WHAT to toss is entirely the model's call
-- (its treasure vs its junk); driving the TOSS row and the quantity
-- wheel is mechanics. Born at the captain's cabin: a 20-of-20 bag ate
-- HM01 silently.
-- Items the engine can USE on a party member, from its own tables
-- (src/inventory/ItemEffects.lua: STONES, VITAMINS, plus the HM/TM teach
-- flow). Says only THAT an item has a use, never what the use is — what a
-- stone does to a Pokemon is the model's to know, and the item's own name
-- is already on screen.
local function item_has_a_use(id)
  local ok, IE = pcall(require, "src.inventory.ItemEffects")
  if not ok or not IE then return false end
  id = tostring(id or "")
  if id:match("^TM_") or id:match("^HM_") then return true end
  for _, tbl in ipairs({ IE.STONES, IE.VITAMINS, IE.stones, IE.vitamins }) do
    if type(tbl) == "table" and tbl[id] then return true end
  end
  -- the tables above are locals in some builds; fall back to the names,
  -- which are the game's own and already printed to the model
  return id:match("_STONE$") ~= nil
      or id == "HP_UP" or id == "PROTEIN" or id == "IRON"
      or id == "CARBOS" or id == "CALCIUM" or id == "RARE_CANDY"
end

function OPS.toss(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  if not c.item then return false, "toss needs item" end
  local have = bag_count(G, c.item)
  if have < 1 then return false, "no " .. c.item .. " in the bag" end
  -- THROWING AWAY A THING THAT HAD A USE. The bag pressure line lists
  -- what can go, and a MOON_STONE sat in it looking like dead weight: on
  -- Silph 11F the run tossed one to free a slot for two item balls. The
  -- harness may not say what a stone does, but it can say the item is one
  -- the game will let you USE on a party member, and that tossing ends
  -- that. Refused once; re-issue the same toss and it goes.
  if item_has_a_use(c.item) and not c.confirm then
    return false, (c.item .. " is something this game will let you USE on "
      .. "a party member ({\"op\":\"use_item\",\"item\":\"" .. c.item
      .. "\",\"slot\":N}) — using it spends it and keeps whatever it is "
      .. "worth, tossing it destroys that. Nothing has been thrown away. "
      .. "If you meant it, send the same toss again with \"confirm\":true.")
  end
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

-- Walk to this map's PC and turn it on, leaving its top menu up. Says
-- nothing about WHICH storage you wanted; pc_open_storage and
-- pc_open_boxes pick that up from here.
local function pc_open_menu(G)
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
  return true
end

-- WHICH PC. The terminal offers several: the player's own name is item
-- storage, "SOMEONE'S PC" (or "BILL'S PC" once you have met him) is the
-- Pokemon boxes, and PROF.OAK's is the dex rating. Everything above this
-- line is walking to the machine and turning it on, which is identical
-- whichever one you want — it was written inline in the item path and had
-- to come out whole before the boxes could reuse it rather than grow a
-- second copy of the same twelve taps.
local function pc_open_storage(G)
  local ok, why = pc_open_menu(G)
  if not ok then return false, why end
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

-- ...and the same door into the BOXES. The row is named for whoever owns
-- it, which changes when you meet Bill (bills_pc.asm gates on
-- EVENT_MET_BILL), so match on the suffix and exclude the player's own.
local function pc_open_boxes(G)
  local ok, why = pc_open_menu(G)
  if not ok then return false, why end
  if not ui_row_labelled(G, "WITHDRAW") then
    local name = ((G.save or {}).player or {}).name
    local mine = name and name ~= "" and (name:upper() .. "'S PC") or nil
    local want
    for i, r in ipairs(ui_rows(G) or {}) do
      local lab = tostring(r.label or r.value or ""):upper()
      if lab:find("'S PC") and not (mine and lab:find(mine, 1, true)) then
        want = i break
      end
    end
    if not want then
      ui_back_out(G)
      return false, "no Pokemon-storage row on the PC menu"
    end
    ui_cursor_to(G, "index", want)
    U.tap(G, "a"); U.wait(10)
  end
  if not ui_row_labelled(G, "WITHDRAW") then
    ui_back_out(G); return false, "the boxes never opened"
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

-- THE BOXES, WHICH WERE READ-ONLY UNTIL NOW (user, 2026-08-17).
-- obs.pc_mons listed what was in storage and no op could touch it: mons
-- went in exactly one way, by being caught with a full party (this engine
-- auto-deposits rather than refusing the catch), and never came out. That
-- made "the party holds a WATER type" UNSATISFIABLE rather than merely
-- hard the moment the right creature was boxed, which is the same shape
-- as the mode that did not exist. The harness was even telling the run to
-- do it: daycare_withdraw refuses with "there is nowhere to put X until
-- one is deposited in the PC", naming an action with no op behind it.
local function pc_change_box(G, want)
  local cur = tonumber(((G.save or {}).currentBox)) or 1
  if not want or want == cur then return true end
  local r = ui_row_labelled(G, "CHANGE BOX")
  if not r then return false, "no CHANGE BOX row" end
  ui_cursor_to(G, "index", r)
  U.tap(G, "a"); U.wait(8)
  -- rows read "  BOX  3" (a mark on the current one); find by number
  local want_i
  for i, row in ipairs(ui_rows(G) or {}) do
    if tostring(row.label or row.value or ""):match("BOX%s+0?" .. want
                                                    .. "%s*$") then
      want_i = i break
    end
  end
  if not want_i then ui_back_out(G); return false, "no BOX " .. want end
  ui_cursor_to(G, "index", want_i)
  U.tap(G, "a"); U.wait(10)
  for _ = 1, 8 do                        -- "BOX N selected" / save prompt
    local t = ui_top(G)
    if not (t and t.pages) then break end
    U.tap(G, "a"); U.wait(5)
  end
  if (tonumber(((G.save or {}).currentBox)) or 1) ~= want then
    return false, "the PC would not switch to BOX " .. want
  end
  return true
end

-- One driver for all three, because the menus are the same shape: pick the
-- action row, pick a Pokemon from the list it opens, then confirm. Only
-- the confirmation differs, and only for RELEASE.
local function pc_mon(G, c, row, pick)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  local ok, why = pc_open_boxes(G)
  if not ok then return false, why end
  if c.box then
    local moved, mwhy = pc_change_box(G, tonumber(c.box))
    if not moved then ui_back_out(G); return false, mwhy end
  end
  local r = ui_row_labelled(G, row)
  if not r then ui_back_out(G); return false, row .. " row missing" end
  ui_cursor_to(G, "index", r)
  U.tap(G, "a"); U.wait(8)
  if not ui_is_list(G) then
    -- an empty box answers with "What? There are no POKéMON here!"
    ui_back_out(G)
    return false, row .. ": no list opened (is the box empty?)"
  end
  local rows = ui_rows(G) or {}
  local want = tonumber(pick)
  if not want or want < 1 or want > #rows then
    ui_back_out(G)
    return false, ("%s: there is no #%s here — this list has %d"):format(
      row, tostring(pick), #rows)
  end
  local label = tostring(rows[want].label or rows[want].value or "")
  ui_cursor_to(G, "index", want)
  U.tap(G, "a"); U.wait(8)
  return true, label
end

-- Put party member N into the current box.
function OPS.pc_deposit(G, c)
  local n = tonumber(c.slot)
  local party = (G.save or {}).party or {}
  if not n then return false, "pc_deposit needs slot" end
  if #party <= 1 then
    return false, "that is your last Pokemon — the PC will not take it"
  end
  local before = #party
  local ok, label = pc_mon(G, c, "DEPOSIT", n)
  if not ok then return false, label end
  -- the per-mon submenu: DEPOSIT / STATS / CANCEL, action first
  ui_cursor_to(G, "index", 1)
  U.tap(G, "a"); U.wait(10)
  for _ = 1, 8 do
    local t = ui_top(G)
    if not (t and t.pages) then break end
    U.tap(G, "a"); U.wait(5)
  end
  ui_back_out(G)
  local after = #((G.save or {}).party or {})
  if after >= before then
    return false, "the deposit did not go through (party still " .. after
      .. ")"
  end
  return true, ("deposited %s — party is now %d"):format(label, after)
end

-- Take stored Pokemon #index out of box `box` (default: the current one).
function OPS.pc_withdraw(G, c)
  local n = tonumber(c.index)
  if not n then return false, "pc_withdraw needs index" end
  local party = (G.save or {}).party or {}
  if #party >= 6 then
    return false, "the party is full (6) — deposit one first "
      .. "({\"op\":\"pc_deposit\",\"slot\":N})"
  end
  local before = #party
  local ok, label = pc_mon(G, c, "WITHDRAW", n)
  if not ok then return false, label end
  ui_cursor_to(G, "index", 1)
  U.tap(G, "a"); U.wait(10)
  for _ = 1, 8 do
    local t = ui_top(G)
    if not (t and t.pages) then break end
    U.tap(G, "a"); U.wait(5)
  end
  ui_back_out(G)
  local after = #((G.save or {}).party or {})
  if after <= before then
    return false, "the withdrawal did not go through (party still " .. after
      .. ")"
  end
  return true, ("withdrew %s — party is now %d"):format(label, after)
end

-- Release stored Pokemon #index. IT IS GONE. There is no undo, no box it
-- moves to, and no way to catch that individual again.
--
-- THE HARNESS DOES NOT GET A VOTE (user, 2026-08-17: "cant tie its hands
-- even if it wants to make a bad decision"). So this is a real op and it
-- really works. What it does insist on is that the model name the species
-- it means, and that is not a veto: a mismatch is a WRONG FACT about
-- which row is which, not a bad decision, and refusing wrong facts is the
-- one thing the harness is for. Releasing the Pokemon you meant to
-- release is the model's call; releasing a different one because the list
-- shifted under an index is nobody's.
--
-- The engine's own prompt defaults to NO (defaultNo, bills_pc.asm), so
-- this must move the cursor to YES deliberately. A mashed A does nothing,
-- which is exactly right and is left as it is.
function OPS.pc_release(G, c)
  local n = tonumber(c.index)
  if not n then return false, "pc_release needs index" end
  if not c.species then
    return false, "pc_release needs species too — name the one you mean, "
      .. "so an index that has shifted cannot release the wrong Pokemon"
  end
  local want = tostring(c.species):upper():gsub("[^A-Z0-9]", "")
  local boxes = (G.save or {}).boxes or {}
  local bi = tonumber(c.box) or tonumber((G.save or {}).currentBox) or 1
  local mon = (boxes[bi] or {})[n]
  if not mon then
    return false, ("there is no #%d in BOX %d"):format(n, bi)
  end
  local have = tostring(mon.species or ""):upper():gsub("[^A-Z0-9]", "")
  if have ~= want then
    return false, ("#%d in BOX %d is a %s, not a %s — nothing was released")
      :format(n, bi, tostring(mon.species), tostring(c.species))
  end
  local before = #(boxes[bi] or {})
  local ok, label = pc_mon(G, c, "RELEASE", n)
  if not ok then return false, label end
  -- "Once released, X is gone forever. OK?" — a ChoiceBox pushed on top of
  -- the text once it finishes paging, with the cursor STARTING ON NO
  -- (defaultNo, bills_pc.asm). Ride the text with the harness's own
  -- press-until rather than a private loop: the first version of this was
  -- a hand-rolled copy of exactly that and it never saw the box.
  if not ui_press_until(G, ui_is_choice, "a", 20) then
    ui_back_out(G)
    return false, "the release confirmation never appeared"
  end
  -- YES is index 1. Nothing else in this file has had to move a cursor
  -- ONTO a destructive answer, and that asymmetry is the engine being
  -- careful rather than an accident: a mashed A here answers NO and the
  -- Pokemon lives. Left exactly as it is.
  ui_cursor_to(G, "index", 1)
  U.tap(G, "a"); U.wait(8)
  for _ = 1, 8 do                      -- "...was released outside. Bye X!"
    local t = ui_top(G)
    if not (t and t.pages) then break end
    U.tap(G, "a"); U.wait(5)
  end
  ui_back_out(G)
  local after = #(((G.save or {}).boxes or {})[bi] or {})
  if after >= before then
    return false, "the release did not go through (BOX " .. bi
      .. " still holds " .. after .. ")"
  end
  -- the box row prints a padded nickname ("AAAAAAAAAA :L12"); say the
  -- species and level plainly instead. This is the sentence that reports
  -- something irreversible, so it should read like one.
  return true, ("released the %s (L%s) from BOX %d — it is gone for good; "
                .. "BOX %d now holds %d"):format(
    tostring(mon.species), tostring(mon.level or "?"), bi, bi, after)
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
  -- RIDING IS ONE ACT, DOOR TO DOOR. Standing outside a lift, "take me to
  -- 3F" meant: warp into the car, press the panel, wait the fade, warp out
  -- — and a macro may hold only ONE map-changing op, so the model could
  -- never say it in one go. It re-derived the trip every round and lost
  -- the thread halfway, bouncing between the car and the floor it started
  -- on (user, watching Silph, then: "lets just do that"). A car has one
  -- doorway, one panel, and no choices between them; the only decision is
  -- WHICH FLOOR, which is the argument. So: if there is no panel where we
  -- stand, walk into the car first and carry on.
  local _lift_seen, _lift_why
  do
    local _ow0 = G.overworld
    local _md0 = _ow0 and _ow0.map and G.data and G.data.maps
                 and G.data.maps[_ow0.map.id]
    local _panel_here = false
    for _, sg in ipairs((_md0 and _md0.signs) or {}) do
      if tostring(sg.name or sg.text or ""):upper():find("ELEVATOR") then
        _panel_here = true
      end
    end
    if not _panel_here then
      for _, w in ipairs((_md0 and _md0.warps) or {}) do
        if tostring(w.destMap or ""):upper():find("ELEVATOR") then
          local _in = (G.overworld.map or {}).id
          _lift_seen = ("%d,%d"):format(w.x, w.y)
          local _ok, _why = OPS.use_warp(G, { x = w.x, y = w.y })
          if (G.overworld.map or {}).id ~= _in then break end
          _lift_why = _why or _lift_why
        end
      end
    end
  end
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
    -- A LIFT YOU CANNOT WALK TO IS NOT AN ABSENT LIFT. This said "no
    -- elevator on this map" on SILPH_CO_5F, which has one at 20,0 — the
    -- party was in a pocket that cannot reach it, the walk-in failed, and
    -- the message denied the lift existed. Say which it is.
    if _lift_seen then
      return false, ("this map HAS a lift — its door is at %s — but no walk "
        .. "from where you stand reaches it%s. Get to that door's ground "
        .. "first; from there this op rides door to door.")
        :format(_lift_seen, _lift_why and (" (" .. tostring(_lift_why) .. ")")
                            or "")
    end
    return false, "no elevator on this map — there is no lift panel where "
      .. "you stand and no door here leads into a car. This op rides a "
      .. "lift door to door: from outside it walks in, presses the floor "
      .. "and walks out onto that floor, so it only needs a lift to be "
      .. "somewhere on this map"
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
  -- EXACT FIRST, AND 1F IS NOT 11F. The substring fallback matched on
  -- every row and the LAST match won, so "1F" found 11F ("11F":find("1F")
  -- hits at position 2) — the op reported "rode to 1F", the car never
  -- left the eleventh floor, and walking out put the party back where it
  -- started. Watched live in Silph: ride 1F, walk out, arrive 11F, repeat.
  -- Keep the loose match for labels the panel spells differently, but only
  -- when nothing matches exactly, and take the FIRST such row, not the last.
  local idx, offer, loose = nil, {}, nil
  for i, it in ipairs(t.items) do
    local lab = tostring(it.label or ""):upper()
    offer[#offer + 1] = lab
    if lab == want then
      idx = idx or i
    elseif not loose and lab:find(want, 1, true) then
      loose = i
    end
  end
  idx = idx or loose
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
  local _carmap = (G.overworld.map or {}).id
  ui_cursor_to(G, "index", idx)
  U.tap(G, "a"); U.wait(10)
  for _ = 1, 60 do              -- ride the shake out
    if G.stack:top() == G.overworld then break end
    U.tap(G, "a"); U.wait(5)
  end
  -- ...AND PUT THE PANEL AWAY, VERIFIED. One back-out was assumed to be
  -- enough and was not: the ride ends with the floor list still up, so the
  -- op returned "rode to 1F" while the game sat in ui mode and the next
  -- walk-out could only fail with "not in overworld". The model worked it
  -- out and pressed B itself, which is a choice it should never have had
  -- to make — closing a panel after the lift has moved decides nothing.
  -- ...AND THE PANEL COMES BACK AFTER THE RIDE, A BEAT LATE. ui_back_out
  -- is a 400-tap B-masher, so nothing was refusing to close: the list was
  -- simply not up YET when the loop looked, it re-rendered a moment after
  -- the op returned, and the model spent a round pressing B itself. Let
  -- the car settle first, then close, then make sure it STAYS closed.
  -- ...AND IT COMES BACK LATER THAN 20 FRAMES. Watched again after that
  -- fix: ride, then use_warp answers "not in overworld (a box was up and
  -- would not close)", then a bare tap(b) clears it and the same warp
  -- works. So the list re-renders after the op has already looked twice.
  -- Watch it for a whole second, closing whatever appears, and only stop
  -- once the overworld has held for a stretch.
  -- ...AND ui_back_out CANNOT CLOSE THIS. It opens with
  --     if t == G.overworld or (t and (t.enemy or t.kind)) then return true
  -- and ListMenu.new sets `kind = opts.kind or title`, so every list menu
  -- is truthy-kind and the helper returns WITHOUT PRESSING ANYTHING. That
  -- is why three passes at this bug (wait 20, then wait 30, then watch for
  -- a second) all failed and a bare tap(b) always worked: nothing was ever
  -- being pressed. Press B here, and look at the stack rather than
  -- trusting a helper that treats this screen as none of its business.
  -- THE PANEL ARRIVES AFTER THE RIDE SETTLES, and every close loop so far
  -- broke before it got there: the overworld IS on top for a moment, the
  -- loop sees it, waits its 10 frames, breaks, and the list comes up
  -- afterwards — which is why the instrumented pass printed NOTHING while
  -- the very next op still answered "a box was up and would not close".
  -- Sit out the whole arrival before looking.
  -- IT TELLS YOU HOW LONG IT IS. The probe answered at last:
  --   [lift] pass 5 fade=true phase=pa frames=200 t=nil map=false
  -- a fade declaring 200 frames, while every budget I guessed came out at
  -- about that — so it cleared sometimes and not others, which is exactly
  -- how this behaved across six attempts. Read the number off the object
  -- rather than inventing one, and leave room after it.
  U.wait(20)
  for _i = 1, 40 do
    local _t = G.stack:top()
    if _t == G.overworld then
      U.wait(20)
      if G.stack:top() == G.overworld then break end
    elseif _is_fade(_t) then
      local _budget = (tonumber(_t.frames) or 120) + 90
      for _ = 1, math.ceil(_budget / 10) do
        if not _is_fade(G.stack:top()) then break end
        U.wait(10)
      end
    else
      U.tap(G, "b"); U.wait(10)
    end
  end
  -- ...AND THEN WALK OUT, BECAUSE THAT IS THE SAME INTENT. "Rode to 3F —
  -- you are still IN the car; walk out of its door" made a lift a
  -- THREE-op sequence (ride, close the panel, warp out), and a macro may
  -- hold only one map-changing op, so the model could never express it in
  -- one go and re-derived it every round: bouncing between the car and
  -- 11F, never completing the trip, and refusing the stairs because they
  -- go the wrong way. A car has ONE doorway and no choice in it — asking
  -- for a floor and arriving on it is a single act, the same way use_warp
  -- walks you to the tile before it opens the door.
  local _out_why
  if G.stack:top() == G.overworld then
    for _, w in ipairs((G.data and G.data.maps
                        and G.data.maps[(G.overworld.map or {}).id]
                        and G.data.maps[(G.overworld.map or {}).id].warps)
                       or {}) do
      local _ok, _why = OPS.use_warp(G, { x = w.x, y = w.y })
      _out_why = _why
      if _ok or (G.overworld.map or {}).id ~= _carmap then break end
    end
  end
  local _stuck = (G.stack:top() ~= G.overworld)
  -- ...AND NAME THE CAR'S OWN DOORS. "Walk out of its door" left the
  -- model reaching for the door it came in BY, which belongs to the floor
  -- it was standing on, not to the car: use_warp(13,0) on SILPH_CO_ELEVATOR
  -- with the car's doors at (1,3) and (2,3). Coordinates belong to one map
  -- and these are the ones on this one.
  local _mine = {}
  for _, w in ipairs((G.data and G.data.maps
                      and G.data.maps[(G.overworld.map or {}).id]
                      and G.data.maps[(G.overworld.map or {}).id].warps) or {}) do
    _mine[#_mine + 1] = ("(%d,%d)"):format(w.x, w.y)
  end
  local _here = (G.overworld.map or {}).id
  if _here ~= _carmap then
    return true, ("rode to %s and stepped out — you are on %s now. That "
      .. "panel offers %s")
      :format(tostring(offer[idx] or want), tostring(_here),
              table.concat(offer, ", "))
  end
  return true, ("rode to %s — you are still IN the car; walk out of %s to "
    .. "arrive. This panel offers %s%s")
    :format(tostring(offer[idx] or want),
            #_mine > 0 and ("its door " .. table.concat(_mine, " or "))
              or "its door",
            table.concat(offer, ", "),
            _stuck and (". A screen is STILL up that would not close — "
              .. "{\"op\":\"tap\",\"btn\":\"b\"} before walking out")
              or "")
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

-- Level-grind primitive: stand where this map's wilds spawn (grass; any
-- floor tile of a cave or tower) and pace until an encounter interrupts (or
-- the step budget runs out). The EXECUTOR fights
-- each battle with the subgoal's policy and re-sends this op — the same
-- battle-retry machinery as traversal — until the plan's done_when (a
-- level gate) holds. Decision-free: the model decides WHERE (which map)
-- and the plan decides UNTIL; walking onto wild ground is mechanics.
function OPS.grind(G, c)
  if not need_overworld(G) then
    return false, "not in overworld (a box was up and would not close)"
  end
  local Collision = require("src.world.Collision")
  local ow = G.overworld
  local p = ow.player
  local map = ow.map
  if not (map and map.isGrassCell) then return false, "no map" end
  -- WHERE A WILD CAN APPEAR, by the engine's own rule (OverworldController
  -- :3585): in grass; on water while surfing; or, on an INDOOR map with an
  -- encounter table whose tileset is not FOREST, on EVERY tile -- caves,
  -- towers, the Mansion, the Power Plant. grind only knew grass, so in Rock
  -- Tunnel it said "no reachable grass on this map" while every floor tile
  -- there spawns Zubat.
  local indoor = G.data and G.data.field and G.data.field.indoorEncounters
  local encDef = G.data and G.data.encounters and G.data.encounters[map.id]
  local md = map.def or {}
  local anywhere = encDef and indoor and md.index and indoor.firstIndoorMap
    and md.index >= indoor.firstIndoorMap
    and md.tileset ~= indoor.excludedTileset
  local afloat = p.surfing and encDef and encDef.water and map.isWaterCell
  -- GRIND ON THE WATER, OPT-IN. Water holds its own encounter table
  -- (encDef.water) and its own species — the point of pacing a lake
  -- rather than the grass beside it — but you have to be ON it, and
  -- getting on it is a decision (different wilds, a different place to be
  -- dumped). `surf=true` says do it; the mount is walk_to's mechanic.
  if c.surf and not p.surfing and encDef and encDef.water then
    local knows = false
    for _, mon in ipairs((G.save or {}).party or {}) do
      for _, mv in ipairs(mon.moves or {}) do
        if tostring(type(mv) == "table" and mv.id or mv) == "SURF" then
          knows = true
        end
      end
    end
    if not knows then
      return false, "no party Pokemon knows SURF, so the water here cannot "
        .. "be paced"
    end
    local reach = warp_reach(G) or {}
    local bx, by, bland, bd
    for k in pairs(reach) do
      local sx, sy = k:match("^(-?%d+),(-?%d+)$")
      sx, sy = tonumber(sx), tonumber(sy)
      for _, d in pairs(DIRS) do
        local wx, wy = sx + d[1], sy + d[2]
        if map.isWaterCell and map:inBounds(wx, wy)
           and map:isWaterCell(wx, wy) then
          local dd = math.abs(wx - p.cellX) + math.abs(wy - p.cellY)
          if not bd or dd < bd then
            bd, bx, by, bland = dd, wx, wy, { sx, sy }
          end
        end
      end
    end
    if not bx then
      return false, "there is no water on this map to pace"
    end
    OPS.walk_to(G, { x = bland[1], y = bland[2], max_steps = 200 })
    local ok2, why2 = OPS.field_move(G, { move = "SURF", x = bx, y = by })
    if not ok2 then
      return false, "could not get onto the water: " .. tostring(why2)
    end
    afloat = p.surfing and encDef.water and map.isWaterCell
  end
  -- (never onto a warp tile: a cave's ladders and mouths are floor too, and
  -- pacing across one would leave the map mid-grind)
  local warp_at = {}
  for _, w in ipairs(md.warps or {}) do warp_at[w.x .. "," .. w.y] = true end
  for k in pairs(trigger_cells(G)) do warp_at[k] = true end   -- nor script tiles
  local function enc_cell(x, y)
    if not map:inBounds(x, y) then return false end
    if anywhere then
      return map:isWalkableCell(x, y) and not warp_at[x .. "," .. y]
    end
    if afloat and map:isWaterCell(x, y) then return true end
    return map:isGrassCell(x, y)
  end
  if not encDef then
    return false, "no wild Pokemon live on this map (no grass, and not a "
      .. "cave or tower floor that spawns them)"
  end
  local ground = anywhere and "the floor" or (afloat and "the water" or "grass")
  local function dirname_of(d)
    return (d[1] == 0 and (d[2] < 0 and "up" or "down"))
      or (d[1] < 0 and "left" or "right")
  end
  -- stand where wilds spawn: BFS to the nearest such cell if not on one
  if not enc_cell(p.cellX, p.cellY) then
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
            if enc_cell(nx, ny) then gx, gy = nx, ny break end
            queue[#queue + 1] = { x = nx, y = ny }
          end
        end
      end
    end
    if not gx then
      -- "NO REACHABLE GRASS" IS TWO DIFFERENT FACTS. Route 15 has grass
      -- (Oddish, Ditto, Venonat) and the run was standing in a 14-cell
      -- pocket west of the gate that has none — the message read as "this
      -- map has no grass" and sent it back across Kanto for a patch it was
      -- standing one building away from. Say which it is; the map is on
      -- screen, the reachable set is ours.
      local any_ground, any_water = false, false
      local W2, H2 = map_dims_cells(G)
      for yy = 0, math.max(0, H2 - 1) do
        for xx = 0, math.max(0, W2 - 1) do
          if not any_ground and map:isGrassCell(xx, yy) then any_ground = true end
          if not any_water and map.isWaterCell and map:isWaterCell(xx, yy) then
            any_water = true
          end
        end
      end
      local extra = ""
      if any_water and encDef.water then
        extra = " There IS water on this map with its own wild Pokemon: "
          .. "{\"op\":\"grind\",\"surf\":true} paces it if a party "
          .. "Pokemon knows SURF."
      end
      if any_ground then
        return false, ("this map HAS " .. ground .. ", but none of it is "
          .. "reachable from where you stand — the part of the map you are "
          .. "in has none, so the walking to do is toward the rest of it."
          .. extra)
      end
      return false, "no " .. ground .. " anywhere on this map." .. extra
    end
    OPS.walk_to(G, { x = gx, y = gy, max_steps = c.max_steps or 200 })
    if G.stack:top() ~= ow then return true, "battle en route to " .. ground end
    if not enc_cell(p.cellX, p.cellY) then
      return false, "couldn't reach the " .. ground
    end
  end
  -- pace: step between adjacent spawning cells (each step rolls the wild RNG)
  local BACK = { left = "right", right = "left", up = "down", down = "up" }
  for _ = 1, (c.steps or 80) do
    if G.stack:top() ~= ow then return true, "encounter" end
    local moved = false
    for _, dn in ipairs({ "left", "right", "up", "down" }) do
      local d = DIRS[dn]
      if enc_cell(p.cellX + d[1], p.cellY + d[2])
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
      if not moved then return false, "boxed in on the " .. ground end
    end
  end
  if G.stack:top() ~= ow then return true, "encounter" end
  return true, "paced without an encounter (re-send to keep grinding)"
end

-- List-menu navigation: any stack state exposing a numeric cursor `index`.
-- Moves the cursor to c.index, then A (or just positions with c.press=false).
function OPS.menu(G, c)
  local no = hands_off(G)
  if no then return false, no end
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
    -- SAY WHAT THE SCREEN SAID. Against the tower's GHOST, FIGHT does not
    -- open the move list: the game prints "<mon> is too scared to move!"
    -- and the turn passes. "no moveSelect (disabled/struggle?)" was a
    -- guess about the cause; the sentence on screen is the fact.
    local cur = b.current or (b.queue and b.queue[1])
    local said = cur and type(cur) == "table" and cur.text
    if type(said) == "string" and said ~= "" then
      return false, "no move list opened — the screen says: \""
        .. said:gsub("\n", " ") .. "\""
    end
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
    -- A LEVEL-UP MOVE LIST IS NOT TURN TEXT. Mashing A through it answers
    -- "delete an older move?" with the cursor's YES and then forgets
    -- whichever move the cursor rests on -- slot 1 -- a decision the
    -- harness has no business making. Stop here; the executor puts the
    -- list to the model.
    local t = G.stack:top()
    if t and t.screenId == "MoveLearnMenu" then
      return true, "a Pokemon is trying to learn a move — the choice is on screen"
    end
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
    -- ITEM_x_y is the harness's own name for an item lying at x,y (see
    -- observe: contents are never emitted); pressing it is pressing that
    -- tile. The map's own object names still resolve below, so a macro
    -- distilled before the rename keeps replaying.
    local ix, iy = tostring(c.name):match("^ITEM_(%d+)_(%d+)$")
    if ix then
      tx, ty = tonumber(ix), tonumber(iy)
      -- ...BUT ONLY ON THE MAP THAT NAME CAME FROM. ITEM_x_y names a ball
      -- by where it lies, so the same name exists on dozens of floors and
      -- the op quietly became "press tile (8,3) wherever you happen to be"
      -- — pressed in Fuchsia City for an item in the Warden's House, and
      -- answered with a pathing failure that says nothing about the mixup.
      local here_item = false
      for _, npc in ipairs(ow.npcs or {}) do
        local d2 = npc.def or {}
        if npc.cellX == tx and npc.cellY == ty
           and ((d2.name or ""):find("POKE_BALL") or d2.item) then
          here_item = true
        end
      end
      if not here_item then
        return false, ("no item lies at (%d,%d) on %s — an ITEM_x_y name "
          .. "means \"the ball at those coordinates on THAT map\", so it "
          .. "only means something on the map you saw it. Go to that map "
          .. "first (use_warp/go take map=), or press a tile here with "
          .. "{\"op\":\"interact\",\"x\":N,\"y\":N}.")
          :format(tx, ty, tostring((ow.map or {}).id))
      end
    end
    for _, npc in ipairs(ow.npcs or {}) do
      if not tx and (npc.def or {}).name == c.name then
        tx, ty = npc.cellX, npc.cellY
      end
    end
    if not tx then
      for _, f in ipairs(map_fixtures(G, ((ow.map or {}).id))) do
        if f.name == c.name then
          tx, ty, want_facing = f.x, f.y, f.facing
        end
      end
    end
    -- SIGNS, BY THE NAME THE OBSERVATION GAVE THEM. observe() lists every
    -- md.signs entry in obs.map.objects as kind "sign" under
    -- `sg.name or sg.text or SIGN_x_y`, and the untouched-things line then
    -- tells the model to press A on it -- but this lookup searched npcs and
    -- fixtures only, so every such press came back "not visible": 1,726
    -- failures in the journals and not one success, ever. A failed press
    -- retracts the touch, so the sign stayed "never touched" and was
    -- re-offered every round, and after three goes the failed-3x guard
    -- refused it. Route signs are the pamphlet tier made literal
    -- ("ROUTE 1 -- PALLET TOWN / VIRIDIAN CITY"); the engine reads one from
    -- any adjacent cell you face (OverworldController:interact ->
    -- map:signAtCell(fx, fy)), so no facing constraint is needed.
    if not tx then
      -- the same table observe() reads them from
      local md = ow.map and G.data and G.data.maps and G.data.maps[ow.map.id]
      for _, sg in ipairs((md and md.signs) or {}) do
        local nm = sg.name or sg.text or ("SIGN_" .. tostring(sg.x) .. "_"
                                          .. tostring(sg.y))
        if nm == c.name then tx, ty = sg.x, sg.y break end
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
  -- REACHING PAST A SPINNER. On an arrow-tile floor the only stand beside
  -- a thing can be an arrow: walk_to refuses to end on one (you arrive and
  -- are slid away), and adjacent_reachable counts it, so the observation
  -- said "reachable" while every walk said "no path" (ROCKET_HIDEOUT_B2F
  -- item at 3,21, five rounds). The engine reads the tile you FACE, so a
  -- press from the far side of the arrow is impossible — but stepping ON
  -- the arrow slides you, and gen 1's slide stops when it meets a wall,
  -- which is how the floor is meant to be crossed. Say so plainly rather
  -- than reporting a pathing failure.
  local spin_only = nil
  do
    local sp = G.data and G.data.field and G.data.field.spinners
               and G.data.field.spinners[(ow.map or {}).id]
    if sp then
      local function is_spin(x, y)
        for _, e in ipairs(sp) do
          if e.x == x and e.y == y then return true end
        end
        return false
      end
      local free = false
      for _, a in ipairs({ {tx, ty + 1}, {tx, ty - 1},
                           {tx - 1, ty}, {tx + 1, ty} }) do
        if ow.map.isWalkableCell and ow.map:isWalkableCell(a[1], a[2])
           and not is_spin(a[1], a[2]) then free = true end
      end
      if not free then spin_only = true end
    end
  end
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
  local function build_adj(tx, ty)
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
    return adj
  end
  local adj = build_adj(tx, ty)
  -- A PERSON WHO WANDERS IS NOT WHERE THEY WERE. The target's cell was
  -- read once, up top; by the time the walk arrived beside that cell a
  -- pacing NPC had often stepped off it, the press faced empty floor, and
  -- four retries re-walked to the same stale spot. Re-read a named
  -- person's cell before every approach and every press.
  local npc_named = nil
  if c.name then
    for _, npc in ipairs(ow.npcs or {}) do
      if (npc.def or {}).name == c.name then npc_named = npc end
    end
  end
  local function refresh_target()
    if npc_named and npc_named.cellX and
       (npc_named.cellX ~= tx or npc_named.cellY ~= ty) then
      tx, ty = npc_named.cellX, npc_named.cellY
      adj = build_adj(tx, ty)
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
      -- ...AND AT PC STORAGE, AND WITHOUT BEING ASKED. This was opt-in,
      -- so only buy and sell ever got handed the counter and a bare
      -- interact still pressed into it — which is how answer="yes" rode
      -- fifteen purchase confirmations. An op that means to DRIVE one of
      -- these passes stop_at_menu and gets it silently; anyone else is
      -- told which ops work here and left outside it.
      do
        local _kind = ui_transaction_up(G)
        -- The PC's own top-level list is not a transaction screen — it
        -- only navigates — but a bare interact still must not A-mash a
        -- choice out of it. Mashing picked "SOMEONE'S PC" because that is
        -- where the cursor sat, dived into WITHDRAW, met an empty box,
        -- and backed all the way out: 40-odd rounds of
        -- `it said: "What? There are no POKéMON here!"` and the screen
        -- never once still open when the observation was taken.
        local _pc = (not _kind) and ui_row_labelled(G, "'S PC") and true
        if _kind or _pc then
          if c.stop_at_menu then return true end
          -- LEAVE IT OPEN. Closing it was the bug: a subgoal conditioned
          -- on {"screen":"BoxMenu"} can never be satisfied if the harness
          -- shuts the screen before the observation is taken, and that is
          -- the very predicate added to make "access the PC" sayable.
          -- need_overworld backs out for whatever comes next, so nothing
          -- is stranded.
          if _pc then
            -- NUMBER THEM. The op addresses rows by index and the
            -- first version of this listed them unnumbered, so the model
            -- had to guess which position was which: told "SOMEONE'S PC,
            -- AAAAAAA's PC, PROF.OAK's PC, LOG OFF" it asked for index 2
            -- while its subgoal wanted the box menu at 1. The order is on
            -- the screen; withholding the numbering is the harness
            -- knowing the mapping and not saying it.
            local labels = {}
            for i, r in ipairs(ui_rows(G) or {}) do
              labels[#labels + 1] = ("%d=%s"):format(
                i, tostring(r.label or r.value or "?"))
            end
            return true, ("the PC is on. Its menu offers: %s. Choose one "
              .. "with {\"op\":\"menu\",\"index\":N} — the storage "
              .. "screens behind it are driven by store_item / "
              .. "retrieve_item / pc_deposit / pc_withdraw / pc_release, "
              .. "not by pressing keys"):format(table.concat(labels, ", "))
          end
          -- WHAT THEY SAID COMES FIRST. An earlier version of this
          -- prepended recent_text and the restructure for the PC case
          -- dropped it on the shop branch — so a subgoal whose whole
          -- purpose was "talk to the clerk and find out" got 392
          -- characters of guard notice and not one word of the clerk,
          -- four rounds running. The guard exists to stop the harness
          -- hiding things; hiding the answer inside it is the same fault
          -- wearing the fix's clothes.
          local said = recent_text
          return true, ((said and said ~= "")
                        and ("\"" .. said .. "\" — ") or "")
                       .. hands_off(G)
        end
      end
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
          .. "one — backed out (which the game takes as a no). To hand "
          .. "over the Pokemon in party slot N, re-send this same interact "
          .. "with slot=N (an in-game trade works this way; the day care "
          .. "has its own daycare_deposit slot=N)."
      end
      -- ...AND WHEN THE OP DID NAME ONE, PICK THAT ONE. With slot= set the
      -- picker fell through to the generic "tap A", which selects whoever
      -- the cursor rests on -- slot 1 -- so the named Pokemon was never
      -- the one handed over. Same cursor walk daycare_deposit uses.
      if t and t.screenId == "PartyMenu" and c.slot then
        local want = math.floor(tonumber(c.slot) or 0)
        local n = #((G.save or {}).party or {})
        if want < 1 or want > n then
          U.tap(G, "b"); U.wait(6)
          for _ = 1, 20 do
            if G.stack:top() == ow then break end
            U.tap(G, "b"); U.wait(4)
          end
          return false, ("it asked WHICH POKEMON and slot=%s is not a party "
            .. "slot (the party has %d) — backed out"):format(
              tostring(c.slot), n)
        end
        ui_cursor_to(G, "index", want)
        U.tap(G, "a"); U.wait(8)
        -- the dialog that follows (a confirm, the trade, or a refusal in
        -- words) is read like any other page below, on the fresh top
        t = G.stack:top()
      end
      -- ANY OTHER LIST IS A CHOICE, AND CHOICES ARE THE MODEL'S. Every
      -- screen not named above fell through to "tap A", and a ListMenu
      -- that stays open after each pick turns that into a purchase loop:
      -- the Celadon roof VENDING MACHINE is a sign whose script pushes
      -- one (data/scripts/story4.lua vendingMachine), and A on it buys a
      -- FRESH WATER, dismisses "popped out!", and buys again until the
      -- money is gone. Signs became pressable by name today, and the room
      -- sweep presses every untouched sign, so this was about to fire
      -- unasked. Same rule as the PC and the elevator panel: leave the
      -- menu OPEN, number the rows as they read on screen, and say how to
      -- choose. Nothing is bought, ridden or picked by the harness.
      -- (`elevator` calls interact with floor= set and then reads the
      -- FLOOR menu itself, so it wants exactly this: the menu still up.)
      if t and t.items and t.items[1] then
        local who = c.name or (c.x and ("%s,%s"):format(tostring(c.x),
                                                        tostring(c.y)))
                    or "?"
        local labels = {}
        for i, r in ipairs(t.items) do
          labels[#labels + 1] = ("%d=%s"):format(
            i, tostring(r.label or r.value or "?"))
        end
        local title = t.title and (" (" .. tostring(t.title) .. ")") or ""
        return true, ("%s opened a menu%s: %s. Nothing was chosen and it "
          .. "is left OPEN. Pick a row with {\"op\":\"menu\","
          .. "\"index\":N}, or {\"op\":\"tap\",\"btn\":\"b\"} to "
          .. "close it; the next overworld op closes it anyway.")
          :format(who, title, table.concat(labels, ", "))
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
  -- A BATTLE ON THE WAY IS NOT PENDING TEXT. The clear-text loop below
  -- taps A at whatever is on top; with a wild encounter up from the
  -- approach walk that was twelve A presses INTO THE BATTLE MENU before
  -- "stuck in a menu/dialog" came back. Hand a battle straight back to
  -- the executor, which fights it and re-sends the interact.
  local function in_fight()
    local t = G.stack:top()
    return t and t ~= ow and (t.enemy or t.kind) and true or false
  end
  for _ = 1, 4 do
    if in_fight() then return true, "battle started on the way" end
    for _ = 1, 12 do          -- clear any pending text
      if G.stack:top() == ow or in_fight() then break end
      U.tap(G, "a"); U.wait(3)
    end
    if in_fight() then return true, "battle started on the way" end
    if G.stack:top() ~= ow then return false, "stuck in a menu/dialog" end
    refresh_target()
    if press_from_adjacent() then return settle_dialog() end
    for _, a in ipairs(adj) do
      OPS.walk_to(G, { x = a[1], y = a[2], max_steps = 60 })
      if G.stack:top() ~= ow then break end       -- a battle or a script
      refresh_target()                             -- they may have moved
      if press_from_adjacent() then return settle_dialog() end
      if p.cellX == a[1] and p.cellY == a[2] then
        break
      end
    end
    if in_fight() then return true, "battle started on the way" end
    if G.stack:top() == ow then
      refresh_target()
      if press_from_adjacent() then return settle_dialog() end
    end
  end
  if spin_only then
    return false, "every tile beside that is an ARROW TILE — you cannot "
      .. "stand on one (it slides you the moment you step on), so nothing "
      .. "here can be pressed from beside it. This floor is crossed by "
      .. "RIDING the arrows: step on one and see where it puts you."
  end
  -- WHO IS STANDING WHERE YOU WOULD HAVE TO STAND. "No reachable tile
  -- adjacent" is true and says nothing: the Warden's House RARE_CANDY has
  -- a BOULDER parked on the one approach, which is on screen and was never
  -- mentioned, so the run read a pathing failure and tried again. Name
  -- whatever occupies the four tiles around it; what to do about a boulder
  -- (or a person, or a bush) stays the model's.
  do
    local around = {}
    for _, a in ipairs({ {tx, ty + 1}, {tx, ty - 1},
                         {tx - 1, ty}, {tx + 1, ty} }) do
      for _, npc in ipairs(ow.npcs or {}) do
        if npc.cellX == a[1] and npc.cellY == a[2] then
          around[#around + 1] = ("%s at (%d,%d)"):format(
            tostring((npc.def or {}).name or "something"), a[1], a[2])
        end
      end
      for _, f in ipairs(map_fixtures(G, ((ow.map or {}).id)) or {}) do
        if f.x == a[1] and f.y == a[2] then
          around[#around + 1] = ("%s at (%d,%d)"):format(
            tostring(f.name or "something"), a[1], a[2])
        end
      end
      if cut_bush_at(G, a[1], a[2]) then
        around[#around + 1] = ("CUT_TREE (a bush CUT clears) at (%d,%d)")
          :format(a[1], a[2])
      end
    end
    if #around > 0 then
      return false, "no reachable tile adjacent to target — standing on "
        .. "the tiles you would press from: " .. table.concat(around, ", ")
    end
  end
  do
    local _b = bushes_blocking(G, tx, ty, warp_reach(G) or {})
    if #_b > 0 then
      return false, "no reachable tile adjacent to target — standing "
        .. "between the ground you can reach and the rest of this map: "
        .. table.concat(_b, ", ")
    end
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
