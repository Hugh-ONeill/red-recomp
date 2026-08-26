"""Every room reachable gets a sentence before any room gets a second
(2026-08-26: Celadon City's chatter ate all 8 told-elsewhere lines and the
Mart's "ROOFTOP SQUARE: VENDING MACHINES" directory line — one leg further,
and the answer to the thirsty guard — never appeared)."""
import sys
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))
import executor as E

ex = E.Executor.__new__(E.Executor)
ex.hints = {
    "CELADON_CITY|2,1": [f"CHATTER_{i}: line number {i} about slots" for i in range(9)],
    "CELADON_MART_1F|1,1": ["TEXT_DIRECTORY: 5F: DRUG STORE ROOFTOP SQUARE: VENDING MACHINES"],
    "ROUTE_7|0,2": ["A_GUY: the road east is closed"],
}
ex._dated = lambda rg, l, obs: l
ex._route = lambda a, b: {"CELADON_CITY|2,1": [1, 2],
                          "CELADON_MART_1F|1,1": [1, 2, 3],
                          "ROUTE_7|0,2": [1, 2, 3, 4]}.get(b)

here = "ROUTE_7_GATE|0,3"
said_away = []
for _rg, _lines in (ex.hints or {}).items():
    if _rg == here or not _lines:
        continue
    _p = ex._route(here, _rg)
    if _p is None:
        continue
    said_away.append((len(_p), _rg, list(_lines)))
said_away.sort(key=lambda t: (t[0], t[1]))
_body, _round = [], 0
while len(_body) < 14:
    _added = False
    for _n, _rg, _ls in said_away:
        if _round < len(_ls):
            _body.append(f"  ({_rg}, {_n} leg(s) away) {ex._dated(_rg, _ls[_round], None)}")
            _added = True
            if len(_body) >= 14:
                break
    if not _added:
        break
    _round += 1
_body = _body[:14]
text = "\n".join(_body)

ck("the nearest room still leads", "CELADON_CITY" in _body[0])
ck("the farther room's one sentence survives", "ROOFTOP SQUARE: VENDING MACHINES" in text)
ck("...and so does the farthest room's", "the road east is closed" in text)
ck("every room appears before any room repeats",
   all(r in "\n".join(_body[:3]) for r in ("CELADON_CITY", "CELADON_MART_1F", "ROUTE_7|0,2")))
ck("the budget is still bounded", len(_body) <= 14)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
