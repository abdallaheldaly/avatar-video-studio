"""Minimal client for a local open-source LLM served by Ollama (MIT license).
Everything stays on localhost: no external API, no API key."""
import json
import os
import re
import urllib.error
import urllib.request

HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1:11500")
HOST = HOST if HOST.startswith("http") else "http://" + HOST
MODEL = os.environ.get("LLM_MODEL", "qwen3:8b")     # Apache 2.0. For small RAM use qwen3:4b
CTX = int(os.environ.get("LLM_CTX", "8192"))        # Ollama's default (2048) is too small, so we set it explicitly


def _post(path, body, timeout=900):
    req = urllib.request.Request(HOST + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def status():
    """Returns (ok, message)."""
    try:
        with urllib.request.urlopen(HOST + "/api/tags", timeout=3) as r:
            names = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return False, f"Ollama is not running at {HOST}"
    if MODEL in names or (":" not in MODEL and f"{MODEL}:latest" in names):
        return True, f"{MODEL} is ready"
    return False, f"Model {MODEL} is not installed (run: ollama pull {MODEL})"


def _parse(txt):
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
    starts = [i for i in (txt.find("{"), txt.find("[")) if i >= 0]
    return json.loads(txt[min(starts): max(txt.rfind("}"), txt.rfind("]")) + 1])


def chat_json(system, user, schema=None, max_tokens=1200, temperature=0.2, retries=2):
    """Ask for a JSON reply (constrained by a schema when given). Retries when the JSON is broken."""
    body = {"model": MODEL, "stream": False, "keep_alive": "2m", "think": False,
            "format": schema or "json",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"num_ctx": CTX, "temperature": temperature, "num_predict": max_tokens}}
    last = None
    for _ in range(retries):
        try:
            try:
                out = _post("/api/chat", body)
            except urllib.error.HTTPError as e:
                if e.code != 400 or "think" not in body:
                    raise
                body.pop("think")          # model without `think` support
                out = _post("/api/chat", body)
            return _parse(out["message"]["content"])
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            last = e
    raise RuntimeError(f"The model returned invalid JSON: {last}")
