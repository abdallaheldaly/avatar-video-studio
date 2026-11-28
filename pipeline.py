"""Avatar Video Studio pipeline:  transcribe -> analyze -> build.

Each stage reads/writes files in a per-input work folder (work/<id>/), so every stage is resumable and you can
edit the result of a stage (transcript, plan) before running the next one."""
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import asr
import extract
import llm
import tools

tools.ensure_ffmpeg()
W, H, FPS = 1280, 720, 30
HERE = Path(__file__).resolve().parent
SADTALKER_DIR = os.environ.get("SADTALKER_DIR", str(HERE / "third_party" / "SadTalker"))
MUSETALK_DIR = os.environ.get("MUSETALK_DIR", str(HERE / "third_party" / "MuseTalk"))
MUSETALK_PYTHON = os.environ.get("MUSETALK_PYTHON", sys.executable)   # python of the MuseTalk environment
SADTALKER_PYTHON = os.environ.get("SADTALKER_PYTHON", sys.executable)
FACE_BACKEND = os.environ.get("FACE_BACKEND", "musetalk")             # musetalk | sadtalker | photo
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")             # Mac: unsupported MPS ops fall back to CPU

# quality presets: draft = fastest (check layout/numbers), balanced = default, high = everything lip-synced
PRESETS = {
    "draft":    {"face": "photo", "lipsync": "none", "fps": 8,  "jpeg": 80},
    "balanced": {"face": "auto",  "lipsync": "speaker-only", "fps": 16, "jpeg": 88},
    "high":     {"face": "auto",  "lipsync": "all", "fps": 24, "jpeg": 92},
}


# ---------------------------------------------------------------- helpers
def run(cmd, **kw):
    cmd = [str(c) for c in cmd]
    if cmd[0] == "ffmpeg":
        cmd[1:1] = ["-hide_banner", "-loglevel", "error"]
    print(">>", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def audio_duration(path):
    try:
        import soundfile as sf
        return float(sf.info(str(path)).duration)
    except Exception:                                   # fallback: ask ffmpeg
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)], capture_output=True, text=True)
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
        if not m:
            raise RuntimeError(f"Cannot read the duration of {path}")
        return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def sha(*parts, n=10):
    h = hashlib.sha1()
    for p in parts:
        h.update(p if isinstance(p, bytes) else str(p).encode())
        h.update(b"|")
    return h.hexdigest()[:n]


def file_sha(path, n=12):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:n]


def job_dir(*files, root="work"):
    """One folder per (image, audio): same inputs resume from cache, different inputs get a fresh folder."""
    d = Path(root) / sha(*[file_sha(f) for f in files if f], n=12)
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(p, default=None):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def write_json(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def fmt_time(s):
    s = int(max(s, 0))
    return f"{s // 60}:{s % 60:02d}"


# ---------------------------------------------------------------- stage 1: transcribe
def transcribe_stage(image, audio, language="ar", hotwords="", notes="", workdir="work", progress=lambda f, m: None):
    """Convert the audio (m4a/mp3/wav...) and transcribe it. Returns (work, segments).
    Edit the segments if needed before running `analyze`."""
    work = job_dir(image, audio, root=workdir)
    wav, tfile = work / "audio.wav", work / "transcript.json"
    if not wav.exists():
        progress(0.02, "Converting audio...")
        run(["ffmpeg", "-y", "-i", audio, "-vn", "-ar", 44100, wav])
    cached = read_json(tfile)
    if cached and cached.get("language") == language and cached.get("hotwords") == hotwords:
        progress(1.0, "Using cached transcript")
        return work, cached["segments"]
    progress(0.1, f"Transcribing with Whisper ({asr.model_name()})...")
    hot = hotwords.strip() or asr.hotwords_from_notes(notes)
    t0 = time.time()
    segs = asr.transcribe(wav, language, hot)
    write_json(tfile, {"language": language, "hotwords": hotwords, "segments": segs, "seconds": round(time.time() - t0, 1)})
    progress(1.0, "Transcript ready - review and fix it if needed")
    return work, segs


# ---------------------------------------------------------------- stage 2: analyze
def merge_segments(segs, total, min_len=8.0):
    """Merge short Whisper segments into planning segments of at least `min_len` seconds (contiguous, no gaps)."""
    segs = [s for s in segs if str(s.get("text", "")).strip()]
    if not segs:
        raise ValueError("No speech found in the audio. Check that it is clear spoken audio in the selected language.")
    out, cur = [], None
    for s in segs:
        if cur is None:
            cur = {"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()}
        else:
            cur["end"], cur["text"] = float(s["end"]), cur["text"] + " " + s["text"].strip()
        if cur["end"] - cur["start"] >= min_len:
            out.append(cur); cur = None
    if cur:
        out.append(cur)
    for i, s in enumerate(out):
        s["start"] = 0.0 if i == 0 else out[i - 1]["end"]
    out[-1]["end"] = max(total, out[-1]["end"])
    return out


UNDERSTAND_SYS = ("You are an editor of educational videos. You get the transcript of one lesson. Understand it and answer "
                  "in JSON. Write text values in the same language as the transcript, short and faithful. "
                  "Never invent facts or numbers that are not in the transcript.")
UNDERSTAND_SCHEMA = {"type": "object", "required": ["title", "summary", "domain", "outline", "key_terms"], "properties": {
    "title": {"type": "string"}, "summary": {"type": "string"}, "domain": {"type": "string"},
    "outline": {"type": "array", "items": {"type": "string"}},
    "key_terms": {"type": "array", "items": {"type": "object", "required": ["term", "meaning"],
                                              "properties": {"term": {"type": "string"}, "meaning": {"type": "string"}}}}}}


def _sample(segs, limit=14000):
    full = "\n".join(s["text"] for s in segs)
    if len(full) <= limit:
        return full
    t, m = limit // 3, len(full) // 2          # long lesson: beginning + middle + end
    return full[:t] + "\n...\n" + full[m - t // 2: m + t // 2] + "\n...\n" + full[-t:]


def key_numbers(segs, n=12):
    """Key numbers are collected by code from the text (never by the model), so they cannot be hallucinated."""
    out = []
    for s in segs:
        w = extract._norm(s["text"]).split()
        out += [" ".join(w[max(0, i - 2):i + 3]) for i, x in enumerate(w) if re.fullmatch(r"\d[\d.]*", x)]
    return out[:n]


def retrieve_notes(query, notes, k=2, max_chars=600):
    """Pick the notes paragraphs that overlap most with the segment (simple lexical retrieval)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", notes or "") if p.strip()]
    q = set(re.findall(r"\w{3,}", query))
    scored = sorted(((len(q & set(re.findall(r"\w{3,}", p))), p) for p in paras), reverse=True)
    return "\n".join(p[:300] for sc, p in scored[:k] if sc)[:max_chars]


def understand(segs, notes="", use_llm=True):
    ok, msg = llm.status() if use_llm else (False, "local LLM disabled")
    lesson = {"title": "", "summary": "", "domain": "", "outline": [], "key_terms": []}
    if ok:
        try:
            ctx = ("Reference notes written by the author:\n" + notes[:3000] + "\n\n") if notes else ""
            lesson.update(llm.chat_json(UNDERSTAND_SYS, ctx + "Transcript:\n" + _sample(segs), UNDERSTAND_SCHEMA, 1500))
        except Exception as e:
            ok, msg = False, f"local model failed: {e}"
    if not ok:
        lesson["summary"] = f"(no lesson understanding: {msg})"
    lesson["key_numbers"], lesson["llm_ok"] = key_numbers(segs), ok
    return lesson


def plan_heuristic(segs):
    for s in segs:
        has_num = re.search(r"\d", extract._norm(s["text"]))
        s["mode"] = "scene" if has_num else "face"
        s["scene"] = {"type": "title", "title": " ".join(s["text"].split()[:6])} if has_num else None
        s["warnings"] = []
    return segs


def analyze_stage(work, segments, notes="", use_llm=True, min_len=8.0, progress=lambda f, m: None):
    """Understand the lesson and plan one scene per segment. Returns (lesson, plan)."""
    work = Path(work)
    segs = merge_segments(segments, audio_duration(work / "audio.wav"), min_len)
    progress(0.05, "Understanding the lesson...")
    lesson = understand(segs, notes, use_llm)
    if lesson["llm_ok"]:
        for i, s in enumerate(segs):
            progress(0.1 + 0.88 * i / len(segs), f"Extracting facts from segment {i + 1}/{len(segs)}")
            prev = segs[i - 1]["text"] if i else ""
            nxt = segs[i + 1]["text"] if i + 1 < len(segs) else ""
            try:
                x = extract.extract_segment(s["text"], lesson, prev, nxt, retrieve_notes(s["text"], notes))
                s["mode"], s["scene"], s["warnings"] = extract.plan_segment(x, s["text"], work, i)
            except Exception as e:
                s["mode"], s["scene"], s["warnings"] = "face", None, [f"extraction failed: {e}"]
    else:
        plan_heuristic(segs)
    write_json(work / "lesson.json", lesson)
    write_json(work / "plan.json", segs)
    progress(1.0, "Plan ready - review it before building")
    return lesson, segs


# ---------------------------------------------------------------- face clips
def _src_is_video(src):
    return Path(src).suffix.lower() in VIDEO_EXT


def base_video(src, work):
    """MuseTalk edits the mouth in a video. An image becomes a 10 s still video."""
    if _src_is_video(src):
        return str(Path(src).resolve())
    out = Path(work) / "base.mp4"
    if not out.exists():
        run(["ffmpeg", "-y", "-loop", 1, "-i", src, "-t", 10, "-r", 25, "-vf",
             "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p", "-c:v", "libx264", out])
    return str(out.resolve())


def _seg_wav(audio, work, i, seg, key):
    wav = Path(work) / f"seg_{i:03d}_{key}.wav"
    if not wav.exists():
        run(["ffmpeg", "-y", "-ss", f"{seg['start']:.3f}", "-t", f"{seg['end'] - seg['start']:.3f}", "-i", audio,
             "-ar", 16000, "-ac", 1, wav])
    return wav


def photo_clips(src, segs, idx, work, key):
    """No model, no lip-sync: slow zoom on your photo (or looped video). Fast; used for draft and for corner clips."""
    work, outs = Path(work), {}
    for i in idx:
        s, out = segs[i], work / f"face_{i:03d}_photo_{key}.mp4"
        if not out.exists():
            d = s["end"] - s["start"]
            if _src_is_video(src):
                run(["ffmpeg", "-y", "-stream_loop", -1, "-i", src, "-t", f"{d:.3f}", "-an", "-r", 25, "-vf",
                     "scale=720:720:force_original_aspect_ratio=increase,crop=720:720,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", out])
            else:
                run(["ffmpeg", "-y", "-i", src, "-an", "-t", f"{d:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-vf",
                     "scale=1440:1440:force_original_aspect_ratio=increase,crop=1440:1440,"
                     "zoompan=z='min(1+0.0004*on,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                     f":d={int(d * 25) + 2}:s=720x720:fps=25,format=yuv420p", out])
        outs[i] = out
    return outs


def musetalk_clips(src, audio, segs, idx, work, key):
    """All requested segments in ONE MuseTalk run (the model loads once). JSON is valid YAML."""
    work, base, cfg, wavs = Path(work), base_video(src, work), {}, {}
    for i in idx:
        out = work / f"face_{i:03d}_musetalk_{key}.mp4"
        if not out.exists():
            wavs[i] = _seg_wav(audio, work, i, segs[i], key)
            cfg[f"task_{i}"] = {"video_path": base, "audio_path": str(wavs[i].resolve())}
    if cfg:
        yml = work / f"musetalk_{key}.yaml"
        yml.write_text(json.dumps(cfg))
        run([MUSETALK_PYTHON, "-m", "scripts.inference", "--inference_config", yml.resolve(),
             "--result_dir", (work / "mt").resolve(), "--unet_model_path", "models/musetalkV15/unet.pth",
             "--unet_config", "models/musetalkV15/musetalk.json", "--version", "v15"], cwd=MUSETALK_DIR)
    outs = {}
    for i in idx:
        out = work / f"face_{i:03d}_musetalk_{key}.mp4"
        if not out.exists():
            stem = f"seg_{i:03d}_{key}"
            exact = work / "mt" / "v15" / f"{os.path.basename(base).split('.')[0]}_{stem}.mp4"
            hits = [str(exact)] if exact.exists() else [
                h for h in glob.glob(str(work / "mt" / "**" / f"*_{stem}.mp4"), recursive=True)
                if "concat" not in h and "temp_" not in os.path.basename(h)]
            if not hits:
                raise RuntimeError(f"MuseTalk produced no output for segment {i}")
            shutil.copy(hits[0], out)
        outs[i] = out
    return outs


def sadtalker_clips(src, audio, segs, idx, work, key):
    work, outs = Path(work), {}
    for i in idx:
        out = work / f"face_{i:03d}_sadtalker_{key}.mp4"
        if not out.exists():
            wav = _seg_wav(audio, work, i, segs[i], key)
            res = work / f"st_{i:03d}"
            shutil.rmtree(res, ignore_errors=True); res.mkdir(parents=True)
            run([SADTALKER_PYTHON, "inference.py", "--driven_audio", wav.resolve(), "--source_image", Path(src).resolve(),
                 "--result_dir", res.resolve(), "--still", "--preprocess", "full", "--enhancer", "gfpgan", "--size", 512],
                cwd=SADTALKER_DIR)
            vids = sorted(glob.glob(str(res / "**/*.mp4"), recursive=True), key=os.path.getmtime)
            shutil.copy(vids[-1], out)
        outs[i] = out
    return outs


# ---------------------------------------------------------------- optional voice cloning (XTTS-v2, local)
def _split_text(t, n=150):
    parts, cur = [], ""
    for w in t.split():
        if len(cur) + len(w) + 1 > n:
            parts.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    return parts + ([cur] if cur else [])


def clone_voice(segs, ref_wav, out_wav, language="ar"):
    """Re-speak every plan segment with your voice. Segment times are recomputed from the new audio."""
    try:
        import numpy as np
        import soundfile as sf
        import torch
        from TTS.api import TTS
    except ImportError as e:
        raise RuntimeError("Voice cloning needs the optional package `coqui-tts` (pip install coqui-tts)") from e
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda" if torch.cuda.is_available() else "cpu")
    sr, chunks, t, new = 24000, [], 0.0, []
    for s in segs:
        parts = []
        for piece in _split_text(s["text"]):
            parts += [np.asarray(tts.tts(text=piece, speaker_wav=str(ref_wav), language=language), dtype="float32"),
                      np.zeros(int(sr * 0.15), dtype="float32")]
        y = np.concatenate(parts)
        d = len(y) / sr
        new.append({**s, "start": t, "end": t + d}); chunks.append(y); t += d
    sf.write(str(out_wav), np.concatenate(chunks), sr)
    return new


# ---------------------------------------------------------------- composition
def compose_face(face, dur, out):
    vf = ("[0:v]tpad=stop_mode=clone:stop_duration=3,split=2[a][b];"
          f"[a]scale=160:90:force_original_aspect_ratio=increase,crop=160:90,boxblur=3:2,scale={W}:{H}:flags=bilinear[bg];"
          "[b]scale=-2:640[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p")
    run(["ffmpeg", "-y", "-i", face, "-t", f"{dur:.3f}", "-filter_complex", vf, "-r", FPS, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", out])


def compose_scene(scene_vid, face, dur, out):
    vf = ("[0:v]tpad=stop_mode=clone:stop_duration=2[sc];"
          "[1:v]tpad=stop_mode=clone:stop_duration=3,scale=260:260:force_original_aspect_ratio=increase,"
          "crop=260:260[pip];[sc][pip]overlay=30:H-h-30,format=yuv420p")
    run(["ffmpeg", "-y", "-i", scene_vid, "-i", face, "-t", f"{dur:.3f}", "-filter_complex", vf, "-r", FPS, "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", out])


def render_scene(scene, dur, out, work, fps, jpeg):
    """Render one scene in its own process (parallel-safe; a Chromium crash cannot kill the build)."""
    job = Path(out).with_suffix(".job.json")
    write_json(job, {"scene": scene, "dur": dur, "out": str(out), "work": str(work), "fps": fps, "jpeg": jpeg})
    try:
        subprocess.run([sys.executable, str(HERE / "render.py"), str(job)], check=True)
    finally:
        job.unlink(missing_ok=True)


def scene_key(scene, work, dur, fps, jpeg):
    ill = scene.get("illustration_file")
    extra = file_sha(Path(work) / ill) if ill and (Path(work) / ill).exists() else ""
    return sha(json.dumps(scene, sort_keys=True, ensure_ascii=False), extra, round(dur, 2), fps, jpeg)


# ---------------------------------------------------------------- stage 3: build
def build_stage(work, image, quality="balanced", voice_ref=None, language="ar", workers=None,
                progress=lambda f, m: None):
    """Generate face clips + render 3D scenes + compose the final video. Reuses everything unchanged since last time.
    Returns (final_mp4, report)."""
    work, t_start = Path(work), time.time()
    segs, preset = read_json(work / "plan.json"), PRESETS[quality]
    report = {"quality": quality, "warnings": [], "timings": {}, "segments": len(segs)}
    audio = str(work / "audio.wav")

    def tick(frac, msg):
        el = time.time() - t_start
        eta = f" | elapsed {fmt_time(el)}, ~{fmt_time(el / frac - el)} left" if frac > 0.06 else ""
        progress(frac, msg + eta)

    if voice_ref:
        tick(0.02, "Cloning your voice...")
        cache = work / f"cloned_{sha(file_sha(voice_ref), json.dumps([s['text'] for s in segs], ensure_ascii=False))}.json"
        cw = cache.with_suffix(".wav")
        if cache.exists() and cw.exists():
            segs = read_json(cache)
        else:
            segs = clone_voice(segs, voice_ref, cw, language)
            write_json(cache, segs)
        audio = str(cw)

    # 1) face clips ------------------------------------------------------------------
    n, backend = len(segs), (FACE_BACKEND if preset["face"] == "auto" else preset["face"])
    lip = {"all": list(range(n)), "speaker-only": [i for i, s in enumerate(segs) if s["mode"] == "face"],
           "none": []}[preset["lipsync"] if backend != "photo" else "none"]
    static = [i for i in range(n) if i not in lip]
    akey = sha(audio, round(os.path.getsize(audio) / 1000), n, n=6)
    faces, t0 = {}, time.time()
    tick(0.05, f"Face clips: {len(lip)} lip-synced ({backend}), {len(static)} static")
    if lip:
        fn = {"musetalk": lambda: musetalk_clips(image, audio, segs, lip, work, akey),
              "sadtalker": lambda: sadtalker_clips(image, audio, segs, lip, work, akey)}[backend]
        try:
            faces.update(fn())
        except Exception as e:     # never lose the whole build because lip-sync failed
            report["warnings"].append(f"Lip-sync ({backend}) failed, used static clips instead: {e}")
            static = sorted(set(static) | set(lip))
    faces.update(photo_clips(image, segs, static, work, akey))
    report["timings"]["face_clips_s"] = round(time.time() - t0, 1)

    # 2) scenes, in parallel -----------------------------------------------------------
    t0 = time.time()
    scene_idx = [i for i, s in enumerate(segs) if s["mode"] == "scene"]
    scene_files, todo = {}, []
    for i in scene_idx:
        d = segs[i]["end"] - segs[i]["start"]
        f = work / f"scene_{i:03d}_{scene_key(segs[i]['scene'], work, d, preset['fps'], preset['jpeg'])}.mp4"
        scene_files[i] = f
        if not f.exists():
            todo.append(i)
    workers = workers or int(os.environ.get("SCENE_WORKERS", max(1, min(4, tools.cpu_count() // 2))))
    done = 0

    def job(i):
        render_scene(segs[i]["scene"], segs[i]["end"] - segs[i]["start"], scene_files[i], work, preset["fps"], preset["jpeg"])
        return i

    if todo:
        tick(0.3, f"Rendering {len(todo)} 3D scene(s) with {workers} worker(s)")
        with ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(job, i): i for i in todo}
            for fut in futs:
                try:
                    fut.result()
                except Exception as e:
                    i = futs[fut]
                    report["warnings"].append(f"Scene {i} failed to render ({e}); shown as speaker only")
                    scene_files.pop(i, None)
                done += 1
                tick(0.3 + 0.5 * done / len(todo), f"Rendered scene {done}/{len(todo)}")
    report["timings"]["scenes_s"] = round(time.time() - t0, 1)

    # 3) compose + concat --------------------------------------------------------------
    t0, parts = time.time(), []
    for i, s in enumerate(segs):
        tick(0.8 + 0.15 * i / n, f"Composing {i + 1}/{n}")
        d = s["end"] - s["start"]
        sc = scene_files.get(i) if s["mode"] == "scene" else None
        part = work / f"part_{i:03d}_{sha(faces[i].name, sc.name if sc else 'face', round(d, 2))}.mp4"
        if not part.exists():
            (compose_scene(sc, faces[i], d, part) if sc else compose_face(faces[i], d, part))
        parts.append(part)
    (work / "list.txt").write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", 0, "-i", work / "list.txt", "-c", "copy", work / "video.mp4"])
    final = work / "final.mp4"
    run(["ffmpeg", "-y", "-i", work / "video.mp4", "-i", audio, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", final])
    report["timings"]["compose_s"] = round(time.time() - t0, 1)
    report["timings"]["total_s"] = round(time.time() - t_start, 1)
    report["output"], report["video_seconds"] = str(final), round(audio_duration(audio), 1)
    write_json(work / "build_report.json", report)
    progress(1.0, f"Done in {fmt_time(report['timings']['total_s'])}")
    return str(final), report


def run_all(image, audio, quality="balanced", language="ar", notes="", hotwords="", voice_ref=None, use_llm=True,
            workdir="work", progress=lambda f, m: print(m)):
    """Headless: transcribe -> analyze -> build with no manual review."""
    work, segs = transcribe_stage(image, audio, language, hotwords, notes, workdir, progress)
    analyze_stage(work, segs, notes, use_llm, progress=progress)
    return build_stage(work, image, quality, voice_ref, language, progress=progress)
