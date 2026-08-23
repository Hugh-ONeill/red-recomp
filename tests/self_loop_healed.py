"""Coming out of a door outranks a step that did nothing.

A door stepped through that fires nothing is recorded "back here" -- honest
about that moment, and then permanent, because the reverse-edge writer only
ever filled an ABSENT entry.  Seafoam B2F's (25,11), the one ladder joining
the island's two halves, read "-> SEAFOAM_ISLANDS_B2F|23,10" -- itself --
while the walk UP it sat in the same ledger from the other side.  A ledger
that calls a real door a loop steers the model off it.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

B2F = "SEAFOAM_ISLANDS_B2F|23,10"
B1F = "SEAFOAM_ISLANDS_B1F|20,10"
KEY = "25,11"

def no_fire(explored, src, key):
    """A door stepped through that took you nowhere."""
    e = explored.setdefault(src, {}).setdefault(key, {"n": 0, "to": src})
    e["n"] += 1
    return e

def arrived_through(explored, dst, key, src):
    """The reverse-edge writer, as note_transition applies it."""
    back = explored.setdefault(dst, {})
    ex = back.get(key)
    if ex is not None and ex.get("to") == dst:
        ex["to"] = src                      # the fix
        return "healed"
    if key not in back:
        back[key] = {"to": src, "n": 0}
        return "learned"
    return "kept"

# the live sequence: a no-fire on B2F, then the walk up from B1F
ex = {}
no_fire(ex, B2F, KEY)
ck("a no-fire door records itself", ex[B2F][KEY]["to"] == B2F)
what = arrived_through(ex, B2F, KEY, B1F)
ck("arriving through it heals the self-loop", what == "healed")
ck("the door now says where it goes", ex[B2F][KEY]["to"] == B1F)
ck("the traversal count is untouched", ex[B2F][KEY]["n"] == 1)

# a door already known does NOT get rewritten by a later arrival
ex = {B2F: {KEY: {"to": "SOMEWHERE|1,1", "n": 3}}}
ck("a known destination is left alone",
   arrived_through(ex, B2F, KEY, B1F) == "kept"
   and ex[B2F][KEY]["to"] == "SOMEWHERE|1,1")

# and an absent one is still learned at n=0, as before
ex = {}
ck("an unseen door is learned by arriving",
   arrived_through(ex, B2F, KEY, B1F) == "learned"
   and ex[B2F][KEY] == {"to": B1F, "n": 0})

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
