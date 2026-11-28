"""Evaluate audio classification rules against tests/fixtures/audio_gold_set.json.

Usage:
  python -m api.eval_audio_classification
  python -m api.eval_audio_classification --gold tests/fixtures/audio_gold_set.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# Minimal env for config import
os.environ.setdefault("AURA_API_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("AURA_S3_ACCESS_KEY", "test")
os.environ.setdefault("AURA_S3_SECRET_KEY", "test")
os.environ.setdefault("AURA_S3_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("AURA_S3_BUCKET", "test")
os.environ.setdefault("AURA_SPACE_ID", "00000000-0000-0000-0000-000000000001")

from api.audio_ai import classify_with_rules  # noqa: E402


def load_gold(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError("gold set must contain a list of cases")
    return cases


def evaluate(cases: list[dict]) -> dict:
    labels = sorted({str(c.get("expected_category", "autre")) for c in cases} | {str(c.get("predicted_category", "")) for c in []})
    conf = defaultdict(lambda: defaultdict(int))
    results = []
    for c in cases:
        expected = str(c.get("expected_category", "autre"))
        labels = sorted(set(labels) | {expected})
        quality = {"ok": True, "duration_s": c.get("duration_s", 0), "tags": c.get("tags") or {}, "technical_score": 80}
        meta = {"display_name": c.get("display_name", ""), "folder_name": c.get("folder_name", "")}
        pred = classify_with_rules(metadata=meta, quality=quality)
        got = str(pred.get("suggested_category", "autre"))
        labels = sorted(set(labels) | {got})
        conf[expected][got] += 1
        results.append({
            "id": c.get("id"),
            "display_name": c.get("display_name"),
            "expected": expected,
            "got": got,
            "confidence": pred.get("confidence"),
            "ok": got == expected,
            "reason": pred.get("reason"),
        })

    per = {}
    for label in labels:
        tp = conf[label][label]
        fp = sum(conf[other][label] for other in labels if other != label)
        fn = sum(conf[label][other] for other in labels if other != label)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per[label] = {"tp": tp, "fp": fp, "fn": fn, "precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3)}
    total = len(results)
    correct = sum(1 for r in results if r["ok"])
    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3) if total else 0.0,
        "per_category": per,
        "confusion": {e: dict(g) for e, g in conf.items()},
        "results": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="tests/fixtures/audio_gold_set.json")
    ap.add_argument("--json", action="store_true", help="output JSON")
    args = ap.parse_args()
    cases = load_gold(Path(args.gold))
    report = evaluate(cases)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(f"Accuracy: {report['correct']}/{report['total']} ({report['accuracy']*100:.1f}%)")
    for label, m in report["per_category"].items():
        if m["tp"] + m["fp"] + m["fn"] == 0:
            continue
        print(f"- {label:20} P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f} (tp={m['tp']} fp={m['fp']} fn={m['fn']})")
    for r in report["results"]:
        if not r["ok"]:
            print(f"MISS {r['id']} expected={r['expected']} got={r['got']} conf={r['confidence']} name={r['display_name']}")
    return 0 if report["accuracy"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
