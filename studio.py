#!/usr/bin/env python3
"""Cross-platform launcher for Windows, macOS and Linux (standard library only).

    python studio.py setup            install everything into this folder (venvs, weights, local LLM)
    python studio.py run              start the local LLM + the web UI  (http://127.0.0.1:7860)
    python studio.py generate IMAGE AUDIO [--quality high]     headless: no UI, no manual review
    python studio.py doctor           check every component and say what to fix
    python studio.py benchmark        measure this machine and estimate episode times
    python studio.py eval             compare local models on extraction accuracy
    python studio.py vendor           copy libraries + models into this folder for offline reinstall
    python studio.py test             run the test suite
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WIN, IS_MAC = os.name == "nt", sys.platform == "darwin"
APP_VENV, MT_VENV = ".venv", ".venv-musetalk"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1:11500")
TORCH = {"torch": "2.2.2", "torchvision": "0.17.2", "torchaudio": "2.2.2"}


# ------------------------------------------------------------------ helpers
def vpy(name):
    return ROOT / name / ("Scripts/python.exe" if IS_WIN else "bin/python")


def say(msg):
    print(f"\n== {msg}", flush=True)


def sh(cmd, env=None, check=True, cwd=None):
    cmd = [str(c) for c in cmd]
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, env=env, cwd=cwd or ROOT, check=check)


def uv():
    exe = shutil.which("uv")
    if exe:
        return [exe]
    sh([sys.executable, "-m", "pip", "install", "--user", "uv"])
    return [sys.executable, "-m", "uv"]


def load_env():
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def has_nvidia():
    try:
        return subprocess.run(["nvidia-smi"], capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def ram_gb():
    try:
        if IS_MAC:
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"])) / 2 ** 30
        if IS_WIN:
            out = subprocess.check_output(["powershell", "-NoProfile", "-Command",
                                           "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"], text=True)
            return int(out.strip()) / 2 ** 30
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                return int(line.split()[1]) / 2 ** 20
    except Exception:
        pass
    return 16.0


def pick_llm():
    gb = ram_gb()
    return "qwen3:4b" if gb < 12 else "qwen3:14b" if gb >= 30 else "qwen3:8b"


def base_env():
    load_env()
    env = dict(os.environ)
    env.update({"MUSETALK_PYTHON": str(vpy(MT_VENV)), "OLLAMA_HOST": OLLAMA_HOST,
                "OLLAMA_MODELS": str(ROOT / "models_cache" / "ollama"), "PYTHONUTF8": "1"})
    if (ROOT / "models_cache" / "huggingface" / "hub").exists():
        env.setdefault("HF_HOME", str(ROOT / "models_cache" / "huggingface"))
    if (ROOT / "vendor" / "browsers").exists() and any((ROOT / "vendor" / "browsers").iterdir()):
        env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / "vendor" / "browsers"))
    return env


# ------------------------------------------------------------------ Ollama
def ollama_up(host=None):
    h = host or OLLAMA_HOST
    h = h if h.startswith("http") else "http://" + h
    try:
        urllib.request.urlopen(h + "/api/tags", timeout=2)
        return True
    except Exception:
        return False


def install_ollama():
    if shutil.which("ollama"):
        return True
    say("Installing Ollama (open source, MIT)")
    try:
        if IS_MAC:
            sh(["brew", "install", "ollama"])
        elif IS_WIN:
            sh(["winget", "install", "--id", "Ollama.Ollama", "-e", "--accept-source-agreements", "--accept-package-agreements"])
        else:
            sh(["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"])
    except Exception as e:
        print(f"Automatic Ollama install failed ({e}). Install it manually from https://ollama.com/download and re-run.")
    return bool(shutil.which("ollama"))


def start_ollama(env):
    """Start our own Ollama on a private port (models stored inside this folder). Returns the process or None."""
    if ollama_up():
        return None
    exe = shutil.which("ollama")
    if not exe:
        print("Ollama is not installed: the lesson will be planned without the local model.")
        return None
    (ROOT / "models_cache" / "ollama").mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([exe, "serve"], env={**env, "OLLAMA_HOST": OLLAMA_HOST}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if ollama_up():
            break
        time.sleep(0.5)
    return proc


# ------------------------------------------------------------------ setup
def make_venv(name, py):
    if not vpy(name).exists():
        sh(uv() + ["venv", "--seed", "--python", py, name])


def pip_install(name, args, offline=None):
    opts = ["--no-index", "--find-links", offline] if offline else []
    sh(uv() + ["pip", "install", "--python", vpy(name)] + opts + args)


def torch_args(with_mmpose):
    """CUDA wheels when an NVIDIA GPU is present, CPU wheels otherwise; macOS uses the default (MPS-capable) wheels."""
    v = {"torch": "2.0.1", "torchvision": "0.15.2", "torchaudio": "2.0.2"} if with_mmpose else TORCH
    pk = [f"{k}=={x}" for k, x in v.items()]
    if IS_MAC:
        return pk
    if has_nvidia():
        idx = "cu118" if with_mmpose else "cu121"
    else:
        idx = "cpu"
    return pk + ["--index-url", f"https://download.pytorch.org/whl/{idx}", "--extra-index-url", "https://pypi.org/simple"]


def cmd_setup(a):
    offline = a.offline
    if offline and not (ROOT / "locks" / "app.txt").exists():
        sys.exit("No local copy found. Run `python studio.py vendor` after a normal setup first.")
    say(f"Platform: {platform.system()} {platform.machine()}  |  NVIDIA GPU: {has_nvidia()}  |  RAM: {ram_gb():.0f} GB")
    say("1/4  App environment (Python 3.11)")
    make_venv(APP_VENV, "3.11")
    if offline:
        pip_install(APP_VENV, ["-r", "locks/app.txt"], "wheelhouse/app")
    else:
        pip_install(APP_VENV, ["-r", "requirements.txt"])
    if offline and (ROOT / "vendor" / "browsers").exists() and any((ROOT / "vendor" / "browsers").iterdir()):
        print("Using the Chromium copy inside vendor/browsers")
    else:
        sh([vpy(APP_VENV), "-m", "playwright", "install", "chromium"])
        if sys.platform.startswith("linux"):
            print("On a fresh Linux install Chromium may need system libraries:\n"
                  f"  sudo {vpy(APP_VENV)} -m playwright install-deps chromium")

    say("2/4  MuseTalk environment (Python 3.10)")
    make_venv(MT_VENV, "3.10")
    if offline:
        pip_install(MT_VENV, ["-r", "locks/musetalk.txt"], "wheelhouse/musetalk")
    else:
        pip_install(MT_VENV, torch_args(a.with_mmpose))
        req = [l for l in (ROOT / "third_party/MuseTalk/requirements.txt").read_text().splitlines()
               if not l.strip().lower().startswith(("tensorflow", "tensorboard", "gradio"))]
        (ROOT / ".mt_requirements.txt").write_text("\n".join(req))
        pip_install(MT_VENV, ["-r", ".mt_requirements.txt"])
        if a.with_mmpose:
            sh([vpy(MT_VENV), "-m", "pip", "install", "-U", "openmim"])
            for pkg in ("mmengine", "mmcv==2.0.1", "mmdet==3.1.0", "mmpose==1.1.0"):
                sh([vpy(MT_VENV), "-m", "mim", "install", pkg])

    say("3/4  MuseTalk weights (about 5 GB, once)")
    if (ROOT / "third_party/MuseTalk/models/musetalkV15/unet.pth").exists():
        print("Weights already present")
    elif a.skip_weights:
        print("Skipped (use FACE_BACKEND=photo or the draft quality until you download them)")
    else:
        sh([vpy(MT_VENV), "download_weights.py"])

    say("4/4  Local language model (Ollama + Qwen3)")
    if a.skip_llm:
        print("Skipped: the lesson will be planned with a basic rule (no understanding).")
    elif install_ollama():
        model = os.environ.get("LLM_MODEL") or pick_llm()
        env = base_env()
        envf = ROOT / ".env"
        txt = envf.read_text(encoding="utf-8") if envf.exists() else ""
        if "LLM_MODEL=" not in txt:
            envf.write_text(txt + f"LLM_MODEL={model}\n", encoding="utf-8")
        if (ROOT / "models_cache/ollama/manifests").exists():
            print("Ollama model already inside the project")
        else:
            srv = start_ollama(env)
            try:
                sh([shutil.which("ollama"), "pull", model], env={**env, "OLLAMA_HOST": OLLAMA_HOST})
            finally:
                if srv:
                    srv.terminate()
    print("\nSetup finished.  Try:  python studio.py doctor   then   python studio.py run")


# ------------------------------------------------------------------ run / generate / tools
def cmd_run(a):
    env = base_env()
    if a.face_backend:
        env["FACE_BACKEND"] = a.face_backend
    srv = None if a.no_ollama else start_ollama(env)
    print("\nOpen http://127.0.0.1:7860 in your browser (Ctrl+C to stop)\n")
    try:
        sh([vpy(APP_VENV), "app.py"], env=env, check=False)
    finally:
        if srv:
            srv.terminate()


def cmd_generate(a):
    env = base_env()
    srv = start_ollama(env)
    try:
        args = [vpy(APP_VENV), "generate.py", a.image, a.audio, "--quality", a.quality, "--language", a.language]
        for flag, val in (("--notes", a.notes), ("--hotwords", a.hotwords), ("--voice", a.voice)):
            if val:
                args += [flag, val]
        if a.no_llm:
            args.append("--no-llm")
        sh(args, env=env)
    finally:
        if srv:
            srv.terminate()


def cmd_tool(script, extra):
    env = base_env()
    srv = start_ollama(env)
    try:
        sh([vpy(APP_VENV), script] + extra, env=env, check=False)
    finally:
        if srv:
            srv.terminate()


def cmd_test(a):
    env = base_env()
    for t in ("tests/test_numbers_ar.py", "tests/test_pipeline.py"):
        sh([vpy(APP_VENV), t], env=env, check=False)


def cmd_vendor(a):
    """Copy libraries and models into this folder, so a fresh machine can reinstall without internet."""
    for d in ("locks", "wheelhouse/app", "wheelhouse/musetalk", "models_cache/huggingface/hub", "vendor/browsers"):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    for venv, name in ((APP_VENV, "app"), (MT_VENV, "musetalk")):
        say(f"Freezing + downloading libraries: {name}")
        out = subprocess.check_output([vpy(venv), "-m", "pip", "freeze"], text=True)
        (ROOT / "locks" / f"{name}.txt").write_text(out)
        sh([vpy(venv), "-m", "pip", "download", "-q", "-r", f"locks/{name}.txt", "-d", f"wheelhouse/{name}"])
    say("Whisper models + Chromium")
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface")) / "hub"
    for d in hub.glob("models--Systran--faster-whisper-*"):
        shutil.copytree(d, ROOT / "models_cache/huggingface/hub" / d.name, dirs_exist_ok=True)
    for pw in (Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright", Path.home() / "Library/Caches/ms-playwright",
               Path.home() / ".cache/ms-playwright"):
        if pw.exists():
            shutil.copytree(pw, ROOT / "vendor/browsers", dirs_exist_ok=True)
            break
    print("\nDone. On a new machine:  python studio.py setup --offline")
    print("(Ollama models already live in models_cache/ollama; MuseTalk weights in third_party/MuseTalk/models.)")


def cmd_doctor(a):
    env = base_env()
    ok_all = True

    def check(name, ok, fix=""):
        nonlocal ok_all
        ok_all &= bool(ok)
        print(f"  [{'OK' if ok else 'FAIL'}] {name}" + ("" if ok else f"\n         -> {fix}"))

    def py_ok(venv, code):
        p = vpy(venv)
        return p.exists() and subprocess.run([p, "-c", code], capture_output=True, env=env).returncode == 0

    print(f"Platform: {platform.platform()} | Python {platform.python_version()} | RAM {ram_gb():.0f} GB | NVIDIA: {has_nvidia()}")
    check("App environment", vpy(APP_VENV).exists(), "python studio.py setup")
    check("App libraries", py_ok(APP_VENV, "import gradio, faster_whisper, playwright, soundfile, imageio_ffmpeg"), "python studio.py setup")
    check("ffmpeg", py_ok(APP_VENV, "import tools, sys; sys.exit(0 if tools.ensure_ffmpeg() else 1)"), "pip install imageio-ffmpeg (or install ffmpeg)")
    check("Chromium for 3D scenes", py_ok(APP_VENV, "from playwright.sync_api import sync_playwright as s\np=s().start();b=p.chromium.launch();b.close();p.stop()"),
          f"{vpy(APP_VENV)} -m playwright install chromium" + ("  (Linux: also `playwright install-deps chromium`)" if sys.platform.startswith("linux") else ""))
    check("MuseTalk environment (torch, diffusers)", py_ok(MT_VENV, "import torch, diffusers, transformers"), "python studio.py setup")
    r = subprocess.run([vpy(MT_VENV), "-c", "import torch;print('cuda' if torch.cuda.is_available() else 'mps' if getattr(torch.backends,'mps',None) and torch.backends.mps.is_available() else 'cpu')"],
                       capture_output=True, text=True, env=env) if vpy(MT_VENV).exists() else None
    print(f"  [info] MuseTalk will run on: {r.stdout.strip() if r and r.returncode == 0 else 'unknown'}")
    check("MuseTalk weights", (ROOT / "third_party/MuseTalk/models/musetalkV15/unet.pth").exists(), "python studio.py setup  (or python download_weights.py)")
    check("Ollama installed", bool(shutil.which("ollama")), "install from https://ollama.com/download")
    srv = start_ollama(env) if shutil.which("ollama") else None
    try:
        model = os.environ.get("LLM_MODEL", "qwen3:8b")
        have = False
        try:
            tags = json.loads(urllib.request.urlopen(("http://" + OLLAMA_HOST) + "/api/tags", timeout=3).read())
            have = any(m["name"] == model or m["name"] == model + ":latest" for m in tags.get("models", []))
        except Exception:
            pass
        check(f"Local model {model}", have, f"OLLAMA_HOST={OLLAMA_HOST} ollama pull {model}")
    finally:
        if srv:
            srv.terminate()
    free = shutil.disk_usage(ROOT).free / 2 ** 30
    check(f"Free disk space ({free:.0f} GB)", free > 10, "free at least 10 GB")
    print("\nAll good." if ok_all else "\nFix the FAIL items above.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    a = s.add_parser("setup"); a.add_argument("--offline", action="store_true"); a.add_argument("--skip-llm", action="store_true")
    a.add_argument("--skip-weights", action="store_true"); a.add_argument("--with-mmpose", action="store_true",
                                                                          help="NVIDIA only, advanced: original MuseTalk face landmarks")
    a.set_defaults(fn=cmd_setup)
    a = s.add_parser("run"); a.add_argument("--no-ollama", action="store_true", help="use an Ollama that is already running (Docker)")
    a.add_argument("--face-backend", choices=["musetalk", "sadtalker", "photo"]); a.set_defaults(fn=cmd_run)
    a = s.add_parser("generate"); a.add_argument("image"); a.add_argument("audio")
    a.add_argument("--quality", default="balanced", choices=["draft", "balanced", "high"]); a.add_argument("--language", default="ar")
    a.add_argument("--notes"); a.add_argument("--hotwords"); a.add_argument("--voice"); a.add_argument("--no-llm", action="store_true")
    a.set_defaults(fn=cmd_generate)
    s.add_parser("doctor").set_defaults(fn=cmd_doctor)
    s.add_parser("vendor").set_defaults(fn=cmd_vendor)
    s.add_parser("test").set_defaults(fn=cmd_test)
    for name, script in (("benchmark", "benchmark.py"), ("eval", "eval_llm.py")):
        a = s.add_parser(name); a.add_argument("extra", nargs=argparse.REMAINDER); a.set_defaults(fn=lambda ns, sc=script: cmd_tool(sc, ns.extra))
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
