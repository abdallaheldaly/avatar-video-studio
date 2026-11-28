"""Convert spoken Arabic numbers (MSA + Egyptian) to digits so numeric scenes can be verified.

    "خمسمية ألف"        -> "500 ألف"
    "ثلاثمائة وخمسون ألف" -> "350 ألف"
    "مية وخمسين"        -> "150"
    "عشرين في المية"     -> "20 في المية"

Conservative on purpose: a lone small number ("تلات حاجات") is left as words; a group is converted only if it is
>= 10, or followed by a multiplier (ألف/مليون/مليار), a percent phrase, or a currency word."""
import re

UNITS = {"واحد": 1, "واحدة": 1, "وحدة": 1, "اتنين": 2, "إتنين": 2, "اثنين": 2, "إثنين": 2, "اثنان": 2, "إثنان": 2,
         "ثلاثة": 3, "تلاتة": 3, "ثلاث": 3, "تلات": 3, "أربعة": 4, "اربعة": 4, "أربع": 4, "اربع": 4,
         "خمسة": 5, "خمس": 5, "ستة": 6, "ست": 6, "سبعة": 7, "سبع": 7, "ثمانية": 8, "تمانية": 8, "ثماني": 8, "تمان": 8,
         "تمن": 8, "تسعة": 9, "تسع": 9, "عشرة": 10, "عشر": 10, "حداشر": 11, "اتناشر": 12, "إتناشر": 12, "تلتاشر": 13,
         "تلاتاشر": 13, "أربعتاشر": 14, "اربعتاشر": 14, "خمستاشر": 15, "ستاشر": 16, "سبعتاشر": 17, "تمنتاشر": 18,
         "تسعتاشر": 19}
TENS = {"عشرين": 20, "عشرون": 20, "ثلاثين": 30, "تلاتين": 30, "ثلاثون": 30, "أربعين": 40, "اربعين": 40, "أربعون": 40,
        "خمسين": 50, "خمسون": 50, "ستين": 60, "ستون": 60, "سبعين": 70, "سبعون": 70, "ثمانين": 80, "تمانين": 80,
        "ثمانون": 80, "تسعين": 90, "تسعون": 90}
HUNDREDS = {"مية": 100, "ميه": 100, "مائة": 100, "مئة": 100, "ميت": 100, "ميتين": 200, "مئتين": 200, "مائتين": 200,
            "مئتان": 200, "مائتان": 200, "تلتمية": 300, "تلاتمية": 300, "ثلاثمائة": 300, "ثلاثمئة": 300,
            "ربعمية": 400, "اربعمية": 400, "أربعمائة": 400, "اربعمائة": 400, "أربعمئة": 400, "خمسمية": 500,
            "خمسمائة": 500, "خمسمئة": 500, "ستمية": 600, "ستمائة": 600, "ستمئة": 600, "سبعمية": 700, "سبعمائة": 700,
            "سبعمئة": 700, "تمنمية": 800, "تمانمية": 800, "ثمانمائة": 800, "ثمانمئة": 800, "ثمانمية": 800,
            "تسعمية": 900, "تسعمائة": 900, "تسعمئة": 900}
MULT = {"ألف": 1000, "الف": 1000, "آلاف": 1000, "الاف": 1000, "مليون": 10 ** 6, "ملايين": 10 ** 6, "مليار": 10 ** 9,
        "مليارات": 10 ** 9}
CURRENCY = {"جنيه", "جنيها", "دولار", "ريال", "درهم", "دينار", "يورو"}
ALL = {**UNITS, **TENS, **HUNDREDS}
_PUNCT = "،,.:;!؟?()\"'"


def _strip(tok):
    core = tok.strip(_PUNCT)
    return core, tok[len(tok.rstrip(_PUNCT)):] if tok != core else ""


def _word(core):
    """number word for a token, allowing the attached conjunction 'و' (وخمسين)."""
    if core in ALL:
        return core
    if core.startswith("و") and core[1:] in ALL:
        return core[1:]
    return None


def normalize(text):
    toks, out, i = text.split(), [], 0
    while i < len(toks):
        core, trail = _strip(toks[i])
        w = _word(core)
        if w is None:
            out.append(toks[i]); i += 1; continue
        total, j, parts = 0, i, 0
        while j < len(toks):                       # collect "خمسمية وخمسين" style groups
            c, t = _strip(toks[j])
            ww = _word(c)
            if ww is None or (j > i and t_prev):
                break
            total += ALL[ww]; parts += 1
            t_prev = bool(t)
            j += 1
        nxt = _strip(toks[j])[0] if j < len(toks) else ""
        nxt2 = _strip(toks[j + 1])[0] if j + 1 < len(toks) else ""
        after = nxt in MULT or nxt in CURRENCY or nxt2 in ("المية", "الميه", "بالمية", "بالمائة") or nxt in ("%", "بالمائة")
        pct = nxt == "في" and nxt2 in ("المية", "الميه", "المائة", "المئة")
        if total >= 10 or after or pct:
            last_trail = _strip(toks[j - 1])[1]
            out.append(f"{total}{last_trail}")
        else:
            out.extend(toks[i:j])
        i = j
    return " ".join(out)


def digits(text):
    """Arabic-Indic digits and separators -> ASCII."""
    return text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,"))
