"""Integration test: fake Ollama + real headless Chromium (set CHROMIUM_PATH if Playwright's browser isn't installed)."""
import json, os, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_ollama
import asr, llm
import pipeline as P

SEGS = [
    {"start": 0.0, "end": 9.0, "text": "الإيرادات 500 ألف والمصروفات 300 ألف", "raw": ""},
    {"start": 9.0, "end": 18.0, "text": "الرواتب 50 في المية والإيجار 30 في المية والتسويق 20 في المية", "raw": ""},
    {"start": 18.0, "end": 27.0, "text": "الإيرادات 500 ناقص المصروفات 300", "raw": ""},
    {"start": 27.0, "end": 36.0, "text": "الخطوة الأولى نحدد الإيرادات والتانية المصروفات", "raw": ""},
    {"start": 36.0, "end": 45.0, "text": "أهلاً بيكم في الحلقة", "raw": ""},
    {"start": 45.0, "end": 54.0, "text": "الأرباح كبيرة جداً الحمد لله", "raw": ""},
]


def ff(*a):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, a)], check=True)


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        fake_ollama.start(11601)
        llm.HOST = "http://127.0.0.1:11601"
        cls.img, cls.aud = cls.tmp / "me.png", cls.tmp / "talk.m4a"
        ff("-f", "lavfi", "-i", "testsrc2=s=800x1000:d=1", "-frames:v", "1", cls.img)
        ff("-f", "lavfi", "-i", "sine=frequency=300:duration=54", "-c:a", "aac", cls.aud)
        asr.transcribe = lambda *a, **k: [dict(s) for s in SEGS]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_full_flow(self):
        wd = str(self.tmp / "work")
        work, segs = P.transcribe_stage(self.img, self.aud, "ar", "", "", wd)
        self.assertEqual(len(segs), 6)
        self.assertTrue((work / "audio.wav").exists())                       # m4a -> wav
        lesson, plan = P.analyze_stage(work, segs, "", True, 8)
        self.assertTrue(lesson["llm_ok"])
        types = [s["scene"]["type"] if s["scene"] else "face" for s in plan]
        self.assertEqual(types, ["compare", "donut", "equation", "steps", "face", "bullets"])
        eq = plan[2]["scene"]["items"]
        self.assertEqual(eq[-1]["value"], 200)                              # result computed by code
        self.assertTrue(any("rejected" in w for w in plan[5]["warnings"]))  # hallucinated numbers rejected, downgraded to bullets
        self.assertEqual(fake_ollama.CALLS[0]["think"], False)
        self.assertEqual(fake_ollama.CALLS[0]["num_ctx"], 8192)

        t = time.time()
        final, rep = P.build_stage(work, self.img, "draft", workers=4)
        first = time.time() - t
        dur = P.audio_duration(final)
        self.assertAlmostEqual(dur, 54.0, delta=0.2)
        print(f"\nfirst build (draft, 4 scenes in parallel): {first:.1f}s  report={rep['timings']}")

        t = time.time()
        P.build_stage(work, self.img, "draft", workers=4)                   # fully cached
        second = time.time() - t
        print(f"cached rebuild: {second:.1f}s")
        self.assertLess(second, first / 2)

        plan = json.loads((work / "plan.json").read_text())                  # edit ONE number
        plan[0]["scene"]["items"][1]["value"] = 350
        (work / "plan.json").write_text(json.dumps(plan, ensure_ascii=False))
        before = set(p.name for p in work.glob("scene_*.mp4"))
        P.build_stage(work, self.img, "draft", workers=4)
        new = set(p.name for p in work.glob("scene_*.mp4")) - before
        self.assertEqual(len(new), 1, new)                                   # only that scene re-rendered
        print("edited 1 number -> re-rendered", len(new), "scene")

        orig = P.render_scene                                                # a failing scene must not kill the build
        def boom(scene, dur, out, work, fps, jpeg):
            if scene.get("type") == "steps":
                raise RuntimeError("chromium crashed")
            return orig(scene, dur, out, work, fps, jpeg)
        P.render_scene = boom
        plan = json.loads((work / "plan.json").read_text())
        plan[3]["scene"]["items"][0] = "changed to force a re-render"
        (work / "plan.json").write_text(json.dumps(plan, ensure_ascii=False))
        final, rep = P.build_stage(work, self.img, "draft", workers=4)
        P.render_scene = orig
        self.assertTrue(os.path.exists(final))
        self.assertTrue(any("failed to render" in w for w in rep["warnings"]), rep["warnings"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
