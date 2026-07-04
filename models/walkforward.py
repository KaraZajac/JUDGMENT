"""Walk-forward evaluation: train on terms <= T-1, predict every vote of term T.

No random splits, ever — random splits leak court composition and era effects.
The eval window defaults to 1956–2024 (ten burn-in terms of training data).

Targets:
  reverse  — justice votes to disturb the judgment below (primary; comparable
             to Katz–Bommarito–Blackman 2017, who report 71.9% justice-vote
             and 70.2% case accuracy on a different, longer window)
  liberal  — SCDB directional vote (secondary; inherits direction-coding caveats)

Baselines (all computed strictly from the training window):
  base_rate   — the training-window base rate as a constant probability
  justice     — the justice's lagged EB-shrunk prior rate (career behavior)
  attitudinal — classic heuristic: P(reverse) = P(justice disagrees with the
                ideological direction of the decision below), from lagged lean
  party       — (liberal target) P(liberal | appointing party) fit on train

Model: HistGradientBoostingClassifier over the leak-free feature table
(native categoricals + missing handling). Case outcomes are aggregated from
per-justice probabilities by Poisson-binomial majority (independence
assumption — reported as a limitation).

Usage:
  .venv/bin/python -m models.walkforward                     # both targets, full window
  .venv/bin/python -m models.walkforward --target reverse --start 2018   # smoke
  .venv/bin/python -m models.walkforward --ablations         # feature-group ablations
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.stats import binomtest
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from .features import CAT_FEATURES, NUM_FEATURES, load

OUT = Path(__file__).resolve().parent / "output"
CACHE = OUT / "cache"

MODEL_PARAMS = dict(
    max_iter=400, learning_rate=0.06, max_leaf_nodes=31, min_samples_leaf=40,
    l2_regularization=1.0, early_stopping=True, validation_fraction=0.15,
    n_iter_no_change=25, random_state=7,
)

ABLATIONS = {
    "full": None,  # all features
    "no_case": [c for c in CAT_FEATURES + NUM_FEATURES
                if c in ("justice_cat", "appointer_party", "term", "tenure", "is_chief",
                         "n_prior", "prior_reverse", "prior_reverse_3t", "prior_liberal",
                         "prior_liberal_3t", "prior_majority_rate", "prior_dissent_rate",
                         "court_prior_reverse_3t")],
    "no_justice": [c for c in CAT_FEATURES + NUM_FEATURES
                   if c not in ("justice_cat", "appointer_party", "tenure", "is_chief",
                                "n_prior", "prior_reverse", "prior_reverse_3t",
                                "prior_liberal", "prior_liberal_3t", "prior_issue_liberal",
                                "prior_majority_rate", "prior_dissent_rate")],
    "no_ideology": [c for c in CAT_FEATURES + NUM_FEATURES
                    if c not in ("appointer_party", "prior_liberal", "prior_liberal_3t",
                                 "prior_issue_liberal")],
}

# Exactly the features available for a granted-but-undecided case in this repo
# (cert-stage facts + justice history). The deployed forecaster trains and is
# validated on THIS subset so its missing-value patterns match deployment —
# the full model routes never-seen missingness constellations into unreliable
# leaves (observed: degenerate p≈1.0 forecasts).
PENDING_CONFIG = [
    "issue_area", "jurisdiction", "appointer_party", "justice_cat",
    "term", "tenure", "is_chief", "us_petitioner", "us_respondent",
    "n_prior", "prior_reverse", "prior_reverse_3t",
    "prior_liberal", "prior_liberal_3t", "prior_issue_liberal",
    "prior_majority_rate", "prior_dissent_rate", "court_prior_reverse_3t",
]


# ---------------------------------------------------------------- metrics

def brier(y, p):
    return float(np.mean((p - y) ** 2))


def logloss(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def ece(y, p, bins=10):
    idx = np.clip((p * bins).astype(int), 0, bins - 1)
    total, err = len(y), 0.0
    for b in range(bins):
        m = idx == b
        if m.sum():
            err += m.sum() / total * abs(p[m].mean() - y[m].mean())
    return float(err)


def reliability(y, p, bins=10):
    idx = np.clip((p * bins).astype(int), 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        if m.sum():
            rows.append({"bin": f"{b / bins:.1f}–{(b + 1) / bins:.1f}",
                         "n": int(m.sum()),
                         "mean_p": round(float(p[m].mean()), 3),
                         "frac_positive": round(float(y[m].mean()), 3)})
    return rows


def metric_block(y, p):
    out = {
        "n": int(len(y)),
        "accuracy": round(float(((p >= 0.5) == y).mean()), 4),
        "brier": round(brier(y, p), 4),
        "log_loss": round(logloss(y, p), 4),
        "ece": round(ece(y, p), 4),
    }
    if 0 < y.mean() < 1:
        out["auc"] = round(float(roc_auc_score(y, p)), 4)
    return out


def mcnemar(y, p_a, p_b):
    """A right & B wrong vs B right & A wrong, exact binomial p-value."""
    a_right = (p_a >= 0.5) == y
    b_right = (p_b >= 0.5) == y
    b_ = int((a_right & ~b_right).sum())
    c_ = int((~a_right & b_right).sum())
    if b_ + c_ == 0:
        return {"a_only_right": 0, "b_only_right": 0, "p_value": 1.0}
    p = binomtest(min(b_, c_), b_ + c_, 0.5).pvalue
    return {"a_only_right": b_, "b_only_right": c_, "p_value": float(f"{p:.2e}")}


# ---------------------------------------------------------------- baselines

def baseline_probs(train, test, target):
    out = {}
    base = train[target].mean()
    out["base_rate"] = np.full(len(test), base)

    if target == "y_reverse":
        out["justice"] = test["prior_reverse"].fillna(base).to_numpy()
        # attitudinal: reverse iff the decision below leans against the justice
        lean = test["prior_liberal"].fillna(0.5).to_numpy()
        lc = test["lc_direction"].to_numpy()
        att = np.where(lc == 1.0, lean, np.where(lc == 2.0, 1.0 - lean, base))
        out["attitudinal"] = att
    else:
        out["justice"] = test["prior_liberal"].fillna(base).to_numpy()
        rates = train.groupby("appointer_party")[target].mean()
        party = test["appointer_party"].map(rates).fillna(base).to_numpy()
        out["party"] = party
    return out


# ---------------------------------------------------------------- engine

def fit_predict(train, test, target, feature_subset=None):
    cats = [c for c in CAT_FEATURES if feature_subset is None or c in feature_subset]
    nums = [c for c in NUM_FEATURES if feature_subset is None or c in feature_subset]
    cols = cats + nums
    X_train = train[cols].copy()
    X_test = test[cols].copy()
    for c in cats:
        joint = pd.concat([X_train[c], X_test[c]])
        categories = joint.dropna().unique()
        X_train[c] = pd.Categorical(X_train[c], categories=categories)
        X_test[c] = pd.Categorical(X_test[c], categories=categories)
    clf = HistGradientBoostingClassifier(
        categorical_features=[i for i in range(len(cats))], **MODEL_PARAMS)
    clf.fit(X_train, train[target])
    return clf.predict_proba(X_test)[:, 1]


def case_level(test_rows):
    """Poisson-binomial majority aggregation per case."""
    recs = []
    for cid, g in test_rows.groupby("caseId"):
        probs = g["p_model"].to_numpy()
        y_case = g["case_reversed"].iloc[0]
        if np.isnan(y_case) or len(probs) < 2:
            continue
        dist = np.zeros(len(probs) + 1)
        dist[0] = 1.0
        for p in probs:
            dist[1:] = dist[1:] * (1 - p) + dist[:-1] * p
            dist[0] *= 1 - p
        need = len(probs) // 2 + 1
        recs.append({"caseId": cid, "term": g["term"].iloc[0],
                     "y": float(y_case), "p": float(dist[need:].sum())})
    return pd.DataFrame(recs)


# ---------------------------------------------------------------- harness

def run(target, start, end, feature_subset=None, tag="full", with_theta=False):
    df = load()
    label = "y_reverse" if target == "reverse" else "y_liberal"
    df = df.dropna(subset=[label]).copy()
    df[label] = df[label].astype(float)

    if with_theta:
        theta_path = CACHE / "theta_filtered.pkl"
        if not theta_path.exists():
            raise SystemExit("run `.venv/bin/python -m models.ideal_points --filtered` first")
        theta = pd.read_pickle(theta_path)
        df = df.merge(theta, on=["justiceName", "term"], how="left")
        if "theta_lag" not in NUM_FEATURES:
            NUM_FEATURES.append("theta_lag")

    rows = []
    for T in range(start, end + 1):
        train = df[df["term"] < T]
        test = df[df["term"] == T]
        if len(test) == 0 or len(train) < 2000:
            continue
        p_model = fit_predict(train, test, label, feature_subset)
        bl = baseline_probs(train, test, label)
        chunk = test[["caseId", "term", "justiceName", label, "case_reversed"]].copy()
        chunk = chunk.rename(columns={label: "y"})
        chunk["p_model"] = p_model
        for name, p in bl.items():
            chunk[f"p_{name}"] = p
        rows.append(chunk)
        acc = float(((p_model >= 0.5) == test[label]).mean())
        print(f"  {tag}/{target} term {T}: n={len(test):,} acc={acc:.3f}", flush=True)

    res = pd.concat(rows, ignore_index=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    res.to_pickle(CACHE / f"predictions-{target}-{tag}.pkl")
    return res


def summarize(res, target, tag="full"):
    y = res["y"].to_numpy()
    models = {"model": res["p_model"].to_numpy()}
    for c in res.columns:
        if c.startswith("p_") and c not in ("p_model",):
            models[c[2:]] = res[c].to_numpy()

    summary = {
        "target": target, "tag": tag,
        "eval_terms": [int(res["term"].min()), int(res["term"].max())],
        "vote_level": {name: metric_block(y, p) for name, p in models.items()},
        "comparisons": {name: mcnemar(y, models["model"], p)
                        for name, p in models.items() if name != "model"},
        "calibration_model": reliability(y, models["model"]),
    }

    cases = case_level(res)
    if len(cases):
        summary["case_level_model"] = metric_block(
            cases["y"].to_numpy(), cases["p"].to_numpy())

    by_decade = {}
    for dec, g in res.groupby(res["term"] // 10 * 10):
        by_decade[f"{dec}s"] = {
            "model": metric_block(g["y"].to_numpy(), g["p_model"].to_numpy()),
            "justice_baseline": metric_block(g["y"].to_numpy(), g["p_justice"].to_numpy()),
        }
    summary["by_decade"] = by_decade

    per_j = []
    for jn, g in res.groupby("justiceName"):
        if len(g) < 300:
            continue
        per_j.append({"justice": jn, "n": int(len(g)),
                      "accuracy": round(float(((g["p_model"] >= 0.5) == g["y"]).mean()), 4),
                      "brier": round(brier(g["y"].to_numpy(), g["p_model"].to_numpy()), 4)})
    summary["by_justice"] = sorted(per_j, key=lambda r: -r["accuracy"])
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["reverse", "liberal", "both"], default="both")
    ap.add_argument("--start", type=int, default=1956)
    ap.add_argument("--end", type=int, default=2024)
    ap.add_argument("--ablations", action="store_true")
    ap.add_argument("--theta", action="store_true",
                    help="add leak-free lagged ideal points as a feature (tag: with_theta)")
    ap.add_argument("--pending-config", action="store_true",
                    help="validate the deployment feature subset used by models.predict")
    args = ap.parse_args()

    if args.pending_config:
        for target in (["reverse", "liberal"] if args.target == "both" else [args.target]):
            print(f"=== walk-forward, pending-config subset: {target} ===")
            res = run(target, args.start, args.end, PENDING_CONFIG, tag="pending_config")
            summary = summarize(res, target, tag="pending_config")
            with open(OUT / f"metrics-{target}-pending-config.yaml", "w") as f:
                yaml.safe_dump(summary, f, sort_keys=False)
            vm = summary["vote_level"]["model"]
            print(f"pending_config/{target}: acc={vm['accuracy']} "
                  f"brier={vm['brier']} auc={vm.get('auc')}")
        return

    if args.theta:
        target = "reverse" if args.target == "both" else args.target
        print(f"=== walk-forward with ideal points: {target} ===")
        res = run(target, max(args.start, 1990), args.end, tag="with_theta", with_theta=True)
        summary = summarize(res, target, tag="with_theta")
        with open(OUT / f"metrics-{target}-with-theta.yaml", "w") as f:
            yaml.safe_dump(summary, f, sort_keys=False)
        vm = summary["vote_level"]["model"]
        print(f"with_theta: acc={vm['accuracy']} brier={vm['brier']}")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    targets = ["reverse", "liberal"] if args.target == "both" else [args.target]

    if args.ablations:
        results = {}
        for name, subset in ABLATIONS.items():
            print(f"ablation: {name}")
            res = run("reverse", max(args.start, 1990), args.end, subset, tag=name)
            results[name] = metric_block(res["y"].to_numpy(), res["p_model"].to_numpy())
        with open(OUT / "metrics-ablations.yaml", "w") as f:
            yaml.safe_dump({"eval_terms": [max(args.start, 1990), args.end],
                            "target": "reverse", "ablations": results}, f, sort_keys=False)
        print(yaml.safe_dump(results, sort_keys=False))
        return

    for target in targets:
        print(f"=== walk-forward: {target} ({args.start}–{args.end}) ===")
        res = run(target, args.start, args.end)
        summary = summarize(res, target)
        with open(OUT / f"metrics-{target}.yaml", "w") as f:
            yaml.safe_dump(summary, f, sort_keys=False)
        vm = summary["vote_level"]
        print(f"\n{target}: model acc={vm['model']['accuracy']} "
              f"brier={vm['model']['brier']} vs justice baseline "
              f"acc={vm['justice']['accuracy']}")
        if "case_level_model" in summary:
            print(f"case-level: acc={summary['case_level_model']['accuracy']} "
                  f"(n={summary['case_level_model']['n']})")


if __name__ == "__main__":
    main()
