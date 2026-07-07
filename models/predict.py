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
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .coalition import quadrature, split_distribution as coalition_split
from .features import SHRINK_CAREER, SHRINK_ISSUE, SHRINK_RECENT, eb, load
from .report import fit_final_calibrator
from .walkforward import PENDING_CONFIG, fit_predict, load_questions

COALITION_PARAMS = Path(__file__).resolve().parent / "coalition-params.yaml"
LOWER_COURT_CODES = (Path(__file__).resolve().parent.parent
                     / "pipeline" / "curated" / "lower_court_codes.yaml")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "models" / "output"
CACHE = OUT / "cache"
FORECASTS = ROOT / "data" / "forecasts"
PENDING_ISSUES = Path(__file__).resolve().parent / "pending_issues.yaml"
PENDING_LC = Path(__file__).resolve().parent / "pending_lc.yaml"

# name -> (feature subset additions, with_text); subset base is PENDING_CONFIG
CONFIGS = {
    "pending_config": ([], False),
    "pending_config_lc": (["lc_direction"], False),
    "pending_config_lc_text": (["lc_direction"], True),
    "pending_config_lc_issue3t": (["lc_direction", "prior_issue_liberal_3t"], False),
}

# The deployed configuration is PINNED to the walk-forward winner, never
# inferred from artifact presence — re-pin only with fresh validation evidence
# (report-reverse.md § deployment configuration). History: text-only REJECTED
# 2026-07 (reverse 64.4% -> 63.9%); lc_direction ADOPTED 2026-07 (64.4% ->
# 67.8%, beats the full research config); lc+text interaction REJECTED
# (67.6% < 67.8%); recent topic-lean (issue3t) ADOPTED 2026-07 on probability
# quality (reverse Brier 0.2076 -> 0.2069, AUC 0.686 -> 0.688; accuracy within
# noise). Segal-Cover REJECTED 2026-07 (flat everywhere; first-term slice
# +0.7pp underpowered — docs/coldstart-segal-cover.md). case_source_cat
# (originating circuit) REJECTED 2026-07: worse on every metric, both targets
# (reverse 67.9% -> 67.1%, Brier 0.2069 -> 0.2131, AUC 0.688 -> 0.680) — the
# lean config already prices circuit effects through lc_direction/issue/court
# trends, and the extra cardinality is pure variance, the same failure mode
# that sank the full research config. The lower_court->code mapper stays (rows
# now carry a truthful case_source_cat instead of a hardcoded missing), but no
# deployed config uses the column. Oral-argument features ADOPTED for the
# POST-ARGUMENT stage only (docs/postargument-gate.md; wiring pending).
# Pending-case lc values hand-coded in pending_lc.yaml.
DEPLOY_CONFIG = "pending_config_lc_issue3t"

SITTING = ["JGRoberts", "CThomas", "SAAlito", "SSotomayor", "EKagan",
           "NMGorsuch", "BMKavanaugh", "ACBarrett", "KBJackson"]


_CIRCUIT_RE = re.compile(r"court of appeals for the ([a-z ]+?) circuit")


def case_source_code(lower_court_name):
    """lower_court.name -> SCDB caseSource code, or None when not confidently
    mappable (scheme + anchors: pipeline/curated/lower_court_codes.yaml)."""
    name = (lower_court_name or "").lower()
    if not name:
        return None
    table = yaml.safe_load(LOWER_COURT_CODES.read_text(encoding="utf-8"))
    m = _CIRCUIT_RE.search(name)
    if m:
        return table["circuits"].get(m.group(1).strip())
    if "appellate division" in name or "appellate term" in name:
        return None  # New York's trial-bench "Supreme Court" trap
    if "supreme court" in name or "district of columbia court of appeals" in name:
        return table["state_court_of_last_resort"]
    return None


def frozen_at_argument(case, path, today):
    """Cert-stage forecasts freeze on argument day.

    Once a case is argued, its registered file is never regenerated — the
    cert-stage record must not absorb argument-informed recoding or newer
    model vintages. The post-argument stage re-registers separately
    (data/forecasts/<term>/post-argument/) once argument-derived features
    clear walk-forward validation; until then argued cases simply keep
    their last pre-argument vintage. An argued case with no file at all is
    NOT frozen (a late first registration beats none, and the scorer's
    ex-ante guard polices it against the decision date)."""
    argued = str((case.get("dates") or {}).get("argued") or "")
    return bool(argued) and argued <= today and path.exists()


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
        issue3_rates = {}
        for area, gi in h3.dropna(subset=["y_liberal", "issue_area"]).groupby("issue_area"):
            r = gi["y_liberal"]
            issue3_rates[float(area)] = float(eb(r.sum(), len(r), g_lib, SHRINK_ISSUE))
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
            "_issue_liberal_3t": issue3_rates,
            "_career_liberal": float(eb(lib.sum(), len(lib), g_lib, SHRINK_CAREER)),
        }
    return profiles


def pending_rows(profiles, pending_cases, issue_map, lc_map=None, source_codes=None):
    lc_map = lc_map or {}
    rows = []
    for case in pending_cases:
        coded = issue_map.get(case["id"], {})
        issue_area = coded.get("issue_area")
        lc_word = (lc_map.get(case["id"]) or {}).get("lc_direction")
        lc_value = {"conservative": 1.0, "liberal": 2.0}.get(lc_word, np.nan)
        pet = (case.get("parties", {}) or {}).get("petitioner_name") or ""
        res = (case.get("parties", {}) or {}).get("respondent_name") or ""
        # originating court: mapped SCDB code when it is one the model was
        # trained on, -1.0 (the "rare" bucket) when mapped but untrained,
        # -2.0 (missing) when unmappable — mirrors topk_cat exactly
        src = case_source_code((case.get("lower_court") or {}).get("name"))
        if src is None:
            src_value = -2.0
        elif source_codes and float(src) in source_codes:
            src_value = float(src)
        else:
            src_value = -1.0
        for jn in SITTING:
            p = profiles[jn]
            row = {
                "caseId": case["id"], "justiceName": jn, "term": float(case["term"]),
                "question": case.get("question"),
                "issue_area": float(issue_area) if issue_area else np.nan,
                "law_type": np.nan, "cert_reason": np.nan, "jurisdiction": 1.0,
                "lc_direction": lc_value,
                "case_source_cat": src_value, "case_origin_cat": -2.0,
                "petitioner_cat": -2.0, "respondent_cat": -2.0,
                "lc_disagreement": np.nan, "three_judge_dc": 0.0,
                "us_petitioner": float("United States" in pet),
                "us_respondent": float("United States" in res),
                "has_admin_action": np.nan,
                "prior_issue_liberal": p["_issue_liberal"].get(
                    float(issue_area) if issue_area else -1.0,
                    p["_career_liberal"]) if issue_area else np.nan,
                "prior_issue_liberal_3t": p["_issue_liberal_3t"].get(
                    float(issue_area) if issue_area else -1.0,
                    p["prior_liberal_3t"]) if issue_area else np.nan,
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

    today = datetime.date.today().isoformat()
    frozen = [c for c in pending if frozen_at_argument(
        c, FORECASTS / str(c["term"]) / f"{c['id']}.yaml", today)]
    if frozen:
        print(f"cert-stage frozen at argument ({len(frozen)} not regenerated): "
              + ", ".join(c["id"] for c in frozen))
        frozen_ids = {c["id"] for c in frozen}
        pending = [c for c in pending if c["id"] not in frozen_ids]
    if not pending:
        print("all pending cases argued and frozen; nothing to forecast")
        return

    last_term = int(df["term"].max())

    extra_features, with_text = CONFIGS[DEPLOY_CONFIG]
    if with_text:
        df["question"] = df["caseId"].map(load_questions())
    config_name = DEPLOY_CONFIG
    lc_map = yaml.safe_load(PENDING_LC.read_text()) if PENDING_LC.exists() else {}
    print(f"training final models on terms <= {last_term} "
          f"({len(df):,} rows, config {config_name}); "
          f"forecasting {len(pending)} pending cases")

    calibs, preds = {}, {}
    for target, label in (("reverse", "y_reverse"), ("liberal", "y_liberal")):
        train = df.dropna(subset=[label]).copy()
        train[label] = train[label].astype(float)
        # calibrator fitted on THIS configuration's own out-of-sample
        # predictions; committed step-function export as the cache-less fallback
        wf_path = CACHE / f"predictions-{target}-{config_name}.pkl"
        if wf_path.exists():
            calibs[target] = fit_final_calibrator(pd.read_pickle(wf_path)).predict
        else:
            exported = yaml.safe_load(
                (Path(__file__).resolve().parent / "calibrators-pending.yaml")
                .read_text())[target]
            xs, ys = np.array(exported["x"]), np.array(exported["y"])
            calibs[target] = lambda p, xs=xs, ys=ys: np.interp(p, xs, ys)

        profiles = justice_profiles(train, min(c["term"] for c in pending))
        if target == "reverse":
            lean_of = {jn: 2.0 * (0.5 - p["prior_liberal"])
                       for jn, p in profiles.items()}
        known_sources = set(df["case_source_cat"].dropna().unique()) - {-1.0, -2.0}
        X_pending = pending_rows(profiles, pending, issue_map, lc_map,
                                 source_codes=known_sources)
        raw = fit_predict(train, X_pending, label,
                          feature_subset=PENDING_CONFIG + extra_features,
                          with_text=with_text)
        X_pending[f"p_{target}"] = calibs[target](raw)
        preds[target] = X_pending[["caseId", "justiceName", f"p_{target}"]]

    merged = preds["reverse"].merge(preds["liberal"], on=["caseId", "justiceName"])

    # coalition-aware aggregation (validated: split log-loss 3.75 -> 2.06 vs
    # independence); falls back to independence if the params file is absent
    coalition = None
    if COALITION_PARAMS.exists():
        cp = yaml.safe_load(COALITION_PARAMS.read_text())
        coalition = (cp["lam0_valence"], cp["lam1_ideology"], quadrature())
        aggregation = (f"two-factor coalition (valence {cp['lam0_valence']}, "
                       f"ideology {cp['lam1_ideology']})")
    else:
        aggregation = "independence (Poisson-binomial)"

    generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for case in pending:
        g = merged[merged["caseId"] == case["id"]]
        probs = g["p_reverse"].to_numpy()
        if coalition:
            lam0, lam1, nodes = coalition
            s = np.array([lean_of.get(jn, 0.0) for jn in g["justiceName"]])
            dist = coalition_split(probs, s, lam0, lam1, nodes)
        else:
            dist = split_distribution(probs)
        need = len(probs) // 2 + 1
        p_case = float(dist[need:].sum())
        coded = issue_map.get(case["id"], {})

        payload = {
            "id": case["id"],
            "name": case["name"],
            "term": case["term"],
            "generated": generated,
            "stage": "cert",  # freezes at argument; post-argument re-registers separately
            "model": {
                "engine": "HistGradientBoosting, deployment-matched cert-stage "
                          f"feature subset ({config_name}, walk-forward validated)",
                "trained_through_term": last_term,
                "calibration": "isotonic over the configuration's own 1956-2024 "
                               "out-of-sample predictions",
                "validated_vote_accuracy": "see models/output/report-reverse.md "
                                           "§ deployment configuration",
            },
            "features": {
                "issue_area": coded.get("issue_area"),
                "issue_area_basis": coded.get("basis", "not coded (missing)"),
                "lc_direction": (lc_map.get(case["id"]) or {}).get("lc_direction"),
                "lc_direction_basis": (lc_map.get(case["id"]) or {}).get(
                    "basis", "not coded (missing)"),
                "question_text": bool(case.get("question")) and with_text,
                "argued": (case.get("dates") or {}).get("argued"),
                "note": "lower-court direction, parties, and law type unknown pre-SCDB "
                        "coding; model uses native missing-value handling",
            },
            "prediction": {
                "p_reverse": round(p_case, 3),
                "aggregation": aggregation,
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
