"""Gradio UI: 1) Transcribe  ->  2) Analyze  ->  3) Build.  Review and fix the result of every step before the next one."""
import json
import os
from pathlib import Path

import gradio as gr

import pipeline as P

LANGS = {"Arabic": "ar", "English": "en", "Auto-detect": "auto"}


def _path(f):
    return None if not f else (f if isinstance(f, str) else f.name)


def _read_notes(f):
    p = _path(f)
    return Path(p).read_text(encoding="utf-8", errors="ignore") if p else ""


def transcribe(image, audio, language, hotwords, notes_file, progress=gr.Progress()):
    if not image or not audio:
        raise gr.Error("Upload your photo/video and the audio file first.")
    work, segs = P.transcribe_stage(_path(image), _path(audio), LANGS[language], hotwords, _read_notes(notes_file),
                                    progress=lambda f, m: progress(f, desc=m))
    rows = [[s["start"], s["end"], s["text"]] for s in segs]
    return str(work), rows, "Fix any wrong words or numbers in the table, then click **2) Analyze**."


def _rows(df):
    rows = df.values.tolist() if hasattr(df, "values") else df
    return [{"start": float(r[0]), "end": float(r[1]), "text": str(r[2]).strip()} for r in rows if str(r[2]).strip()]


def lesson_md(lesson, segs):
    L = [f"### {lesson.get('title') or 'Lesson'}", lesson.get("summary", ""), ""]
    if not lesson.get("llm_ok"):
        L += ["> ⚠️ The local model is not running, so the plan is basic. Start Ollama (`python studio.py run` does it) "
              "and analyze again.", ""]
    if lesson.get("domain"):
        L.append(f"**Domain:** {lesson['domain']}")
    if lesson.get("outline"):
        L += ["", "**Outline:**"] + [f"{i + 1}. {x}" for i, x in enumerate(lesson["outline"])]
    if lesson.get("key_numbers"):
        L += ["", "**Numbers found in the audio:** " + " • ".join(lesson["key_numbers"])]
    L += ["", f"**Plan:** {len(segs)} segments, {sum(s['mode'] == 'scene' for s in segs)} with a 3D scene."]
    warns = [(i, w) for i, s in enumerate(segs) for w in s.get("warnings", [])]
    if warns:
        L += ["", "#### ⚠️ Review before building"] + [f"- segment {i}: {w}" for i, w in warns]
    return "\n".join(L)


def analyze(work, table, notes_file, use_llm, min_len, progress=gr.Progress()):
    if not work:
        raise gr.Error("Run step 1 first.")
    lesson, segs = P.analyze_stage(work, _rows(table), _read_notes(notes_file), use_llm, float(min_len),
                                   progress=lambda f, m: progress(f, desc=m))
    return lesson_md(lesson, segs), json.dumps(segs, ensure_ascii=False, indent=1)


def build(work, image, plan_text, quality, language, voice_ref, progress=gr.Progress()):
    if not work:
        raise gr.Error("Run steps 1 and 2 first.")
    try:
        segs = json.loads(plan_text)
    except Exception as e:
        raise gr.Error(f"The plan JSON has a mistake: {e}")
    P.write_json(Path(work) / "plan.json", segs)
    final, rep = P.build_stage(work, _path(image), quality, _path(voice_ref), LANGS[language],
                               progress=lambda f, m: progress(f, desc=m))
    t = rep["timings"]
    md = [f"**Done** in {P.fmt_time(t['total_s'])} for {P.fmt_time(rep['video_seconds'])} of video "
          f"(face clips {t['face_clips_s']}s, 3D scenes {t['scenes_s']}s, compose {t['compose_s']}s)."]
    md += [f"- ⚠️ {w}" for w in rep["warnings"]]
    return final, "\n".join(md)


with gr.Blocks(title="Avatar Video Studio") as demo:
    gr.Markdown("## Avatar Video Studio\nYour photo + your audio → a video with your face and 3D explainer scenes. "
                "100% local and open source.")
    with gr.Row():
        img = gr.File(file_types=["image", "video"], label="Your photo, or a 10-20 s video of you (silent, face to camera)")
        aud = gr.File(file_types=["audio"], label="Audio (m4a / mp3 / wav), e.g. from NotebookLM")
    with gr.Row():
        lang = gr.Dropdown(list(LANGS), value="Arabic", label="Spoken language")
        quality = gr.Dropdown(["draft", "balanced", "high"], value="balanced",
                              label="Quality: draft = fastest (no lip-sync), balanced, high = everything lip-synced")
        use_llm = gr.Checkbox(True, label="Understand the lesson with the local model (Ollama)")
    with gr.Accordion("Optional: improve accuracy", open=False):
        hot = gr.Textbox(label="Key terms (space separated), helps Whisper spell your topic correctly")
        notes = gr.File(file_types=[".txt", ".md"], label="Your script / notes (.txt or .md): used for term spelling and context")
        min_len = gr.Slider(4, 20, value=8, step=1, label="Minimum segment length (seconds)")
        ref = gr.File(file_types=["audio"], label="Voice cloning: 10-30 s recording of your voice (needs `pip install coqui-tts`)")
    work = gr.State("")
    b1 = gr.Button("1) Transcribe", variant="primary")
    hint = gr.Markdown()
    table = gr.Dataframe(headers=["start", "end", "text"], datatype=["number", "number", "str"], interactive=True,
                         wrap=True, label="Transcript (editable)")
    b2 = gr.Button("2) Analyze the lesson", variant="primary")
    summary = gr.Markdown()
    plan_box = gr.Code(language="json", interactive=True, lines=18, label="Scene plan (editable: numbers, titles, mode)")
    b3 = gr.Button("3) Build the video", variant="primary")
    out = gr.Video(label="Final video")
    report = gr.Markdown()
    b1.click(transcribe, [img, aud, lang, hot, notes], [work, table, hint])
    b2.click(analyze, [work, table, notes, use_llm, min_len], [summary, plan_box])
    b3.click(build, [work, img, plan_box, quality, lang, ref], [out, report])

demo.launch(share=os.environ.get("SHARE") == "1")  # local only by default; SHARE=1 for a public link (Colab)
