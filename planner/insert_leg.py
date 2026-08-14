#!/usr/bin/env python3
"""Place an objective the model said was missing, before leg N.

Its own file rather than an inline heredoc: the chain script already
nests one, and a second sharing the terminator silently truncated the
block it was written into.
"""
import sys
from pathlib import Path

i, text = int(sys.argv[1]), sys.argv[2]
p = Path("plans/outline.txt")
lines = [l for l in p.read_text().splitlines() if l.strip()]
lines.insert(i - 1, text)
p.write_text("\n".join(lines) + "\n")
print(f"inserted before leg {i}: {text}")
