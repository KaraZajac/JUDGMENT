"""Forecast the pending docket: per-justice vote probabilities + case outcomes.

Deploys exactly the configuration validated by models/walkforward.py ("full"
feature set): HistGradientBoosting trained on every labeled modern-era vote
(terms <= last SCDB term), with the prospective isotonic calibrator fitted on
the walk-forward out-of-sample predictions. For pending cases the available
features are sparser — hand-coded provisional issue areas
(models/pending_issues.yaml), party-name-derived U.S. flags, jurisdiction =
certiorari — and everything unknowable stays missing; the model's native
missing-value handling carries it. Justice features use votes strictly before
the pending term, so nothing leaks.

Output: data/forecasts/<term>/<caseId>.yaml + a console table.

  .venv/bin/python -m models.predict
"""

import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .features import SHRINK_CAREER, SHRINK_ISSUE, SHRINK_RECENT, eb, load
from .report import fit_final_calibrator
from .walkforward import PENDING_CONFIG, fit_predict

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "models" / "output"
CACHE = OUT / "cache"
FORECASTS = ROOT / "data" / "forecasts"
PENDING_ISSUES = Path(__file__).resolve().parent / "pending_issues.yaml"

SITTING = ["JGRoberts", "CThomas", "SAAlito", "SSotomayor", "EKagan",
           "NMGorsuch", "BMKavanaugh", "ACBarrett", "KBJackson"]


def justice_profiles(df, pending_term):
    """Per-justice features from votes strictly before the pending term."""
    hist = df[df["term"] < pending_term]
    profiles = {}
    g_rev = hist["y_reverse"].mean()
    g_lib = hist["y_liberal"].mean()
    last3 = hist[hist["term"] >= hist["term"].max() - 2]
    court_rev_3t = last3["y_reverse"].mean()

    for jn in SITTING:
        h = hist[hist["justiceName"] == jn]
        h3 = last3[last3["justiceName"] == jn]
        rev = h["y_reverse"].dropna()
        lib = h["y_liberal"].dropna()
        rev3 = h3["y_reverse"].dropna()
        lib3 = h3["y_liberal"].dropna()
        issue_rates = {}
        for area, gi in h.dropna(subset=["y_liberal", "issue_area"]).groupby("issue_area"):
            r = gi["y_liberal"]
            career = eb(lib.sum(), len(lib), g_lib, SHRINK_CAREER)
            issue_rates[float(area)] = float(eb(r.sum(), len(r), career, SHRINK_ISSUE))
        profiles[jn] = {
            "justice_cat": float(h["justice_cat"].iloc[-1]) if len(h) else np.nan,
            "tenure": float(pending_term - h["term"].min()) if len(h) else 0.0,
            "is_chief": 1.0 if jn == "JGRoberts" else 0.0,
            "appointer_party": float(h["appointer_party"].iloc[-1]) if len(h) else np.nan,
            "n_prior": float(len(rev)),
            "prior_reverse": float(eb(rev.sum(), len(rev), g_rev, SHRINK_CAREER)),
            "prior_reverse_3t": float(eb(rev3.sum(), len(rev3), g_rev, SHRINK_RECENT)),
            "prior_liberal": float(eb(lib.sum(), len(lib), g_lib, SHRINK_CAREER)),
            "prior_liberal_3t": float(eb(lib3.sum(), len(lib3), g_lib, SHRINK_RECENT)),
            # lagged-through-(pending_term-2): one term stale, still leak-free
            "prior_majority_rate": float(h["prior_majority_rate"].iloc[-1]) if len(h) else np.nan,
            "prior_dissent_rate": float(h["prior_dissent_rate"].iloc[-1]) if len(h) else np.nan,
            "court_prior_reverse_3t": float(court_rev_3t),
            "_issue_liberal": issue_rates,
            "_career_liberal": float(eb(lib.sum(), len(lib), g_lib, SHRINK_CAREER)),
        }
    return profiles


def pending_rows(profiles, pending_cases, issue_map):
    rows = []
    for case in pending_cases:
        coded = issue_map.get(case["id"], {})
        issue_area = coded.get("issue_area")
        pet = (case.get("parties", {}) or {}).get("petitioner_name") or ""
        res = (case.get("parties", {}) or {}).get("respondent_name") or ""
        for jn in SITTING:
            p = profiles[jn]
            row = {
                "caseId": case["id"], "justiceName": jn, "term": float(case["term"]),
                "issue_area": float(issue_area) if issue_area else np.nan,
                "law_type": np.nan, "cert_reason": np.nan, "jurisdiction": 1.0,
                "lc_direction": np.nan,
                "case_source_cat": -2.0, "case_origin_cat": -2.0,
                "petitioner_cat": -2.0, "respondent_cat": -2.0,
                "lc_disagreement": np.nan, "three_judge_dc": 0.0,
                "us_petitioner": float("United States" in pet),
                "us_respondent": float("United States" in res),
                "has_admin_action": np.nan,
                "prior_issue_liberal": p["_issue_liberal"].get(
                    float(issue_area) if issue_area else -1.0,
                    p["_career_liberal"]) if issue_area else np.nan,
            }
            for k, v in p.items():
                if not k.startswith("_"):
                    row[k] = v
            rows.append(row)
    return pd.DataFrame(rows)


def split_distribution(probs):
    dist = np.zeros(len(probs) + 1)
    dist[0] = 1.0
    for p in probs:
        dist[1:] = dist[1:] * (1 - p) + dist[:-1] * p
        dist[0] *= 1 - p
    return dist  # dist[k] = P(exactly k reverse votes)


def main():
    df = load()
    issue_map = yaml.safe_load(PENDING_ISSUES.read_text()) or {}

    pending = []
    docket_root = ROOT / "data" / "docket"
    if docket_root.exists():
        for tdir in sorted(docket_root.iterdir()):
            if tdir.is_dir():
                for f in sorted(tdir.glob("*.yaml")):
                    pending.append(yaml.safe_load(f.read_text(encoding="utf-8")))
    if not pending:
        print("no pending docket cases (run pipeline.interim to refresh); nothing to forecast")
        return

    last_term = int(df["term"].max())
    print(f"training final models on terms <= {last_term} "
          f"({len(df):,} rows); forecasting {len(pending)} pending cases")

    calibs, preds = {}, {}
    for target, label in (("reverse", "y_reverse"), ("liberal", "y_liberal")):
        train = df.dropna(subset=[label]).copy()
        train[label] = train[label].astype(float)
        # deployment-matched configuration: same feature subset + a calibrator
        # fitted on THAT configuration's own out-of-sample predictions. Falls
        # back to the committed step-function export (models/calibrators-pending
        # .yaml) when the prediction cache is absent (e.g. CI).
        wf_path = CACHE / f"predictions-{target}-pending_config.pkl"
        if wf_path.exists():
            calibs[target] = fit_final_calibrator(pd.read_pickle(wf_path)).predict
        else:
            exported = yaml.safe_load(
                (Path(__file__).resolve().parent / "calibrators-pending.yaml")
                .read_text())[target]
            xs, ys = np.array(exported["x"]), np.array(exported["y"])
            calibs[target] = lambda p, xs=xs, ys=ys: np.interp(p, xs, ys)

        profiles = justice_profiles(train, min(c["term"] for c in pending))
        X_pending = pending_rows(profiles, pending, issue_map)
        raw = fit_predict(train, X_pending, label, feature_subset=PENDING_CONFIG)
        X_pending[f"p_{target}"] = calibs[target](raw)
        preds[target] = X_pending[["caseId", "justiceName", f"p_{target}"]]

    merged = preds["reverse"].merge(preds["liberal"], on=["caseId", "justiceName"])

    generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for case in pending:
        g = merged[merged["caseId"] == case["id"]]
        probs = g["p_reverse"].to_numpy()
        dist = split_distribution(probs)
        need = len(probs) // 2 + 1
        p_case = float(dist[need:].sum())
        coded = issue_map.get(case["id"], {})

        payload = {
            "id": case["id"],
            "name": case["name"],
            "term": case["term"],
            "generated": generated,
            "model": {
                "engine": "HistGradientBoosting, deployment-matched cert-stage "
                          "feature subset (walk-forward validated as pending_config)",
                "trained_through_term": last_term,
                "calibration": "isotonic over the subset's own 1956-2024 "
                               "out-of-sample predictions",
                "validated_vote_accuracy": "see models/output/report-reverse.md "
                                           "§ deployment configuration",
            },
            "features": {
                "issue_area": coded.get("issue_area"),
                "issue_area_basis": coded.get("basis", "not coded (missing)"),
                "argued": (case.get("dates") or {}).get("argued"),
                "note": "lower-court direction, parties, and law type unknown pre-SCDB "
                        "coding; model uses native missing-value handling",
            },
            "prediction": {
                "p_reverse": round(p_case, 3),
                "expected_reverse_votes": round(float(probs.sum()), 2),
                "reverse_vote_distribution": {
                    f"{k}-{len(probs) - k}": round(float(dist[k]), 3)
                    for k in range(len(probs), -1, -1) if dist[k] >= 0.005},
            },
            "votes": [
                {"justice": r.justiceName,
                 "p_reverse": round(float(r.p_reverse), 3),
                 "p_liberal": round(float(r.p_liberal), 3)}
                for r in g.itertuples()
            ],
        }
        tdir = FORECASTS / str(case["term"])
        tdir.mkdir(parents=True, exist_ok=True)
        with open(tdir / f"{case['id']}.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=False, width=100)

    print(f"\n{'case':<44} {'p(reverse)':>10} {'E[rev votes]':>12}")
    for case in pending:
        g = merged[merged["caseId"] == case["id"]]
        probs = g["p_reverse"].to_numpy()
        dist = split_distribution(probs)
        p_case = float(dist[len(probs) // 2 + 1:].sum())
        print(f"{case['name'][:43]:<44} {p_case:>10.2f} {probs.sum():>12.1f}")
    print(f"\nwrote {len(pending)} forecasts -> data/forecasts/")


if __name__ == "__main__":
    main()
