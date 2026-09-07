"""What a sweep's press heard is filed under the person who said it, and a
room you have walked the whole of has no unreached "rest".

Run 16, Pewter (2026-09-07).  The model wrote "I have already tried to enter
the gym and was turned away", and two lines on its page had told it so.
One was a hint filed as "sweep: Stop right there, kid! You're still light
years from facing BROCK!" -- the gym trainer's opening line, attributed to
the op because the hint recorder names the op when the step has no name.
The other was `go`'s note for a map with one walked part: "the rest of
PEWTER_GYM is ground you have SEEN but never STOOD ON ... explore finds no
way on from inside it" -- said of a small room whose one part was fully
seen and had no rest at all.  (User: "whats making it think its blocked?")
"""
import sys
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()
ck("the sweep remembers the last presser whose press put new words on screen",
   "self._last_press_name = None" in src
   and "self._last_press_name = name" in src
   and 'o2.get("last_text") or "") not in ("", _prev_text)' in src)
ck("the hint recorder files a sweep's quote under that presser",
   'who = self._last_press_name      # the sweep\'s presser' in src
   and 'op in ("sweep", "explore")' in src)
ck("a room with no seen ground ending anywhere is not said to have a rest never stood on",
   "Nothing you have seen of {want} lies outside that" in src
   and "so explore finds no way on" not in src)
ck("...while a map with unseen ground beyond the walked part still says so",
   'never STOOD ON, and {_fr_here} spot(s) where that' in src)
i = src.index("if _fr_here == 0:\n                _choice_note = (")
ck("the two wordings are chosen by whether any seen ground ends", i > 0
   and src.index("Nothing you have seen of {want} lies outside", i) < src.index("The rest of {want} is ground you have SEEN but", i))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
