"""A switch asks nothing it can take.

`answer` is only honoured for a question the run has already been SHOWN --
a guard added because a reflex "yes" rode along on 302 of 560 interacts and
boarded a level 40 CHARIZARD to the day-care man while trying to collect it.
That is right for anyone who can take something.  A Mansion switch statue
takes nothing and gives nothing; it flips wall blocks and asks "Press it?".
The run pressed one, was handed the question, answered next round, pressed
again, and EVENT_MANSION_SWITCH_ON stayed off through the whole exchange.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

SWITCH_TILE = 61

def defers(answer, seen, read_question, tile):
    """The guard as the shim now applies it."""
    is_switch = (tile == SWITCH_TILE)
    return bool(answer is not None and not seen and not read_question
                and not is_switch)

ck("a switch answers on the first press",
   not defers("yes", seen=False, read_question=False, tile=SWITCH_TILE))
ck("an unread NPC question is still deferred",
   defers("yes", seen=False, read_question=False, tile=5))
ck("a question already seen is still answered",
   not defers("yes", seen=True, read_question=False, tile=5))
ck("read_question still answers",
   not defers("yes", seen=False, read_question=True, tile=5))
ck("no answer given, nothing deferred",
   not defers(None, seen=False, read_question=False, tile=5))
ck("the day-care trade is still protected",
   defers("yes", seen=False, read_question=False, tile=17))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
