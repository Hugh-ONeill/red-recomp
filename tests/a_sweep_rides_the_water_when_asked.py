#!/usr/bin/env python3
"""sweep takes surf=true and mounts the water first; the automatic ride
waits for the Soul Badge, and the page says so.

User, 2026-09-08: "can sweep be run with surf? (after we get the
soulbadge)". While the player is afloat the reach set already includes water
(seen_reach reads p.surfing), so a sweep begun on the water follows it; what
was missing was a way to BEGIN one there. Now {"op":"sweep","surf":true}
walks to the nearest shore (the same cell a rod is cast from), rides on with
field_move SURF and sweeps. And the order the run met was backwards — a
POLIWAG learned SURF in Cerulean with four badges — so the shim marks the
water frontier "surf_badge_missing" while the SOULBADGE is not in the case,
explore's ride branch stands down, and the ledger's three water lines say
the badge is what is missing instead of promising a ride.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "harness" / "shim.lua").read_text()
ex = (ROOT / "planner" / "executor.py").read_text()
lg = (ROOT / "planner" / "ledger.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


sw = sh[sh.index("function OPS.sweep(G, c)"):sh.index("function OPS.overlay(G, c)")]
ck("sweep mounts the water when asked and not already afloat", "if c.surf and not p.surfing then" in sw)
ck("...refusing when nobody knows SURF", 'return false, "no party Pokemon knows SURF, so the water here cannot "' in sw)
ck("...from the same shore a rod is cast from", "local bx, by, bland = nearest_shore(G)" in sw and "local function nearest_shore(G)" in sh)
ck("...riding on with the game's own field move, whose refusal names the badge", 'OPS.field_move(G, { move = "SURF", x = bx, y = by })' in sw and 'if not ok2 or not p.surfing then' in sw)
ck("the mount happens before the frontier is read, so the frontier includes water", sw.index("if c.surf and not p.surfing then") < sw.index("seen_paint(G)"))
ck("the shim marks the water frontier shut while the SOULBADGE is missing", 'm.seen.surf_badge_missing = "SOULBADGE"' in sh and "KNOWING SURF IS NOT BEING ALLOWED TO" in sh)
ck("explore's ride waits for the badge", 'and self._knows_move(obs, "SURF") and not _surf_shut):' in ex and '"SOULBADGE" not in (obs.get("badges") or [])' in ex)
ck("...and logs that it stood down", 'step="ride_shut"' in ex)
ck("the catalogue names sweep surf and the badge", '{"op":"sweep","surf":true} mounts the water at the nearest shore' in ex and "knows SURF and the SOULBADGE is in your case" in ex)
ck("the ledger's water candidate says the badge when it is what is missing", "only once the SOULBADGE is in your case, and " in lg)
ck("the ledger's 'everything on foot is done' lines say it too", lg.count("_ride_words") >= 3 and "so the ride waits on that" in lg)
ck("the ledger's first-leg advice does not promise a ride the game refuses", 'not (_m0.get("seen") or {}).get("surf_badge_missing")' in lg)
sys.exit(1 if fails else 0)
