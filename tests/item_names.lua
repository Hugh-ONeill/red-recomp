-- An item is identified by its NAME, not by its punctuation.
--
-- Run 4, in the Viridian mart, standing at the counter:
--
--   buy(item=POKEBALL,count=5): FAILED — POKEBALL is not sold here —
--   this mart sells: POKE_BALL, ANTIDOTE, PARLYZ_HEAL, BURN_HEAL
--
-- The shelf in that sentence has the thing on it. The bag row reads
-- "POKé BALL", the compiled id is POKE_BALL, the model wrote POKEBALL,
-- and seven separate ops each did their own `==` against the id. In buy
-- the refusal at least names the stock, so the run can recover in a
-- round. In the others it does not: `no POKEBALL in the bag`, with ten
-- of them in the bag. That is the harness stating a false FACT about the
-- world, which is the one thing CLAIM_RULES forbids outright.
--
-- WHAT IS DELIBERATELY NOT TESTED, because it is deliberately not built:
-- prefixes, substrings, edit distance, "did you mean". Buying, tossing
-- or selling the wrong object costs real money or a real item, and a
-- harness that picks the object for you has stopped facilitating the
-- decision and started making it. The rule is exact-modulo-punctuation
-- and the tests below pin both halves — that POKE BALL resolves, and
-- that BALL does not.
--
-- Reads the function out of the shim source, so there is one definition
-- and no copy here to drift from it. No emulator, no game, no model.

local SHIM = arg[1] or "harness/shim.lua"

local src = assert(io.open(SHIM)):read("a")
local block = src:match("(local function _item_key.-\n  return hit or name\nend)")
if not block then
  io.stderr:write("canon_item is not in " .. SHIM .. "\n")
  os.exit(1)
end
local canon = assert(load(block .. "\nreturn canon_item"))()

-- the real Viridian shelf, plus enough of the rest of the table to catch
-- a matcher that has started guessing
local G = { data = { items = {} } }
for _, id in ipairs({ "POKE_BALL", "GREAT_BALL", "MASTER_BALL", "POTION",
                      "SUPER_POTION", "ANTIDOTE", "PARLYZ_HEAL",
                      "BURN_HEAL", "S_S_TICKET", "TM_01", "TM_MEGA_PUNCH",
                      "HM_01", "FULL_RESTORE", "NUGGET" }) do
  G.data.items[id] = { price = 100 }
end

local CASES = {
  { "the exact id is handed straight back", "POKE_BALL", "POKE_BALL" },
  { "the spelling that failed in the mart resolves", "POKEBALL",
    "POKE_BALL" },
  { "so does the spelling ON THE SCREEN", "POKE BALL", "POKE_BALL" },
  { "case is not identity", "Poke Ball", "POKE_BALL" },
  { "nor is it for a plain one-word item", "Potion", "POTION" },
  { "a TM named the way the bag prints it", "TM01", "TM_01" },
  { "initials survive the fold", "SSTICKET", "S_S_TICKET" },
  { "a TM named by its MOVE is already an id", "TM_MEGA_PUNCH",
    "TM_MEGA_PUNCH" },

  -- the half that must NOT match
  { "a substring is not a name", "BALL", "BALL" },
  { "nor is a prefix", "POKE", "POKE" },
  { "nor is a word that merely appears in one", "HEAL", "HEAL" },
  { "an item this game does not have is left alone", "SITRUS_BERRY",
    "SITRUS_BERRY" },

  -- an item that exists but is not on THIS shelf must reach the shop
  -- code unchanged, so that "POTION is not sold here" — true in Viridian
  -- until the parcel is delivered, and the single most common refusal in
  -- the whole corpus — keeps being said
  { "a real item that this mart does not stock is unchanged", "POTION",
    "POTION" },

  { "nothing is nothing", nil, nil },
  { "empty is empty", "", "" },
}

local fails = 0
for _, c in ipairs(CASES) do
  local name, input, want = c[1], c[2], c[3]
  local got = canon(G, input)
  local ok = got == want
  print(("  %s  %s"):format(ok and "ok  " or "FAIL", name))
  if not ok then
    print(("          %s -> %s, want %s"):format(tostring(input),
                                                 tostring(got),
                                                 tostring(want)))
    fails = fails + 1
  end
end

-- TWO IDS THAT FOLD TOGETHER. Gen 1 has no such pair, but the rule has to
-- say what it does rather than rely on that: it hands the name back and
-- lets the op fail with its own message, because picking one of two real
-- items for the model is exactly the decision this must not make.
do
  local A = { data = { items = { POKE_BALL = {}, POKEBALL = {} } } }
  local got = canon(A, "poke ball")
  local ok = got == "poke ball"
  print(("  %s  two ids folding together is a hands-off, not a coin flip")
    :format(ok and "ok  " or "FAIL"))
  if not ok then
    print("          resolved to " .. tostring(got))
    fails = fails + 1
  end
  -- ...but an exact id still wins outright, even against that
  local ex = canon(A, "POKEBALL")
  local ok2 = ex == "POKEBALL"
  print(("  %s  an exact id wins before any folding happens")
    :format(ok2 and "ok  " or "FAIL"))
  if not ok2 then
    print("          resolved to " .. tostring(ex))
    fails = fails + 1
  end
end

print(("-"):rep(60))
if fails > 0 then
  print(("ITEM NAMES ARE BEING MATCHED WRONG: %d case(s)"):format(fails))
  os.exit(1)
end
print(("an item resolves by name, not by punctuation (%d checks)")
  :format(#CASES + 2))
