"""A heal is not a wipe, and PP is a battle limit.

`heal` reported "your party FAINTED mid-op (blackout): you respawned at
FUCHSIA_POKECENTER, party healed, position progress lost" -- in the same
breath as quoting the nurse's welcome -- about a party that had not fainted
(user: "not true, we didnt wipe").  Every clause of the test was also true
of walking in and asking.  The real signal is the one the state watch
already uses: a blackout HALVES YOUR MONEY.

And the party dump carries every move's PP, which the engine's field-move
gate never checks; reading {"id":"SURF","pp":0} off it, the run flew to
Fuchsia for PP it did not need and lost the shore it had crossed to.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

def is_blackout(op, before_map, after_map, healed, hp_grew, m0, m1):
    """The test as executor.py applies it."""
    respawn_like = (str(after_map).endswith("POKECENTER")
                    or after_map in ("REDS_HOUSE_1F", "PALLET_TOWN"))
    if not (before_map and after_map and before_map != after_map
            and respawn_like and op != "checkpoint_restore"):
        return False
    halved = (isinstance(m0, int) and isinstance(m1, int)
              and m0 > 0 and m1 == m0 // 2)
    return bool(healed and hp_grew and halved and op != "heal")

# the live false positive: walked in, asked, got healed, money untouched
ck("a voluntary heal is not a blackout",
   not is_blackout("heal", "ROUTE_20", "FUCHSIA_POKECENTER",
                   True, True, 57830, 57830))
# even if some other op lands you healed in a Center, money must have halved
ck("a Center arrival with money intact is not a blackout",
   not is_blackout("use_warp", "ROUTE_20", "FUCHSIA_POKECENTER",
                   True, True, 57830, 57830))
# a real wipe still reads as one
ck("a real wipe is still caught",
   is_blackout("walk_to", "ROUTE_20", "FUCHSIA_POKECENTER",
               True, True, 57830, 28915))
ck("a wipe during a grind is still caught",
   is_blackout("grind", "ROUTE_19", "FUCHSIA_POKECENTER",
               True, True, 400, 200))
# and heal never counts, even on the money signature
ck("heal is never called a faint",
   not is_blackout("heal", "ROUTE_20", "FUCHSIA_POKECENTER",
                   True, True, 400, 200))
ck("a checkpoint restore is still exempt",
   not is_blackout("checkpoint_restore", "ROUTE_20", "FUCHSIA_POKECENTER",
                   True, True, 400, 200))

# --- the PP note --------------------------------------------------------
from executor import model_view as _sanitise
def note_of(party):
    o = _sanitise({"party": party, "map": {"id": "ROUTE_20"}})
    return o.get("pp_note")

ck("a 0-PP move earns the note",
   bool(note_of([{"moves": [{"id": "SURF", "pp": 0}]}])))
ck("the note says PP is a battle limit",
   "BATTLE limit" in (note_of([{"moves": [{"id": "SURF", "pp": 0}]}]) or ""))
ck("a full-PP party gets no note",
   note_of([{"moves": [{"id": "SURF", "pp": 15}]}]) is None)
ck("an empty party gets no note", note_of([]) is None)
ck("flags are still stripped",
   "flags" not in _sanitise({"flags": ["EVENT_X"], "party": []}))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
