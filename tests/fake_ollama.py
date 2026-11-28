"""A tiny fake Ollama server (for tests only): answers /api/tags and /api/chat with schema-shaped JSON."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

CALLS = []


def _item(label, value, op="", ev=None):
    return {"label": label, "value": value, "op": op, "evidence": ev or f"{label} {value}"}


BASE = {"kind": "none", "title": "", "items": [], "result_label": "", "steps": [], "term": "", "definition": "",
        "unit": "", "icon_keywords": []}


def extraction(seg):
    x = dict(BASE)
    if "الإيرادات 500 ألف والمصروفات" in seg:
        x.update(kind="comparison", title="الإيرادات مقابل المصروفات", unit="ألف", icon_keywords=["revenue"],
                 items=[_item("الإيرادات", 500, ev="الإيرادات 500 ألف"), _item("المصروفات", 300, ev="المصروفات 300 ألف")])
    elif "الرواتب 50" in seg:
        x.update(kind="share", title="توزيع المصروفات", unit="%", icon_keywords=["money"],
                 items=[_item("الرواتب", 50), _item("الإيجار", 30), _item("التسويق", 20)])
    elif "ناقص" in seg:
        x.update(kind="calculation", title="صافي الربح", result_label="صافي الربح", icon_keywords=["profit"],
                 items=[_item("الإيرادات", 500, ev="الإيرادات 500"), _item("المصروفات", 300, "−", "المصروفات 300")])
    elif "الخطوة الأولى" in seg:
        x.update(kind="sequence", title="الخطوات", steps=["نحدد الإيرادات", "نحسب المصروفات", "نطرح"], icon_keywords=["calculator"])
    elif "الأرباح كبيرة" in seg:   # hallucinated numbers: must be rejected by the verifier
        x.update(kind="comparison", title="أرباح", items=[_item("الأرباح", 777), _item("الخسائر", 12)], steps=["الأرباح كبيرة", "الخسائر قليلة"])
    return x


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, o):
        b = json.dumps(o, ensure_ascii=False).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._send({"models": [{"name": "qwen3:8b"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        props = body["format"]["properties"]
        CALLS.append({"think": body.get("think"), "num_ctx": body["options"].get("num_ctx"), "schema": isinstance(body["format"], dict)})
        user = body["messages"][-1]["content"]
        if "outline" in props:
            out = {"title": "صافي الربح", "summary": "شرح حساب صافي الربح وتوزيع المصروفات", "domain": "محاسبة",
                   "outline": ["التعريف", "الحساب"], "key_terms": [{"term": "صافي الربح", "meaning": "الإيرادات ناقص المصروفات"}]}
        else:
            out = extraction(user.split("CURRENT SEGMENT (extract only from this):")[1])
        self._send({"message": {"content": json.dumps(out, ensure_ascii=False)}})


def start(port):
    s = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s
