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
from sklearn.decomposition import TruncatedSVD
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import roc_auc_score

from .features import (CAT_FEATURES, NUM_FEATURES, ORAL2_FEATURES,
                       ORAL_FEATURES, SC_FEATURES, SG_FEATURES, load)

TEXT_DIMS = 64


def load_questions():
    """caseId -> question presented (data/text/questions.yaml, cert-stage text)."""
    path = Path(__file__).resolve().parent.parent / "data" / "text" / "questions.yaml"
    if not path.exists():
        raise SystemExit("data/text/questions.yaml missing — run "
                         "`python3 -m pipeline.questions` first")
    return yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]


def fit_text_embedder(train_questions, dims=TEXT_DIMS, seed=7):
    """TF-IDF + LSA fit on training-window questions ONLY (leakage-safe).

    Returns embed(series) -> (n, k) array, NaN rows where no question exists,
    or None when the training window has too little text to support the basis.
    """
    texts = train_questions.fillna("")
    has = texts.str.len() > 0
    if has.sum() < 200:
        return None
    tf = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=3,
                         stop_words="english", sublinear_tf=True)
    M = tf.fit_transform(texts[has])
    k = int(min(dims, M.shape[1] - 1, M.shape[0] - 1))
    if k < 2:
        return None
    svd = TruncatedSVD(n_components=k, random_state=seed)
    svd.fit(M)

    def embed(series):
        q = series.fillna("")
        mask = (q.str.len() > 0).to_numpy()
        out = np.full((len(q), k), np.nan)
        if mask.any():
            out[mask] = svd.transform(tf.transform(q[mask]))
        return out

    embed.k = k
    return embed

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

def fit_predict(train, test, target, feature_subset=None, with_text=False):
    cats = [c for c in CAT_FEATURES if feature_subset is None or c in feature_subset]
    # an explicit subset is trusted for numeric columns, so variant features
    # (e.g. prior_issue_liberal_3t) can be tested without changing the base config
    nums = (list(NUM_FEATURES) if feature_subset is None
            else [c for c in feature_subset if c not in CAT_FEATURES])
    X_train = train[cats + nums].copy()
    X_test = test[cats + nums].copy()
    for c in cats:
        joint = pd.concat([X_train[c], X_test[c]])
        categories = joint.dropna().unique()
        X_train[c] = pd.Categorical(X_train[c], categories=categories)
        X_test[c] = pd.Categorical(X_test[c], categories=categories)
    if with_text:
        embed = fit_text_embedder(train["question"])
        if embed is not None:
            E_tr, E_te = embed(train["question"]), embed(test["question"])
            for i in range(embed.k):  # appended after cats: categorical idx unchanged
                X_train[f"q{i}"] = E_tr[:, i]
                X_test[f"q{i}"] = E_te[:, i]
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

def run(target, start, end, feature_subset=None, tag="full", with_theta=False,
        with_text=False):
    df = load()
    label = "y_reverse" if target == "reverse" else "y_liberal"
    df = df.dropna(subset=[label]).copy()
    df[label] = df[label].astype(float)

    if with_text:
        questions = load_questions()
        df["question"] = df["caseId"].map(questions)
        covered = df["question"].notna().mean()
        print(f"  question text on {covered:.1%} of labeled rows")

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
        p_model = fit_predict(train, test, label, feature_subset, with_text=with_text)
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
    ap.add_argument("--text", action="store_true",
                    help="add leakage-safe LSA features from the question presented")
    ap.add_argument("--lc", action="store_true",
                    help="add lower-court direction to the pending-config subset "
                         "(hand-coded for pending cases in models/pending_lc.yaml)")
    ap.add_argument("--issue3t", action="store_true",
                    help="add the recent topic-lean feature (justice x issue area, "
                         "last 3 terms) to the pending-config subset")
    ap.add_argument("--oral", action="store_true",
                    help="add per-justice oral-argument questioning features "
                         "(post-argument stage; harvested by pipeline.oral_args)")
    ap.add_argument("--sc", action="store_true",
                    help="add the Segal-Cover nomination-ideology score "
                         "(cold-start variant; pipeline/curated/segal_cover.yaml)")
    ap.add_argument("--sg", action="store_true",
                    help="add the SG-as-amicus side (post-argument stage variant; "
                         "from the Oyez advocate metadata)")
    ap.add_argument("--oral2", action="store_true",
                    help="add the format-robust word-centric questioning features "
                         "(seriatim-era candidate; see features.ORAL2_FEATURES)")
    ap.add_argument("--lcdis", action="store_true",
                    help="add lower-court dissent (lc_disagreement) — a coded "
                         "SCDB binary; pending cases would code it from the "
                         "harvested lower-court opinions if adopted")
    ap.add_argument("--source", action="store_true",
                    help="add the originating-court categorical (case_source_cat; "
                         "cert-stage-knowable — pending cases map lower_court.name "
                         "to SCDB codes via pipeline/curated/lower_court_codes.yaml)")
    args = ap.parse_args()

    if args.pending_config:
        subset = (PENDING_CONFIG + (["lc_direction"] if args.lc else [])
                  + (["prior_issue_liberal_3t"] if args.issue3t else [])
                  + (ORAL_FEATURES if args.oral else [])
                  + (SC_FEATURES if args.sc else [])
                  + (["case_source_cat"] if args.source else [])
                  + (["lc_disagreement"] if args.lcdis else [])
                  + (SG_FEATURES if args.sg else [])
                  + (ORAL2_FEATURES if args.oral2 else []))
        tag = ("pending_config" + ("_lc" if args.lc else "")
               + ("_issue3t" if args.issue3t else "")
               + ("_oa" if args.oral else "")
               + ("_sc" if args.sc else "")
               + ("_src" if args.source else "")
               + ("_lcdis" if args.lcdis else "")
               + ("_sg" if args.sg else "")
               + ("_oa2" if args.oral2 else "")
               + ("_text" if args.text else ""))
        suffix = tag.replace("_", "-")
        for target in (["reverse", "liberal"] if args.target == "both" else [args.target]):
            print(f"=== walk-forward, {tag} subset: {target} ===")
            res = run(target, args.start, args.end, subset, tag=tag,
                      with_text=args.text)
            summary = summarize(res, target, tag=tag)
            with open(OUT / f"metrics-{target}-{suffix}.yaml", "w") as f:
                yaml.safe_dump(summary, f, sort_keys=False)
            vm = summary["vote_level"]["model"]
            print(f"{tag}/{target}: acc={vm['accuracy']} "
                  f"brier={vm['brier']} auc={vm.get('auc')}")
        return

    if args.text:
        target = "reverse" if args.target == "both" else args.target
        print(f"=== walk-forward, full config + text: {target} ===")
        res = run(target, max(args.start, 1990), args.end, tag="full_text",
                  with_text=True)
        summary = summarize(res, target, tag="full_text")
        with open(OUT / f"metrics-{target}-full-text.yaml", "w") as f:
            yaml.safe_dump(summary, f, sort_keys=False)
        vm = summary["vote_level"]["model"]
        print(f"full_text/{target}: acc={vm['accuracy']} brier={vm['brier']} "
              f"auc={vm.get('auc')}")
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
