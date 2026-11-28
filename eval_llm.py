"""Compare local models on YOUR machine: how well do they extract facts from Arabic transcript segments?

    python eval_llm.py                          # the model in LLM_MODEL (default qwen3:8b)
    python eval_llm.py --models qwen3:4b,qwen3:8b,qwen3:14b
    python eval_llm.py --cases my_cases.json    # your own labelled segments (same format as eval/cases.json)

Metrics (RAW model output, before the verifier):
  kind accuracy    the extracted `kind` is one of the accepted kinds
  number recall    expected numbers that the model extracted
  hallucination    extracted numbers that are NOT in the segment (the verifier rejects them, but a high rate = weak model)
  usable           numeric cases that end as a correct, verified numeric scene
  latency          seconds per segment"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import extract
import llm

HERE = Path(__file__).resolve().parent


def evaluate(cases, model):
    llm.MODEL = model
    ok, msg = llm.status()
    if not ok:
        raise SystemExit(f"[{model}] {msg}")
    rows, lat = [], []
    for c in cases:
        t = time.time()
        try:
            x = extract.extract_segment(c["text"])
        except Exception as e:
            x = {"kind": "error", "items": []}
            print(f"  ! {c['id']}: {e}")
        lat.append(time.time() - t)
        tn = extract.nums(c["text"])
        got = [float(i["value"]) for i in x.get("items", []) if isinstance(i.get("value"), (int, float))]
        sc, _ = extract.to_scene(x, c["text"]) if x.get("kind") != "error" else (None, [])
        scene_nums = {float(i["value"]) for i in (sc or {}).get("items", []) if isinstance(i, dict) and "value" in i}
        exp = set(map(float, c["numbers"]))
        rows.append({"id": c["id"], "kind": x.get("kind"), "kind_ok": x.get("kind") in c["kind_ok"],
                     "recall": (len(exp & set(got)) / len(exp)) if exp else None,
                     "halluc": sum(1 for v in got if v not in tn), "n_items": len(got),
                     "usable": (exp <= scene_nums and sc is not None) if exp else None})
    num = [r for r in rows if r["recall"] is not None]
    items = sum(r["n_items"] for r in rows)
    return {"model": model, "kind_acc": sum(r["kind_ok"] for r in rows) / len(rows),
            "recall": statistics.mean(r["recall"] for r in num) if num else 0,
            "halluc": (sum(r["halluc"] for r in rows) / items) if items else 0,
            "usable": sum(bool(r["usable"]) for r in num) / len(num) if num else 0,
            "latency": statistics.mean(lat), "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=llm.MODEL)
    ap.add_argument("--cases", default=str(HERE / "eval" / "cases.json"))
    a = ap.parse_args()
    cases = json.loads(Path(a.cases).read_text(encoding="utf-8"))
    results = [evaluate(cases, m.strip()) for m in a.models.split(",")]
    print(f"\n{'model':<16}{'kind acc':>10}{'num recall':>12}{'hallucin.':>11}{'usable':>9}{'s/segment':>11}")
    for r in results:
        print(f"{r['model']:<16}{r['kind_acc']:>10.0%}{r['recall']:>12.0%}{r['halluc']:>11.0%}{r['usable']:>9.0%}{r['latency']:>11.1f}")
    (HERE / "eval" / "report.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nPer-case details: eval/report.json")
    bad = [(r["model"], x["id"], x["kind"]) for r in results for x in r["rows"] if not x["kind_ok"]]
    if bad:
        print("Wrong kind:", ", ".join(f"{m}:{i}->{k}" for m, i, k in bad))


if __name__ == "__main__":
    sys.exit(main())
