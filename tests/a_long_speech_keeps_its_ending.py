#!/usr/bin/env python3
"""A long speech keeps its ending, and a gift keeps the words that came with it.

The Fan Club chairman talks for five hundred characters about his Rapidash,
hands over the BIKE VOUCHER, and only then says the one useful sentence:
"Exchange that for a BICYCLE!". Every capture site cut speech with `[:N]`
from the front — 220 in the hints ledger, 160 in the round's trace, 200 in
the outcomes — so the run's whole record of him was "I chair the POKéMON Fan
Club! ... My favorite RAPIDASH... It...cute... love", and it held a voucher
for hours with nothing anywhere saying what the game had said it was for
(2026-09-03; user: "im disturbed that its not trying the 'bike mart' in the
town its actually in"). Bill, the Captain, Mr. Fuji and Oak's aides speak in
the same shape: story first, the useful line last.

Two fixes, both recall of what was on the screen:
  * a cut speech keeps its head AND its tail, seam marked, tail favoured;
  * a thing a named person handed over keeps their words AGAINST THE ITEM,
    on the bag line of every page — because room hints are dealt round
    robin, first sentence of every room before any room's second, capped at
    fourteen, and the chairman's line was fourth of seven in his room: it
    reached zero pages while the Pikachu fan's reached 305.

Synthetic: no game, no model.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

INTRO = ("I chair the POKéMON Fan Club! I have collected over 100 POKéMON! "
         "I'm very fussy when it comes to POKéMON! So... Did you come visit "
         "to hear about my POKéMON? Good! Then listen up! My favorite "
         "RAPIDASH... It...cute... lovely...smart... plus...amazing... you "
         "think so?... oh yes...it... stunning... kindly... love it! Hug "
         "it...when... sleeping...warm and cuddly... spectacular... "
         "ravishing... ...Oops! Look at the time! I kept you too long! "
         "Thanks for hearing me out! I want you to have this!")
TAIL = ("RED received a BIKE VOUCHER! Exchange that for a BICYCLE! Don't "
        "worry, my FEAROW will FLY me anywhere! So, I don't need a BICYCLE! "
        "I hope you like cycling!")
SPEECH = INTRO + " " + TAIL

for cap in (160, 220, 300, 480):
    got = E.speech_excerpt(SPEECH, cap)
    ck(f"cut to {cap}, the speech still starts where it started",
       got.startswith("I chair the POK"), got[:60])
    ck(f"...and still ends where it ended", got.endswith("I hope you like cycling!"),
       got[-60:])
    ck(f"...within the cap (plus the seam)", len(got) <= cap + 5, len(got))
    ck(f"...with the seam marked", " ... " in got)
got = E.speech_excerpt(SPEECH, 220)
ck("at the ledger's cap the instruction survives",
   "Exchange that for a BICYCLE!" in got, got)
got = E.speech_excerpt(SPEECH, 480)
ck("at the gift cap the hand-over and the instruction both survive",
   "received a BIKE VOUCHER" in got and "Exchange that for a BICYCLE" in got)
short = "Okay! Say hi to PROF.OAK for me!"
ck("a short line is left exactly as said", E.speech_excerpt(short, 160) == short)
ck("nothing is ever invented: every kept character is in the original",
   all(part in SPEECH for part in E.speech_excerpt(SPEECH, 200).split(" ... ")))
ck("an empty speech is empty", E.speech_excerpt("", 160) == "")

# the bag line carries who handed a thing over, and their words
e = object.__new__(E.Executor)
e._item_from = {"BIKE_VOUCHER": {"who": "POKEMONFANCLUB_CHAIRMAN",
                                 "at": "POKEMON_FAN_CLUB|0,1",
                                 "said": E.speech_excerpt(SPEECH, 300)}}
note = e._gift_note("BIKE_VOUCHER")
ck("a gift names its giver", "handed to you by POKEMONFANCLUB_CHAIRMAN" in note, note)
ck("...and the room, without the region's coordinates",
   " in POKEMON_FAN_CLUB," in note and "|0,1" not in note, note)
ck("...and what they said, ending included",
   "Exchange that for a BICYCLE!" in note, note)
ck("a thing bought or picked up says nothing extra", e._gift_note("POTION") == "")
e2 = object.__new__(E.Executor)
ck("an executor from before the ledger existed does not die of it",
   e2._gift_note("BIKE_VOUCHER") == "")

src = (ROOT / "planner" / "executor.py").read_text()
ck("the hints ledger keeps head and tail, with a longer cap the round the bag grew",
   "_kept = speech_excerpt(said, 480 if _gained else 220)" in src
   and 'line = f"{who}: {_kept}"' in src)
ck("the round's trace does too",
   "speech_excerpt(heard, 320 if _grew else 160)" in src)
ck("and the outcomes ledger", "speech_excerpt(last.strip(), 200)" in src)
ck("a gift is recorded against the item only for a named thing pressed",
   'if (_gained and op == "interact" and step.get("name")' in src)
ck("...and persisted with the rest of the memory",
   '"item_from": getattr(self, "_item_from", {})' in src
   and 'self._item_from = data.get("item_from") or {}' in src)
ck("the carrying line asks for it", 'f"{k} x{v}{self._gift_note(k)}"' in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
sys.exit(1 if bad else 0)
