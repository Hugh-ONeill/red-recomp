"""push is a deed, so a place cannot witness it.

"Push the boulders in the Seafoam Islands to clear the path" ended on
{"player_at": {...}} -- standing near a spot -- and passed on attempt 1 with
not one boulder moved and not one EVENT_SEAFOAM*_BOULDER*_DOWN_HOLE set.
The DEED guard exists for exactly this and already says "end on what the
deed leaves behind -- an event flag, an item gained, a badge"; the verb
"push" was simply not in its list.  The {"flag": ...} predicate it points at
has been there all along (author.PREDICATES, pred_holds, ENGINE_FLAGS
validation) -- these checks pin that it still works, so nothing here is
mistaken for new.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

from executor import pred_holds
import author

OBS = {"map": {"id": "SEAFOAM_ISLANDS_B4F"},
       "flags": ["EVENT_BEAT_BROCK", "EVENT_SEAFOAM4_BOULDER1_DOWN_HOLE"]}

# the predicate that already existed, still behaving
ck("a set flag holds",
   pred_holds({"flag": "EVENT_SEAFOAM4_BOULDER1_DOWN_HOLE"}, OBS))
ck("an unset flag does not",
   not pred_holds({"flag": "EVENT_SEAFOAM4_BOULDER2_DOWN_HOLE"}, OBS))
ck("it combines with map",
   pred_holds({"map": "SEAFOAM_ISLANDS_B4F", "flag": "EVENT_BEAT_BROCK"}, OBS))
ck("a flagless observation satisfies nothing",
   not pred_holds({"flag": "EVENT_BEAT_BROCK"}, {"map": {"id": "X"}}))
ck("documented exactly once", list(author.PREDICATES).count("flag") == 1)
ck("the validator accepts it", "flag" in author.VALID_KEYS)

# the two things that changed
src = open("planner/author.py").read()
deed = src.split("DEED = (")[1].split(")")[0]
ck("push is a deed", '"push"' in deed)

# ...and player_at counts as a place, or the guard never fires for the
# shape that actually slipped through: "Push the boulders" ended on
# {"player_at": {"x":3,"y":14,"radius":2}} and passed with nothing pushed.
# the guard grew an exemption for a place never stood in, so the set
# it tests is no longer the first thing after "keys <= "
places = src.split("keys <= {")[1].split("}")[0]
ck("player_at is a place", '"player_at"' in places)
for k in ("map", "area", "no_battle", "party_healthy"):
    ck(f"{k} is still a place", f'"{k}"' in places)
ck("a real witness is NOT a place", '"flag"' not in places
   and '"has_item"' not in places and '"badge"' not in places)
for verb in ("defeat", "retrieve", "clear", "catch"):
    ck(f"{verb} is still a deed", f'"{verb}"' in deed)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
