"""Headless run (no UI, no manual review):  python studio.py generate me.png talk.m4a --quality high"""
import argparse
from pathlib import Path

import pipeline as P

ap = argparse.ArgumentParser()
ap.add_argument("image"); ap.add_argument("audio")
ap.add_argument("--quality", default="balanced", choices=list(P.PRESETS)); ap.add_argument("--language", default="ar")
ap.add_argument("--notes"); ap.add_argument("--hotwords", default=""); ap.add_argument("--voice"); ap.add_argument("--no-llm", action="store_true")
a = ap.parse_args()
notes = Path(a.notes).read_text(encoding="utf-8", errors="ignore") if a.notes else ""
final, rep = P.run_all(a.image, a.audio, a.quality, a.language, notes, a.hotwords, a.voice, not a.no_llm,
                       progress=lambda f, m: print(f"[{f:4.0%}] {m}", flush=True))
print("\nVideo:", final)
for w in rep["warnings"]:
    print("WARNING:", w)
print("Timings:", rep["timings"])
