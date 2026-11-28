"""Pick an icon that fits the topic from the Lucide set (ISC license) bundled in vendor/. No generation, no internet."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "vendor" / "icons" / "lucide"
# common business / accounting words -> a direct icon name (unknown names are ignored)
SYN = {"revenue": "banknote", "revenues": "banknote", "income": "coins", "sales": "shopping-cart", "profit": "trending-up",
       "profits": "trending-up", "loss": "trending-down", "expense": "receipt", "expenses": "receipt", "cost": "receipt",
       "invoice": "file-text", "tax": "percent", "taxes": "percent", "balance": "scale", "asset": "building-2",
       "assets": "building-2", "liability": "credit-card", "liabilities": "credit-card", "cash": "wallet",
       "inventory": "package", "salary": "hand-coins", "salaries": "hand-coins", "budget": "piggy-bank",
       "bank": "landmark", "loan": "landmark", "calculator": "calculator", "accounting": "calculator",
       "chart": "chart-column", "growth": "trending-up", "people": "users", "customer": "user", "customers": "users",
       "price": "tag", "equity": "chart-pie", "investment": "chart-line", "money": "banknote", "market": "store",
       "marketing": "megaphone", "contract": "file-signature", "report": "file-chart-column", "time": "clock"}
_tags = None


def _load():
    global _tags
    if _tags is None:
        _tags = json.loads((ROOT / "tags.json").read_text(encoding="utf-8")) if (ROOT / "tags.json").exists() else {}
        for p in ROOT.glob("*.svg"):
            _tags.setdefault(p.stem, [])
    return _tags


def find(keywords):
    """Name of the best icon for a list of English keywords, or None."""
    tags, scores = _load(), {}
    for w, kw in enumerate(k.lower().strip() for k in keywords if k and k.strip()):
        weight = 1.0 - 0.2 * w
        if SYN.get(kw) in tags:
            scores[SYN[kw]] = scores.get(SYN[kw], 0) + 5 * weight
        for name, tg in tags.items():
            s = 3 if kw == name else 2 if kw in name.split("-") else 2 if kw in tg else \
                1 if len(kw) >= 4 and any(kw in t for t in tg) else 0
            if s:
                scores[name] = scores.get(name, 0) + s * weight
    best = sorted(scores.items(), key=lambda kv: (-kv[1], len(kv[0])))
    return best[0][0] if best and best[0][1] >= 2 else None


def svg(name, color="#5eead4", width=1.6):
    s = (ROOT / f"{name}.svg").read_text(encoding="utf-8")
    return s.replace('stroke="currentColor"', f'stroke="{color}"').replace('stroke-width="2"', f'stroke-width="{width}"')
