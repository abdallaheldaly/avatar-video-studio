"""Speech-to-text with faster-whisper. Any CTranslate2 Whisper model works, including fine-tuned Arabic ones:
    WHISPER_MODEL=Omar10lfc/whisper-large-v3-turbo-arabic-ct2-int8"""
import os
import re
from collections import Counter

import numbers_ar
import tools

_cache = {}
_STOP = set("""هذا هذه ذلك التي الذي الذين على عن من إلى الى في مع هو هي هم نحن أنا انت كان كانت يكون تكون ليس لكن لكني أن إن
أو ثم قد لقد بعد قبل عند حتى كل بعض غير هناك هنا ايه إيه ده دي دا دول اللي علشان عشان لأن كمان برضه بس يعني طيب""".split())


def model_name():
    return os.environ.get("WHISPER_MODEL") or ("medium" if tools.is_mac() else "large-v3")


def _load():
    name = model_name()
    if name not in _cache:
        from faster_whisper import WhisperModel
        mac = tools.is_mac()   # no CUDA on Mac: CPU + int8
        _cache[name] = WhisperModel(name, device="cpu" if mac else "auto", compute_type="int8" if mac else "auto")
    return _cache[name]


def hotwords_from_notes(notes, n=40):
    """Frequent domain terms from the user's notes/script: biases Whisper toward the right spelling."""
    words = re.findall(r"[\u0600-\u06FFA-Za-z]{4,}", notes or "")
    common = [w for w, c in Counter(words).most_common(200) if c >= 2 and w not in _STOP]
    return " ".join(common[:n])


def transcribe(audio, language="ar", hotwords="", prompt="", normalize_numbers=True):
    """Returns [{start, end, text, raw}]. `text` has spoken Arabic numbers converted to digits; `raw` is the original."""
    model = _load()
    kw = dict(language=None if language in (None, "", "auto") else language, vad_filter=True, beam_size=5,
              condition_on_previous_text=False)   # avoids repetition loops
    if prompt.strip():
        kw["initial_prompt"] = prompt.strip()
    try:
        segs, _ = model.transcribe(str(audio), hotwords=hotwords.strip() or None, **kw)
        segs = list(segs)
    except TypeError:   # older faster-whisper without `hotwords`
        segs, _ = model.transcribe(str(audio), **kw)
        segs = list(segs)
    out = []
    for s in segs:
        raw = s.text.strip()
        if raw:
            text = numbers_ar.normalize(raw) if (language == "ar" and normalize_numbers) else raw
            out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text, "raw": raw})
    return out
