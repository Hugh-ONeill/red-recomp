#!/usr/bin/env python3
"""An in-game trade is one op: the model says who and which Pokemon, the
harness drives the offer, the pick and the exchange.

Through interact it cost three rounds by design: the first meeting of a
question refuses a preset answer so the model reads what it is agreeing
to; the second answers and picks the slot; the round between was the
model's detour (Vermilion, 2026-09-14: interact, then menu(1) with the
party picker left open at the round's end, then interact again). The leg
has already said what the trade is, so the daycare ops' shape applies
(user: "we might need to facilitate trades a little bit ... its niche but
might as well"). Everything it refuses is a fact the game would refuse on
anyway, in the person's own words; a traded Pokemon keeps its name.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "harness" / "shim.lua").read_text()
ex = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

i0 = sh.index("function OPS.trade(G, c)")
body = sh[i0:sh.index("\nfunction ", i0 + 10)]
ck("the op exists", True)
ck("it needs the overworld like every other op", "need_overworld(G)" in body)
ck("it needs the person's name", 'trade needs name=' in body)
ck("a slot the party does not have is refused before anything moves",
   "no party slot %d" in body and body.index("no party slot") < body.index("OPS.interact"))
ck("the dialogue is interact's own, with the question taken as read",
   'OPS.interact(G, { name = c.name, answer = "yes", slot = slot,' in body
   and "read_question = true" in body)
ck("...and interact's refusal is handed back in the person's words",
   "if not ok then return false, why end" in body)
ck("it sits through the exchange until the overworld is back",
   "if G.stack:top() == G.overworld then break end" in body and 'U.tap(G, "a")' in body)
ck("success is read off the party, not assumed",
   "if tostring(mon.species) ~= before[i] then got = mon break end" in body)
ck("...and names what was given, what came, and what it is called",
   'traded %s (slot %d) for %s L%s%s' in body and "got.nickname" in body
   and "a traded Pokemon keeps " in body and "the name it arrives with" in body)
ck("a trade that did not happen says so, with the words that stopped it",
   "the trade did not go through -- " in body)
ck("the dispatcher needs no registration: ops are looked up by name",
   "local op = OPS[cmd.op]" in sh)

ck("the vocabulary offers it beside the daycare ops",
   '{"op":"trade","name":"NAME","slot":N}' in ex
   and ex.index('{"op":"trade"') > ex.index('{"op":"daycare_withdraw"}'))
ck("...saying it is one op and what it refuses",
   "sits through the exchange, one op" in ex and "Refuses in their own words" in ex)
ck("...and that the name is kept", "keeps the name it arrives with" in ex)
ck("trade is not a map-changing op", '"trade"' not in ex.split("MAP_CHANGING_OPS = (", 1)[1].split(")", 1)[0])

if shutil.which("luac"):
    r = subprocess.run(["luac", "-p", str(ROOT / "harness" / "shim.lua")], capture_output=True, text=True)
    ck("shim.lua parses", r.returncode == 0, r.stderr[:200])

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
