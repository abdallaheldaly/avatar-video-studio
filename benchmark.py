"""Measure how fast THIS machine is, then estimate the time of a whole episode for each quality preset.

    python benchmark.py                          # scenes + local LLM
    python benchmark.py --image me.png           # also MuseTalk lip-sync speed (needs weights)
    python benchmark.py --minutes 15 --scene-ratio 0.6"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import llm
import pipeline as P
import tools

SCENE = {"type": "bars", "title": "Benchmark", "items": [{"label": "A", "value": 5}, {"label": "B", "value": 9}, {"label": "C", "value": 7}]}


def bench_scene(fps, jpeg, seconds=4.0):
    out = Path(tempfile.mkdtemp()) / "s.mp4"
    t = time.time()
    P.render_scene(SCENE, seconds, out, tempfile.gettempdir(), fps, jpeg)
    return (time.time() - t) / seconds            # wall seconds per scene second (single worker)


def bench_llm():
    ok, msg = llm.status()
    if not ok:
        return None, msg
    import extract
    t = time.time()
    extract.extract_segment("الإيرادات كانت 500 ألف جنيه والمصروفات 300 ألف جنيه")
    return time.time() - t, msg


def bench_musetalk(image, seconds=3.0):
    work = Path(tempfile.mkdtemp())
    audio = work / "a.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=200:duration={seconds}", "-ar", "16000", str(audio)], check=True)
    segs = [{"start": 0.0, "end": seconds}]
    t = time.time()
    P.musetalk_clips(image, str(audio), segs, [0], work, "bench")
    return (time.time() - t) / seconds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--scene-ratio", type=float, default=0.6, help="share of the episode shown as 3D scenes")
    ap.add_argument("--image")
    a = ap.parse_args()
    workers = int(os.environ.get("SCENE_WORKERS", max(1, min(4, tools.cpu_count() // 2))))
    print(f"CPU cores: {tools.cpu_count()}  scene workers: {workers}\n")
    r = {k: bench_scene(v["fps"], v["jpeg"]) for k, v in P.PRESETS.items()}
    for k, v in r.items():
        print(f"3D scene render [{k:8}]: {v:5.1f} s of work per 1 s of scene (single worker)")
    llm_s, msg = bench_llm()
    print(f"Local LLM: {msg}" + (f"; {llm_s:.1f} s per segment" if llm_s else ""))
    mt = None
    if a.image:
        try:
            mt = bench_musetalk(a.image)
            print(f"MuseTalk lip-sync: {mt:.1f} s of work per 1 s of video")
        except Exception as e:
            print("MuseTalk benchmark failed:", e)
    sec, seg_n = a.minutes * 60, a.minutes * 60 / 10
    print(f"\nEstimate for a {a.minutes:g}-minute episode ({a.scene_ratio:.0%} scenes) - rough, excludes Whisper and model loading:")
    for k, p in P.PRESETS.items():
        scenes = sec * a.scene_ratio * r[k] / workers
        analysis = (seg_n * llm_s) if llm_s else 0
        lip = {"all": sec, "speaker-only": sec * (1 - a.scene_ratio), "none": 0}[p["lipsync"]] * (mt or 0)
        total = scenes + lip + sec * 0.05
        print(f"  {k:8}: scenes ~{scenes / 60:5.1f} min | lip-sync ~{lip / 60:5.1f} min | analysis (once) ~{analysis / 60:4.1f} min"
              f" | build total ~{total / 60:5.1f} min")
    if mt is None:
        print("  (lip-sync not measured: pass --image your_photo.png to include MuseTalk)")


if __name__ == "__main__":
    main()
