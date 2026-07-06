"""Leak-free feature table for per-justice vote prediction (modern era, 1946+).

One row per (case, justice) vote from the SCDB justice-centered file. Two labels:

- ``y_reverse`` — the justice voted to disturb the judgment below (KBB 2017
  convention): defined where caseDisposition in {2..8} and majority coded;
  reverse-family = {3,4,5,6,7,8}, affirm = {2}. A dissent from a reversing
  majority is an affirm vote, and vice versa.
- ``y_liberal`` — SCDB vote direction == liberal (2), where coded.

Feature-availability policy (the defensibility core): every feature must be
knowable BEFORE the decision.

- Case features are cert-stage facts: issue area, law type, cert reason,
  jurisdiction, lower-court direction/disagreement, three-judge DC, source and
  origin court codes (top-K categorical), party codes (top-K), U.S.-as-party
  flags, term. Nothing downstream of the vote (disposition, direction,
  majority size, opinion data) is ever a feature.
- Justice features are computed from votes in terms STRICTLY BEFORE the row's
  term (term-granular expanding windows, shifted by one term): tenure, prior
  reverse rate, prior liberal share (career and last-3-terms), prior rate in
  the row's issue area, prior majority/dissent rates — all empirical-Bayes
  shrunk toward the running (also strictly-prior) global mean; plus the
  appointing president's party from the curated biographies.

First-term justices therefore carry pure prior values and n_prior == 0 — the
cold-start is honest (Segal–Cover covariates are a roadmap item).
"""

import io
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"
OUT = ROOT / "models" / "output"
CACHE = OUT / "cache"

REVERSE_SET = {3, 4, 5, 6, 7, 8}
AFFIRM_SET = {2}
TARGET_DISPOSITIONS = REVERSE_SET | AFFIRM_SET

SHRINK_CAREER = 25.0   # EB pseudo-counts toward running global mean
SHRINK_RECENT = 15.0
SHRINK_ISSUE = 15.0
TOPK_COURT = 40
TOPK_PARTY = 40

CAT_FEATURES = [
    "issue_area", "law_type", "cert_reason", "jurisdiction",
    "lc_direction", "case_source_cat", "case_origin_cat",
    "petitioner_cat", "respondent_cat", "appointer_party", "justice_cat",
]
NUM_FEATURES = [
    "term", "tenure", "is_chief", "lc_disagreement", "three_judge_dc",
    "us_petitioner", "us_respondent", "has_admin_action",
    "n_prior", "prior_reverse", "prior_reverse_3t",
    "prior_liberal", "prior_liberal_3t", "prior_issue_liberal",
    "prior_majority_rate", "prior_dissent_rate", "court_prior_reverse_3t",
]

# Post-argument stage variants (pipeline.oral_args; NOT cert-stage — known the
# day of argument, strictly pre-decision). Per justice: turn differential and
# word share toward the petitioner side, total engagement; per case: the
# bench-wide asymmetry. Missing for unargued/uncovered cases by construction.
ORAL_FEATURES = [
    "oa_turn_diff", "oa_word_share_pet", "oa_turns_total",
    "oa_case_turn_diff", "oa_case_word_share_pet",
]


def load_oral():
    """data/oral/<term>.yaml -> one row per (caseId, justiceName): raw
    questioning counts (tp/wp = turns/words while the petitioner side argued;
    tr/wr respondent side)."""
    oral_dir = ROOT / "data" / "oral"
    rows = []
    if oral_dir.exists():
        for f in sorted(oral_dir.glob("*.yaml")):
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            for cid, c in (d.get("cases") or {}).items():
                for mn, r in (c.get("justices") or {}).items():
                    rows.append((cid, mn, r.get("tp", 0), r.get("wp", 0),
                                 r.get("tr", 0), r.get("wr", 0)))
    return pd.DataFrame(rows, columns=["caseId", "justiceName",
                                       "tp", "wp", "tr", "wr"])


def merge_oral(df):
    """Attach ORAL_FEATURES; rows without transcript coverage stay NaN
    (the model's native missing handling treats them as pre-argument)."""
    oral = load_oral()
    if not len(oral):
        for c in ORAL_FEATURES:
            df[c] = np.nan
        return df
    oral["oa_turn_diff"] = (oral["tp"] - oral["tr"]).astype(float)
    tw = oral["wp"] + oral["wr"]
    oral["oa_word_share_pet"] = np.where(tw > 0, oral["wp"] / tw, np.nan)
    oral["oa_turns_total"] = (oral["tp"] + oral["tr"]).astype(float)
    case_tot = oral.groupby("caseId")[["tp", "tr", "wp", "wr"]].sum().reset_index()
    case_tot["oa_case_turn_diff"] = (case_tot["tp"] - case_tot["tr"]).astype(float)
    ctw = case_tot["wp"] + case_tot["wr"]
    case_tot["oa_case_word_share_pet"] = np.where(ctw > 0,
                                                  case_tot["wp"] / ctw, np.nan)
    df = df.merge(oral[["caseId", "justiceName", "oa_turn_diff",
                        "oa_word_share_pet", "oa_turns_total"]],
                  on=["caseId", "justiceName"], how="left")
    df = df.merge(case_tot[["caseId", "oa_case_turn_diff",
                            "oa_case_word_share_pet"]],
                  on="caseId", how="left")
    covered = df["oa_turns_total"].notna().sum()
    print(f"oral-argument features: {covered:,} vote rows covered "
          f"({covered / max(len(df), 1):.0%})")
    return df


def read_modern_justice_csv():
    manifest = yaml.safe_load((SOURCES / "manifest.yaml").read_text())
    path = SOURCES / manifest["files"]["modern_justice"]
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    df = pd.read_csv(io.StringIO(text), low_memory=False)
    return df


def topk_cat(series, k, name):
    top = series.value_counts().head(k).index
    out = series.where(series.isin(top), other=-1.0)
    return out.fillna(-2.0).astype("float64").rename(name)


def eb(successes, n, prior, k):
    return (successes + k * prior) / (n + k)


def _per_term_lagged(df, value_col, group_cols, k, prior_series_name=None):
    """Expanding, one-term-shifted EB-shrunk rate of `value_col` per group.

    Returns a frame keyed by group_cols + term with columns: n_prior, rate.
    The global running mean (itself lagged) is the shrinkage prior.
    """
    d = df.dropna(subset=[value_col])
    per_term = (d.groupby([*group_cols, "term"], sort=True)[value_col]
                .agg(s="sum", n="count").reset_index())

    # lagged global prior by term
    g = d.groupby("term", sort=True)[value_col].agg(gs="sum", gn="count").reset_index()
    g["cgs"] = g["gs"].cumsum().shift(1)
    g["cgn"] = g["gn"].cumsum().shift(1)
    g["global_prior"] = (g["cgs"] / g["cgn"]).fillna(0.5)
    prior_by_term = g.set_index("term")["global_prior"]

    per_term = per_term.sort_values("term")
    grp = per_term.groupby(group_cols, sort=False)
    per_term["cs"] = grp["s"].cumsum() - per_term["s"]      # strictly prior terms
    per_term["cn"] = grp["n"].cumsum() - per_term["n"]
    per_term["prior_mean"] = per_term["term"].map(prior_by_term).fillna(0.5)
    per_term["rate"] = eb(per_term["cs"], per_term["cn"], per_term["prior_mean"], k)
    return per_term[[*group_cols, "term", "cn", "rate", "prior_mean"]]


def _last3_lagged(df, value_col, k, group_cols=("justiceName",)):
    """Last-3-prior-terms EB rate per group (rolling window over term aggregates)."""
    group_cols = list(group_cols)
    d = df.dropna(subset=[value_col])
    per_term = (d.groupby([*group_cols, "term"], sort=True)[value_col]
                .agg(s="sum", n="count").reset_index().sort_values("term"))
    grp = per_term.groupby(group_cols, sort=False)
    s3 = grp["s"].transform(lambda x: x.rolling(3, min_periods=1).sum().shift(1))
    n3 = grp["n"].transform(lambda x: x.rolling(3, min_periods=1).sum().shift(1))
    g = d.groupby("term", sort=True)[value_col].agg(gs="sum", gn="count").reset_index()
    g["global_prior"] = (g["gs"].cumsum().shift(1) / g["gn"].cumsum().shift(1)).fillna(0.5)
    per_term["prior_mean"] = per_term["term"].map(g.set_index("term")["global_prior"]).fillna(0.5)
    per_term["rate3"] = eb(s3.fillna(0), n3.fillna(0), per_term["prior_mean"], k)
    return per_term[[*group_cols, "term", "rate3"]]


def build(save=True):
    raw = read_modern_justice_csv()

    df = pd.DataFrame({
        "caseId": raw["caseId"],
        "term": pd.to_numeric(raw["term"], errors="coerce"),
        "justice": pd.to_numeric(raw["justice"], errors="coerce"),
        "justiceName": raw["justiceName"],
        "natural_court": pd.to_numeric(raw["naturalCourt"], errors="coerce"),
        "chief": raw["chief"],
        "disposition": pd.to_numeric(raw["caseDisposition"], errors="coerce"),
        "majority": pd.to_numeric(raw["majority"], errors="coerce"),
        "direction": pd.to_numeric(raw["direction"], errors="coerce"),
        "vote": pd.to_numeric(raw["vote"], errors="coerce"),
        "issue_area": pd.to_numeric(raw["issueArea"], errors="coerce"),
        "law_type": pd.to_numeric(raw["lawType"], errors="coerce"),
        "cert_reason": pd.to_numeric(raw["certReason"], errors="coerce"),
        "jurisdiction": pd.to_numeric(raw["jurisdiction"], errors="coerce"),
        "lc_direction": pd.to_numeric(raw["lcDispositionDirection"], errors="coerce"),
        "lc_disagreement": pd.to_numeric(raw["lcDisagreement"], errors="coerce"),
        "three_judge_dc": pd.to_numeric(raw["threeJudgeFdc"], errors="coerce"),
        "case_source": pd.to_numeric(raw["caseSource"], errors="coerce"),
        "case_origin": pd.to_numeric(raw["caseOrigin"], errors="coerce"),
        "petitioner": pd.to_numeric(raw["petitioner"], errors="coerce"),
        "respondent": pd.to_numeric(raw["respondent"], errors="coerce"),
        "admin_action": pd.to_numeric(raw["adminAction"], errors="coerce"),
    })
    df = df.dropna(subset=["term", "justiceName"]).reset_index(drop=True)
    df["term"] = df["term"].astype(int)

    # ---- labels ------------------------------------------------------------
    case_reversed = df["disposition"].isin(REVERSE_SET)
    target_ok = df["disposition"].isin(TARGET_DISPOSITIONS) & df["majority"].isin([1, 2])
    in_majority = df["majority"] == 2
    df["y_reverse"] = np.where(
        target_ok, np.where(in_majority, case_reversed, ~case_reversed), np.nan
    ).astype("float64")
    df["y_liberal"] = np.where(
        df["direction"].isin([1, 2]), (df["direction"] == 2).astype(float), np.nan
    )
    df["case_reversed"] = np.where(
        df["disposition"].isin(TARGET_DISPOSITIONS), case_reversed.astype(float), np.nan
    )

    # ---- case features -----------------------------------------------------
    df["us_petitioner"] = (df["petitioner"] == 27).astype(float)
    df["us_respondent"] = (df["respondent"] == 27).astype(float)
    df["has_admin_action"] = df["admin_action"].notna().astype(float)
    df["case_source_cat"] = topk_cat(df["case_source"], TOPK_COURT, "case_source_cat")
    df["case_origin_cat"] = topk_cat(df["case_origin"], TOPK_COURT, "case_origin_cat")
    df["petitioner_cat"] = topk_cat(df["petitioner"], TOPK_PARTY, "petitioner_cat")
    df["respondent_cat"] = topk_cat(df["respondent"], TOPK_PARTY, "respondent_cat")
    df["justice_cat"] = df["justice"].astype("float64")

    # ---- justice features (strictly-prior terms) ----------------------------
    first_term = df.groupby("justiceName")["term"].transform("min")
    df["tenure"] = (df["term"] - first_term).astype(float)
    df["is_chief"] = df.apply(
        lambda r: float(isinstance(r["chief"], str) and str(r["justiceName"]).endswith(r["chief"])),
        axis=1,
    )

    curated = yaml.safe_load((ROOT / "pipeline" / "curated" / "justices.yaml").read_text())
    party_map = {k: {"Democratic": 1.0, "Republican": 0.0}.get(v.get("party"))
                 for k, v in curated.items()}
    df["appointer_party"] = df["justiceName"].map(party_map).astype("float64")

    for col, out_col, k in (
        ("y_reverse", "prior_reverse", SHRINK_CAREER),
        ("y_liberal", "prior_liberal", SHRINK_CAREER),
    ):
        lag = _per_term_lagged(df, col, ["justiceName"], k)
        df = df.merge(
            lag.rename(columns={"cn": f"n_{out_col}", "rate": out_col})[
                ["justiceName", "term", f"n_{out_col}", out_col]],
            on=["justiceName", "term"], how="left")

    df["n_prior"] = df["n_prior_reverse"].fillna(0.0)

    df = df.merge(_last3_lagged(df, "y_reverse", SHRINK_RECENT)
                  .rename(columns={"rate3": "prior_reverse_3t"}),
                  on=["justiceName", "term"], how="left")
    df = df.merge(_last3_lagged(df, "y_liberal", SHRINK_RECENT)
                  .rename(columns={"rate3": "prior_liberal_3t"}),
                  on=["justiceName", "term"], how="left")

    issue_lag = _per_term_lagged(df.dropna(subset=["issue_area"]),
                                 "y_liberal", ["justiceName", "issue_area"], SHRINK_ISSUE)
    df = df.merge(issue_lag.rename(columns={"rate": "prior_issue_liberal"})[
        ["justiceName", "issue_area", "term", "prior_issue_liberal"]],
        on=["justiceName", "issue_area", "term"], how="left")

    # recent topic-level lean: the justice's last-3-terms rate within this
    # issue area (the "topic trend" feature; validated as a config variant)
    issue3 = _last3_lagged(df.dropna(subset=["issue_area"]), "y_liberal",
                           SHRINK_ISSUE, group_cols=("justiceName", "issue_area"))
    df = df.merge(issue3.rename(columns={"rate3": "prior_issue_liberal_3t"}),
                  on=["justiceName", "issue_area", "term"], how="left")

    df["in_majority_num"] = np.where(df["majority"].isin([1, 2]),
                                     (df["majority"] == 2).astype(float), np.nan)
    df["is_dissent"] = np.where(df["vote"].notna(), (df["vote"] == 2).astype(float), np.nan)
    df = df.merge(_per_term_lagged(df, "in_majority_num", ["justiceName"], SHRINK_CAREER)
                  .rename(columns={"rate": "prior_majority_rate"})[
                      ["justiceName", "term", "prior_majority_rate"]],
                  on=["justiceName", "term"], how="left")
    df = df.merge(_per_term_lagged(df, "is_dissent", ["justiceName"], SHRINK_CAREER)
                  .rename(columns={"rate": "prior_dissent_rate"})[
                      ["justiceName", "term", "prior_dissent_rate"]],
                  on=["justiceName", "term"], how="left")

    # court-level base-rate drift: pooled reverse rate over the 3 prior terms
    ct = (df.dropna(subset=["y_reverse"]).groupby("term")["y_reverse"]
          .agg(s="sum", n="count").reset_index().sort_values("term"))
    ct["court_prior_reverse_3t"] = (
        ct["s"].rolling(3, min_periods=1).sum().shift(1)
        / ct["n"].rolling(3, min_periods=1).sum().shift(1)
    ).fillna(0.5)
    df = df.merge(ct[["term", "court_prior_reverse_3t"]], on="term", how="left")

    df = merge_oral(df)

    keep = (["caseId", "term", "justice", "justiceName", "natural_court",
             "y_reverse", "y_liberal", "case_reversed"]
            + CAT_FEATURES + [c for c in NUM_FEATURES if c not in ("term",)]
            # variant features, not in the base config
            + ["prior_issue_liberal_3t"] + ORAL_FEATURES)
    keep = list(dict.fromkeys(keep))
    out = df[keep].copy()

    if save:
        CACHE.mkdir(parents=True, exist_ok=True)
        out.to_pickle(CACHE / "features.pkl")
        print(f"cached {len(out):,} vote rows -> models/output/cache/features.pkl")
    return out


def load():
    path = CACHE / "features.pkl"
    if path.exists():
        return pd.read_pickle(path)
    return build()


def main():
    df = build()
    print(f"rows: {len(df):,}  cases: {df['caseId'].nunique():,}  "
          f"justices: {df['justiceName'].nunique()}  terms: {df['term'].min()}–{df['term'].max()}")
    labeled = df.dropna(subset=["y_reverse"])
    print(f"reverse-labeled rows: {len(labeled):,} "
          f"(base rate {labeled['y_reverse'].mean():.3f})")
    dl = df.dropna(subset=["y_liberal"])
    print(f"direction-labeled rows: {len(dl):,} (liberal share {dl['y_liberal'].mean():.3f})")

    # leakage sanity: a justice's first term must carry zero prior observations
    first = df.loc[df.groupby("justiceName")["term"].transform("min") == df["term"]]
    assert (first["n_prior"] == 0).all(), "leak: first-term rows carry prior history"
    # and their shrunk prior must equal the running global mean exactly
    print("leak checks passed: first-term n_prior == 0 for all justices")


if __name__ == "__main__":
    main()
