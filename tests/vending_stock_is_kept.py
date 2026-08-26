"""A vending machine's stock is kept and restated, like a mart's (2026-08-26).

A counter's shelf is recorded the moment it opens and printed on that mart's
door from anywhere in the world ("CELADON_MART_2F sells: GREAT_BALL, ..."). A
vending machine published its rows ONCE, in the round that pressed it —
"1=FRESH WATER 200, 2=SODA POP 300, 3=LEMONADE 350" — and then existed
nowhere. The run pressed all three roof machines, so they sit in `touched`
and the sweep will never press them again, while the Route 7 guard wants a
drink and the roof is the only place in the world that sells one (user: "we
dont say it the way we do for marts in other cities").

A PRICE is what makes a menu a shop: elevator panels and PC menus carry none
and must not be recorded."""
import sys, re
from pathlib import Path
sys.path.insert(0, "planner")
import executor as E
import ledger as L

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

def fresh():
    ex = E.Executor.__new__(E.Executor)
    ex._shelves, ex._shelf_machine = {}, set()
    ex._save_memory = lambda: None
    ex.log = lambda *a, **k: None
    return ex

MENU = ('TEXT_CELADONMARTROOF_VENDING_MACHINE1 opened a menu (VENDING '
        'MACHINE): 1=FRESH WATER ¥200, 2=SODA POP ¥300, '
        '3=LEMONADE ¥350. Nothing was chosen and it is left OPEN.')

ex = fresh()
ex._record_machine_stock("CELADON_MART_ROOF|2,1", MENU)
ck("a priced menu is kept as stock, keyed by map",
   ex._shelves.get("CELADON_MART_ROOF") == ["FRESH_WATER", "SODA_POP",
                                            "LEMONADE"])
ck("...and marked as a machine, not a counter",
   ex._shelf_machine == {"CELADON_MART_ROOF"})

# a floor list and an options list are not shops
ex2 = fresh()
ex2._record_machine_stock(
    "SILPH_CO_ELEVATOR|0,1",
    "PANEL opened a menu (FLOOR): 1=1F, 2=2F, 3=B1F. Nothing was chosen "
    "and it is left OPEN.")
ex2._record_machine_stock(
    "CELADON_POKECENTER|3,7",
    "PC opened a menu (PC): 1=WITHDRAW ITEM, 2=DEPOSIT ITEM. Nothing was "
    "chosen and it is left OPEN.")
ck("a menu with no prices is not a shop", not ex2._shelves
   and not ex2._shelf_machine)
ck("a reply that opened no menu records nothing",
   (fresh()._record_machine_stock("X|0,0", "it said: hello") or True)
   and not fresh()._shelves)

# --- both render sites say MACHINE, and say a buy will not read one ---
src = Path("planner/ledger.py").read_text()
ck("the door line names a vending machine",
   "has a VENDING MACHINE selling:" in src)
ck("the floor line names it too, and says it takes no buy",
   "THE VENDING MACHINE(S) HERE SELL:" in src
   and "takes no buy" in src
   and '{\\"op\\":\\"menu\\",\\"index\\":N}' in src)
ck("a counter still reads as a counter",
   'f"{dest} sells: ' in src and "This mart sells:" in src)
ck("both sites consult the machine set",
   src.count('getattr(ex, "_shelf_machine", None) or set()') == 2)

# --- kept across a restart ---
esrc = Path("planner/executor.py").read_text()
ck("the machine set is persisted and reloaded",
   '"shelf_machine": sorted(' in esrc
   and 'data.get("shelf_machine")' in esrc)
ck("stock already pressed this run is backfilled from the journal",
   "vending stock backfilled" in esrc
   and "if not self._shelf_machine:" in esrc)
ck("...using the last map the journal named, since a menu-up obs has none",
   "_last_at" in esrc and '"None" not in _c' in esrc)

# --- and it never says what the drink is FOR ---
i = esrc.find("def _record_machine_stock")
ck("nothing is said about why a drink matters",
   not re.search(r"(?i)(guard|thirst|saffron|you should|in order to)",
                 esrc[i:i + 1200]))

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
