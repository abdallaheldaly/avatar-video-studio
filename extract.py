"""Extract-then-verify: the local LLM only EXTRACTS facts from a transcript segment (with the exact words as evidence);
plain code VERIFIES every number and decides the scene type. This keeps a small local model from inventing numbers."""
import re

import icons
import llm
import numbers_ar

SYSTEM = """You are a careful information extractor for a spoken Arabic lesson. You get ONE transcript segment.
Extract what is concretely said. You are NOT a designer. Never invent or infer anything that is not in the segment.
Answer in JSON.

kind (choose exactly one):
- none: greeting, transition, opinion, or nothing concrete
- comparison: two or more NAMED numbers that are compared (revenue vs expenses, values per period)
- share: parts of a whole given as numbers or percentages
- calculation: an arithmetic computation the speaker walks through (a - b = c)
- sequence: ordered steps or stages
- list: 2 to 4 unordered key points
- definition: one term being defined

Fields:
- title: short heading (max 6 words), same language as the segment
- items: for comparison/share: [{label, value, op:"", evidence}]. For calculation: the OPERANDS in the order spoken
  [{label, value, op, evidence}] where op is "" for the first and one of + - × ÷ for the others; do not include the result.
- result_label: for calculation, the name of the result (e.g. صافي الربح)
- steps: for sequence/list: short strings (max 8 words) built from what was said
- term, definition: for definition
- unit: the unit word if one is said (ألف, مليون, جنيه, %), else ""
- icon_keywords: 1 to 3 English words for a matching icon (money, bank, chart, scale, invoice, calculator, people...)
- evidence: for EVERY number copy the exact words from the segment that state it (verbatim, no paraphrase).
A number may appear only if it is literally in the segment. If unsure, use kind "none"."""

ITEM = {"type": "object", "required": ["label", "value", "op", "evidence"],
        "properties": {"label": {"type": "string"}, "value": {"type": "number"}, "op": {"type": "string"},
                       "evidence": {"type": "string"}}}
SCHEMA = {"type": "object", "required": ["kind", "title", "items", "result_label", "steps", "term", "definition", "unit",
                                         "icon_keywords"], "properties": {
    "kind": {"type": "string", "enum": ["none", "comparison", "share", "calculation", "sequence", "list", "definition"]},
    "title": {"type": "string"}, "result_label": {"type": "string"}, "term": {"type": "string"},
    "definition": {"type": "string"}, "unit": {"type": "string"},
    "items": {"type": "array", "items": ITEM}, "steps": {"type": "array", "items": {"type": "string"}},
    "icon_keywords": {"type": "array", "items": {"type": "string"}}}}

_DIAC = re.compile("[\u064b-\u0652\u0640]")


def _norm(s):
    return " ".join(_DIAC.sub("", numbers_ar.digits(str(s))).replace(",", "").split())


def nums(text):
    return {float(x) for x in re.findall(r"\d+(?:\.\d+)?", _norm(text))}


def extract_segment(text, lesson=None, prev="", nxt="", notes=""):
    """Raw extraction from the model (no verification)."""
    head = f"Lesson: {(lesson or {}).get('title', '')} - {(lesson or {}).get('summary', '')}\n" if lesson else ""
    ref = f"Reference notes (use ONLY to spell terms correctly, never as a source of numbers):\n{notes}\n" if notes else ""
    user = (f"{head}{ref}Previous segment (context only): {prev[:200]}\nNext segment (context only): {nxt[:200]}\n"
            f"CURRENT SEGMENT (extract only from this): {text}")
    return llm.chat_json(SYSTEM, user, SCHEMA, 800)


def _item_ok(it, text_nums, text_norm):
    """A numeric item is accepted only if its number is in the segment AND is backed by verbatim evidence or its label."""
    try:
        v = float(it["value"])
    except (KeyError, TypeError, ValueError):
        return False
    if v not in text_nums or not str(it.get("label", "")).strip():
        return False
    ev = _norm(it.get("evidence", ""))
    return (bool(ev) and ev in text_norm and v in nums(ev)) or _norm(it["label"]) in text_norm


def _apply(acc, op, v):
    op = (op or "").strip()
    return {"+": acc + v, "−": acc - v, "-": acc - v, "×": acc * v, "x": acc * v, "*": acc * v,
            "÷": acc / v if v else acc, "/": acc / v if v else acc}.get(op, acc)


def to_scene(x, text):
    """Verified scene from a raw extraction. Returns (scene or None, notes)."""
    notes, kind = [], x.get("kind", "none")
    if kind == "none":
        return None, notes
    tn, tnums = _norm(text), nums(text)
    title = (x.get("title") or "").strip()
    unit = (x.get("unit") or "").strip()
    sc = {"title": title}
    if unit:
        sc["unit"] = unit

    def texts(key="steps", lo=2, hi=5):
        s = [t.strip() for t in x.get(key, []) if t and t.strip()][:hi]
        return s if len(s) >= lo else []

    def fallback(reason):
        notes.append(reason + " - downgraded to bullet points" if texts(lo=2, hi=4) else reason + " - shown as speaker only")
        s = texts(lo=2, hi=4)
        return ({"type": "bullets", "title": title, "items": s} if s else None), notes

    if kind in ("comparison", "share", "calculation"):
        good = [i for i in x.get("items", []) if _item_ok(i, tnums, tn)]
        dropped = len(x.get("items", [])) - len(good)
        if dropped:
            notes.append(f"{dropped} number(s) rejected: not stated in the segment (or no matching evidence)")
        if kind == "comparison":
            if len(good) < 2:
                return fallback("numeric scene dropped")
            sc.update(type="compare" if len(good) == 2 else "bars", items=[{"label": i["label"], "value": i["value"]} for i in good[:6]])
        elif kind == "share":
            if len(good) < 2:
                return fallback("share chart dropped")
            sc.update(type="donut", items=[{"label": i["label"], "value": i["value"]} for i in good[:6]])
        else:
            if len(good) < 2:
                return fallback("calculation dropped")
            acc, lines = float(good[0]["value"]), [{"text": good[0]["label"], "value": good[0]["value"], "op": ""}]
            for i in good[1:]:
                acc = _apply(acc, i.get("op", ""), float(i["value"]))
                lines.append({"text": i["label"], "value": i["value"], "op": (i.get("op") or "+").strip()})
            lines.append({"text": (x.get("result_label") or "Result").strip(), "value": round(acc, 6), "op": "=", "result": True})
            sc.update(type="equation", items=lines)
    elif kind in ("sequence", "list"):
        s = texts("steps", 2, 5)
        if not s:
            return None, ["not enough items"]
        sc.update(type="steps" if kind == "sequence" else "bullets", items=s)
    elif kind == "definition":
        term, d = (x.get("term") or "").strip(), (x.get("definition") or "").strip()
        if not term or not d:
            return None, ["incomplete definition"]
        sc.update(type="image", title=term, caption=d)
    else:
        return None, notes
    return sc, notes


def plan_segment(x, text, work, idx):
    """Raw extraction -> (mode, scene, notes); writes the icon file next to the plan."""
    sc, notes = to_scene(x, text)
    if not sc:
        return "face", None, notes
    icon = icons.find(x.get("icon_keywords", []))
    if sc["type"] == "image" and not icon:
        notes.append("definition without a matching icon - shown as speaker only")
        return "face", None, notes
    if icon:
        name = f"ill_{idx:03d}.svg"
        (work / name).write_text(icons.svg(icon), encoding="utf-8")
        sc["illustration_file"] = name
    return "scene", sc, notes
