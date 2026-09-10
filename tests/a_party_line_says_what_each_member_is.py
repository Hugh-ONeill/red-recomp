#!/usr/bin/env python3
"""A party member's types are on its own status screen, and on no page.

One button from the party menu shows them, and the observation has carried
them since the shim first read the party.  Both party lines printed
species, level and HP and dropped them.

Buying an evolution stone is the choice that needs them.  Run 16 stood on
Celadon Mart 4F with a Water, a Thunder and a Fire stone in front of it and
an EEVEE to spend one on, and bought WATER with a GYARADOS already in the
party (user, 2026-09-10: "id rather itdve got the thunder in this case
since we already have water with gyara").

Which type is worth having is the model's call.  What it is choosing
between was ours to say.  Synthetic: no game, no model.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

f = E._mon_types

ck("a dual type reads as both", f({"types": ["WATER", "FLYING"]}) == " (WATER/FLYING)")
# gen 1 stores a single-type Pokemon's type twice
ck("a single type is said once, not twice",
   f({"types": ["NORMAL", "NORMAL"]}) == " (NORMAL)", f({"types": ["NORMAL", "NORMAL"]}))
ck("...and once when the engine only gives one", f({"types": ["NORMAL"]}) == " (NORMAL)")
ck("order is the engine's, not sorted",
   f({"types": ["POISON", "GROUND"]}) == " (POISON/GROUND)")
ck("no types, nothing said", f({"types": []}) == "" and f({}) == "")
ck("a missing member says nothing rather than raising", f(None) == "")
ck("junk entries are dropped", f({"types": ["FIRE", None, ""]}) == " (FIRE)")

# ---- and both party lines use it ---------------------------------------
SRC = (ROOT / "planner" / "executor.py").read_text()
ck("there is one implementation, not two", SRC.count("def _mon_types") == 1)
_lines = [ln for ln in SRC.splitlines() if "YOUR PARTY RIGHT NOW" in ln]
ck("both party lines are still there", len(_lines) == 2, len(_lines))
ck("the goal page names the types",
   "f\"{i}. {m.get('species')}{_mon_types(m)} L{m.get('level')} \"" in SRC)
ck("...and so does the every-round line",
   "f\"{m.get('species')}{_mon_types(m)} L{m.get('level')} \"" in SRC)
ck("level and HP are untouched",
   SRC.count("f\"{m.get('hp')}/{m.get('max_hp')}hp\"") == 2)

# ---- the whole line, as the model reads it -----------------------------
party = [{"species": "GYARADOS", "types": ["WATER", "FLYING"],
          "level": 50, "hp": 162, "max_hp": 162},
         {"species": "EEVEE", "types": ["NORMAL", "NORMAL"],
          "level": 40, "hp": 110, "max_hp": 110}]
shown = "; ".join(f"{m['species']}{f(m)} L{m['level']} {m['hp']}/{m['max_hp']}hp"
                  for m in party)
ck("the line reads as a party sheet",
   shown == "GYARADOS (WATER/FLYING) L50 162/162hp; "
            "EEVEE (NORMAL) L40 110/110hp", shown)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d)[:120] + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
