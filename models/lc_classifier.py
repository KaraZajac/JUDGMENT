"""Lower-court direction classifier: opinion text -> SCDB lcDispositionDirection.

Purpose: assist (not replace) the hand-coding of lc_direction for pending cases
— the deployed model's most valuable feature. Trained on historical pairs
harvested by pipeline.lc_opinions (data/text/lc-matches.yaml + data/text/lc/),
labels from SCDB. Human-in-the-loop by design: this prints suggestions and
disagreements with models/pending_lc.yaml; it never writes coding files.

  .venv/bin/python -m models.lc_classifier            # train + eval + apply to pending
"""

import json
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
LC_TEXTS = ROOT / "data" / "text" / "lc"
MATCHES = ROOT / "data" / "text" / "lc-matches.yaml"
PENDING_LC = Path(__file__).resolve().parent / "pending_lc.yaml"
OUT = Path(__file__).resolve().parent / "output"

MIN_TRAIN = 120  # below this, per-fold estimates are noise — keep harvesting
LABELS = {1: "conservative", 2: "liberal"}


def load_training():
    if not MATCHES.exists():
        raise SystemExit("no lc-matches.yaml yet — run pipeline.lc_opinions --harvest")
    matches = (yaml.safe_load(MATCHES.read_text()) or {}).get("matches", {})
    texts, labels, terms = [], [], []
    for cid, m in matches.items():
        label = m.get("lc_direction_label")
        path = LC_TEXTS / f"{cid}.json"
        if label not in (1, 2) or not path.exists():
            continue
        texts.append(json.loads(path.read_text())["text"])
        labels.append(label)
        terms.append(int(cid[:4]))
    return texts, np.array(labels), np.array(terms)


def build_pipeline():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    return make_pipeline(
        TfidfVectorizer(max_features=30000, ngram_range=(1, 2), min_df=2,
                        stop_words="english", sublinear_tf=True),
        LogisticRegression(C=1.0, max_iter=3000, class_weight="balanced"),
    )


def evaluate(texts, labels, terms):
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    accs, aucs = [], []
    gkf = GroupKFold(n_splits=min(5, len(np.unique(terms))))
    for tr, te in gkf.split(texts, labels, groups=terms):
        clf = build_pipeline()
        clf.fit([texts[i] for i in tr], labels[tr])
        p = clf.predict_proba([texts[i] for i in te])[:, list(clf.classes_).index(2)]
        accs.append(float((np.where(p >= 0.5, 2, 1) == labels[te]).mean()))
        if len(set(labels[te])) == 2:
            aucs.append(float(roc_auc_score(labels[te] == 2, p)))
    return {
        "n": int(len(labels)),
        "class_balance_liberal": round(float((labels == 2).mean()), 3),
        "cv_accuracy": round(float(np.mean(accs)), 4),
        "cv_auc": round(float(np.mean(aucs)), 4) if aucs else None,
        "folds": len(accs),
    }


def apply_to_pending(clf):
    handmap = yaml.safe_load(PENDING_LC.read_text()) if PENDING_LC.exists() else {}
    rows = []
    for path in sorted(LC_TEXTS.glob("pending-*.json")):
        data = json.loads(path.read_text())
        case_id = data["caseId"].removeprefix("pending-")
        p_lib = float(clf.predict_proba([data["text"]])[0][
            list(clf.classes_).index(2)])
        pred = "liberal" if p_lib >= 0.5 else "conservative"
        hand = (handmap.get(case_id) or {}).get("lc_direction")
        rows.append({"id": case_id, "predicted": pred,
                     "p_liberal": round(p_lib, 3), "hand_coded": hand,
                     "agrees": (hand == pred) if hand else None})
    return rows


def main():
    texts, labels, terms = load_training()
    print(f"training pairs with text: {len(labels)} "
          f"(terms {terms.min() if len(terms) else '—'}–{terms.max() if len(terms) else '—'})")
    if len(labels) < MIN_TRAIN:
        print(f"insufficient training data (< {MIN_TRAIN}) — keep running harvest "
              f"tranches; the daily workflow accumulates ~30 matches/run")
        return

    metrics = evaluate(texts, labels, terms)
    print(f"grouped-CV: acc={metrics['cv_accuracy']} auc={metrics['cv_auc']} "
          f"(n={metrics['n']}, liberal share {metrics['class_balance_liberal']})")

    clf = build_pipeline()
    clf.fit(texts, labels)
    rows = apply_to_pending(clf)
    payload = {"training": metrics, "pending": rows}
    OUT.mkdir(exist_ok=True)
    with open(OUT / "metrics-lc-classifier.yaml", "w") as f:
        yaml.safe_dump(payload, f, sort_keys=False)

    if rows:
        print("\npending cases (suggestion vs hand-code):")
        for r in rows:
            mark = ("AGREES" if r["agrees"] else
                    "DISAGREES" if r["agrees"] is False else "uncoded")
            print(f"  {r['id']:<18} {r['predicted']:<12} p_lib={r['p_liberal']:.2f} "
                  f"hand={r['hand_coded'] or '—':<12} {mark}")
        print("\nsuggestions only — update models/pending_lc.yaml by hand where "
              "the evidence convinces you (human-in-the-loop by design).")


if __name__ == "__main__":
    main()
