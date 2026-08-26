"""A list that opened and was not picked from is not a spent press (2026-08-26).

Exactly the fossil rule, for the other kind of open box. `interact` on a
vending machine opens its rows and deliberately picks nothing — "Nothing was
chosen and it is left OPEN. Pick a row with {"op":"menu","index":N}" — and
that reply was recorded as a TRY. The escalation's round budget then ran out
on the very op that opened the menu, the next subgoal was "exit the department
store" so the model closed the box and left, and by the time it came back the
roof machines read as pressed, the ledger dropped them from "never pressed",
and its own summary hardened into "I have already checked the Celadon Mart
clerks and the roof vending machines without success" (user: "i guess it
believes it isnt there and is searching the game corner now")."""
import sys, re
from pathlib import Path
sys.path.insert(0, "planner")
import executor as E

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()

ck("the marker is matched from one place, like ASKING",
   E.LIST_OPEN == "Nothing was chosen and it is left OPEN"
   and src.count("LIST_OPEN = ") == 1)

def ex_with(det, ok=True):
    ex = E.Executor.__new__(E.Executor)
    ex._tried_objs, ex._shelves, ex._shelf_machine = {}, {}, set()
    ex._save_memory = lambda: None
    ex.log = lambda *a, **k: None
    ex._stamp_touch = lambda r: None
    ex._mark_touch = lambda *a: None
    res = ex._record_touch("CELADON_MART_ROOF|2,1", "VM1",
                           {"result": {"ok": ok, "detail": det}})
    return ex, res

MENU = ('VM1 opened a menu (VENDING MACHINE): 1=FRESH WATER ¥200, '
        '2=SODA POP ¥300. Nothing was chosen and it is left OPEN.')
ex, res = ex_with(MENU)
ck("a menu left open is not recorded as a touch",
   res is False and not ex._tried_objs)
ck("...but what it was offering IS kept",
   ex._shelves.get("CELADON_MART_ROOF") == ["FRESH_WATER", "SODA_POP"]
   and ex._shelf_machine == {"CELADON_MART_ROOF"})

ex2, res2 = ex_with("it said: welcome to the roof")
ck("an ordinary press is still a touch",
   res2 is True and "VM1" in ex2._tried_objs.get("CELADON_MART_ROOF|2,1", ()))

# --- the sweep says the thing is still open ---
ck("the sweep reports a list it could not pick from",
   "OPENED A LIST and " in src and "NOT recorded as done" in src
   and "listed_back" in src)
ck("...told separately from a thing that ASKED",
   "asked_back, listed_back = [], []" in src
   and "elif LIST_OPEN in _det:" in src)
ck("it names the op that picks a row",
   'f"{{\\"op\\":\\"menu\\",\\"index\\":N}} with the "' in src)

# --- ledgers written under the old rule are repaired ---
ck("presses already spent under the old rule are re-opened",
   "opened a list are open again" in src and "_unspent" in src)
ck("...under its OWN gate, not the vending store's",
   "if not self._shelf_machine or not self._lists_reopened:" in src
   and "self._lists_reopened = True" in src)
ck("...and that gate survives a restart",
   'data.get("lists_reopened")' in src and '"lists_reopened": bool(' in src)
ck("...keyed on the object the reply itself names",
   r'r"([A-Z0-9_]+) opened a (?:menu|list)"' in src)

# --- and it never says what to pick ---
i = src.find("LIST_OPEN = ")
ck("nothing is said about which row matters",
   not re.search(r"(?i)(fresh water is|you need|you should|the guard wants)",
                 "\n".join(l for l in src[i - 1400:i + 400].splitlines()
                           if not l.lstrip().startswith("#"))))

import ast
try:
    ast.parse(src); ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
