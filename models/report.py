"""Generate models/output/report-<target>.md from cached predictions + metrics.

Adds prospective isotonic recalibration: the calibrated probability for term T
is produced by an isotonic map fitted ONLY on out-of-sample predictions from
terms before T — exactly what a live forecaster could have done at the time.
Raw and calibrated metrics are reported side by side.
"""

import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.isotonic import IsotonicRegression

from .walkforward import metric_block, reliability

OUT = Path(__file__).resolve().parent / "output"
CACHE = OUT / "cache"

MIN_CAL_ROWS = 3000  # history required before calibration kicks in


def prospective_calibration(res):
    res = res.sort_values("term").reset_index(drop=True)
    p_cal = res["p_model"].to_numpy().copy()
    terms = sorted(res["term"].unique())
    for T in terms:
        hist = res[res["term"] < T]
        mask = (res["term"] == T).to_numpy()
        if len(hist) < MIN_CAL_ROWS:
            continue
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.005, y_max=0.995)
        iso.fit(hist["p_model"].to_numpy(), hist["y"].to_numpy())
        p_cal[mask] = iso.predict(res.loc[mask, "p_model"].to_numpy())
    res["p_cal"] = p_cal
    return res


def fit_final_calibrator(res):
    """Isotonic map over ALL out-of-sample predictions — for the live forecaster."""
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.005, y_max=0.995)
    iso.fit(res["p_model"].to_numpy(), res["y"].to_numpy())
    return iso


def md_table(rows, headers):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def block_row(name, b):
    return [name, b["n"], f"{b['accuracy']:.4f}", f"{b['brier']:.4f}",
            f"{b['log_loss']:.4f}", f"{b.get('auc', '—')}", f"{b['ece']:.4f}"]


def build_report(target):
    metrics = yaml.safe_load((OUT / f"metrics-{target}.yaml").read_text())
    res = pd.read_pickle(CACHE / f"predictions-{target}-full.pkl")
    res = prospective_calibration(res)
    y = res["y"].to_numpy()

    cal_block = metric_block(y, res["p_cal"].to_numpy())
    raw_block = metrics["vote_level"]["model"]

    lines = []
    a = lines.append
    tgt_label = ("justice votes to reverse the judgment below" if target == "reverse"
                 else "justice casts an SCDB-liberal vote")
    a(f"# Walk-forward evaluation — target: {target}")
    a("")
    a(f"*Generated {datetime.date.today().isoformat()} by `models/report.py`. "
      f"Protocol: train on terms ≤ T−1, predict every vote of term T; "
      f"eval window {metrics['eval_terms'][0]}–{metrics['eval_terms'][1]} "
      f"(modern SCDB era, first ten terms reserved as burn-in). "
      f"Target: {tgt_label}.*")
    a("")
    a("## Vote-level results")
    a("")
    rows = [block_row(n, b) for n, b in metrics["vote_level"].items()]
    rows.append(block_row("model + prospective isotonic", cal_block))
    a(md_table(rows, ["predictor", "n", "accuracy", "Brier", "log loss", "AUC", "ECE"]))
    a("")
    a("Baselines: `base_rate` = training-window base rate; `justice` = lagged "
      "EB-shrunk per-justice rate; `attitudinal` = P(justice's lean opposes the "
      "decision below)" + ("; `party` = P(liberal | appointing party), fit on train."
                           if target == "liberal" else "."))
    a("")
    a("## Model vs baselines (McNemar exact test, vote level)")
    a("")
    rows = [[k, v["a_only_right"], v["b_only_right"], v["p_value"]]
            for k, v in metrics["comparisons"].items()]
    a(md_table(rows, ["baseline", "model-only correct", "baseline-only correct", "p"]))
    a("")
    if "case_level_model" in metrics:
        a("## Case-level results (Poisson-binomial majority aggregation)")
        a("")
        cases_rows = [block_row("model (raw)", metrics["case_level_model"])]
        a(md_table(cases_rows, ["predictor", "n", "accuracy", "Brier", "log loss", "AUC", "ECE"]))
        a("")
        a("Independence across the nine votes is assumed when aggregating; "
          "correlated voting (coalitions) makes case-level probabilities "
          "overdispersed — a known limitation, listed below.")
        a("")
    a("## Calibration (vote level)")
    a("")
    a("Raw model reliability:")
    a("")
    rows = [[r["bin"], r["n"], r["mean_p"], r["frac_positive"]]
            for r in metrics["calibration_model"]]
    a(md_table(rows, ["bin", "n", "mean p", "observed"]))
    a("")
    a("After prospective isotonic recalibration (fitted per term on strictly "
      "earlier out-of-sample predictions only):")
    a("")
    rows = [[r["bin"], r["n"], r["mean_p"], r["frac_positive"]]
            for r in reliability(y, res["p_cal"].to_numpy())]
    a(md_table(rows, ["bin", "n", "mean p", "observed"]))
    a("")
    a("## By decade (accuracy, model vs justice baseline)")
    a("")
    rows = [[dec, b["model"]["n"], f"{b['model']['accuracy']:.4f}",
             f"{b['justice_baseline']['accuracy']:.4f}",
             f"{b['model']['accuracy'] - b['justice_baseline']['accuracy']:+.4f}"]
            for dec, b in sorted(metrics["by_decade"].items())]
    a(md_table(rows, ["decade", "n", "model", "justice baseline", "edge"]))
    a("")
    a("## Per justice (≥300 evaluated votes, sorted by accuracy)")
    a("")
    rows = [[r["justice"], r["n"], f"{r['accuracy']:.4f}", f"{r['brier']:.4f}"]
            for r in metrics["by_justice"]]
    a(md_table(rows, ["justice", "n", "accuracy", "Brier"]))
    a("")

    abl_path = OUT / "metrics-ablations.yaml"
    if abl_path.exists() and target == "reverse":
        abl = yaml.safe_load(abl_path.read_text())
        a(f"## Feature-group ablations (reverse target, "
          f"{abl['eval_terms'][0]}–{abl['eval_terms'][1]})")
        a("")
        rows = [block_row(n, b) for n, b in abl["ablations"].items()]
        a(md_table(rows, ["variant", "n", "accuracy", "Brier", "log loss", "AUC", "ECE"]))
        a("")
        a("`no_case` = justice/context features only; `no_justice` = case facts only; "
          "`no_ideology` = full minus directional-lean features.")
        a("")
    theta_path = OUT / f"metrics-{target}-with-theta.yaml"
    if theta_path.exists():
        th = yaml.safe_load(theta_path.read_text())
        b = th["vote_level"]["model"]
        a(f"## With lagged dynamic ideal points "
          f"({th['eval_terms'][0]}–{th['eval_terms'][1]})")
        a("")
        a(md_table([block_row("full + theta_lag", b)],
                   ["variant", "n", "accuracy", "Brier", "log loss", "AUC", "ECE"]))
        a("")
        a("`theta_lag` is the justice's ideal point estimated from votes strictly "
          "before the prediction term (expanding refits; models/ideal_points.py).")
        a("")

    pc_path = OUT / f"metrics-{target}-pending-config.yaml"
    if pc_path.exists():
        pc = yaml.safe_load(pc_path.read_text())
        b = pc["vote_level"]["model"]
        a("## Deployment configuration (pending-docket forecaster)")
        a("")
        a(md_table([block_row("cert-stage subset", b)],
                   ["variant", "n", "accuracy", "Brier", "log loss", "AUC", "ECE"]))
        a("")
        a("The live forecaster (`models/predict.py`) is restricted to features "
          "actually available for a granted-but-undecided case (justice history, "
          "hand-coded issue area, U.S.-party flags, jurisdiction). This row is that "
          "exact configuration walk-forward validated over the same window — the "
          "honest expected performance of published forecasts. The full model's "
          "extra accuracy comes from lower-court and party codings that do not "
          "exist until SCDB codes the case.")
        a("")
    a("## Published benchmark context")
    a("")
    a("Katz, Bommarito & Blackman (2017, *PLOS ONE*) report **71.9% justice-vote / "
      "70.2% case accuracy** with a random forest over 1816–2015 — a much longer, "
      "structurally easier window (mandatory-jurisdiction eras, larger dockets, "
      "higher base rates). Numbers here cover the modern discretionary-cert era "
      "only, so the comparison is indicative, not head-to-head. Ruger et al. "
      "(2004) achieved 75% case accuracy on the single 2002 term against 59% for "
      "legal experts; our per-term case accuracies bracket that figure.")
    a("")
    a("## Limitations (read before citing)")
    a("")
    a("1. **Vote independence** in the Poisson-binomial case aggregation ignores "
      "coalition structure; case-level probabilities are overconfident in the "
      "tails even after vote-level calibration.")
    a("2. **SCDB conventions**: the reverse/affirm label follows the "
      "disposition-family mapping (partial affirmances count as reverse); the "
      "liberal target inherits the Spaeth direction-coding critiques.")
    a("3. **Issue area is coded post-hoc** by SCDB from the opinion. Treating it "
      "as a cert-stage feature follows the literature (KBB) but is optimistic "
      "for truly pre-decision forecasting; the pending-docket forecaster uses "
      "hand-coded provisional issue areas and documents them.")
    a("4. **Docket selection drift**: the discretionary docket shrank ~150→60 "
      "cases/term across the window; per-decade results are the honest view.")
    a("5. **Cold starts**: new justices carry shrunk priors only (Segal–Cover "
      "covariates are a roadmap item).")
    a("")

    path = OUT / f"report-{target}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")
    print(f"  raw: acc={raw_block['accuracy']} brier={raw_block['brier']} "
          f"ece={raw_block['ece']}")
    print(f"  calibrated: acc={cal_block['accuracy']} brier={cal_block['brier']} "
          f"ece={cal_block['ece']}")


def main():
    for target in ("reverse", "liberal"):
        if (OUT / f"metrics-{target}.yaml").exists():
            build_report(target)


if __name__ == "__main__":
    main()
