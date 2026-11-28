"""Render one 3D scene to an mp4, frame by frame, with headless Chromium (Playwright).
Time is controlled by the page (window.__setT), so quality does not depend on machine speed.
Runs as its own process (`python render.py job.json`) so several scenes render in parallel and a crash can't kill a build."""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import tools

tools.ensure_ffmpeg()
HERE = Path(__file__).resolve().parent
W, H, OUT_FPS = 1280, 720, 30


def file_to_uri(path):
    import base64
    import urllib.parse
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".svg":
        return "data:image/svg+xml;utf8," + urllib.parse.quote(path.read_text(encoding="utf-8"))
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}[ext]
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def active_seconds(scene):
    """When the entrance animations are finished; afterwards only a slow camera sway remains."""
    n = len(scene.get("items", []))
    return {"bars": 1.8 + 0.25 * n, "donut": 1.4 + 0.3 * n, "compare": 2.8, "equation": 2.2 + 0.9 * n,
            "steps": 2.2 + 0.9 * n, "bullets": 2.2 + 0.9 * n, "image": 2.2, "title": 1.6}.get(scene.get("type"), 3.0)


def render(scene, dur, out, work=None, fps=24, jpeg=92, crf=18):
    from playwright.sync_api import sync_playwright
    sc = dict(scene)
    f = sc.pop("illustration_file", None)
    if f and work and (Path(work) / f).exists():
        sc["illustration_uri"] = file_to_uri(Path(work) / f)
    args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"]
    if hasattr(os, "geteuid") and os.geteuid() == 0:      # Docker / root
        args.append("--no-sandbox")
    args += shlex.split(os.environ.get("CHROMIUM_ARGS", ""))
    # schedule: full fps while animating, then every 3rd frame repeated (slow sway only)
    rep = 3 if fps >= 12 else 1
    act, t, plan = min(dur, active_seconds(sc)), 0.0, []
    while t < act:
        plan.append((t, 1)); t += 1 / fps
    while t < dur:
        plan.append((t, rep)); t += rep / fps
    enc = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", str(fps),
                            "-c:v", "mjpeg", "-i", "-", "-r", str(OUT_FPS), "-c:v", "libx264", "-preset", "veryfast",
                            "-pix_fmt", "yuv420p", "-crf", str(crf), str(out)], stdin=subprocess.PIPE)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None, args=args)
            page = b.new_page(viewport={"width": W, "height": H})
            page.add_init_script("window.__MANUAL = true; window.SCENE = " + json.dumps(sc, ensure_ascii=False))
            page.goto((HERE / "scene.html").as_uri())
            page.wait_for_function("window.__ready === true", timeout=30000)
            for t, r in plan:
                page.evaluate("t => window.__setT(t)", t)
                img = page.screenshot(type="jpeg", quality=jpeg)
                for _ in range(r):
                    enc.stdin.write(img)
            b.close()
    finally:
        enc.stdin.close()
        enc.wait()
    if enc.returncode:
        raise RuntimeError("ffmpeg failed while encoding the scene")


if __name__ == "__main__":
    render(**json.load(open(sys.argv[1])))
