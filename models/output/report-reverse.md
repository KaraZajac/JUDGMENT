# Walk-forward evaluation — target: reverse

*Generated 2026-07-04 by `models/report.py`. Protocol: train on terms ≤ T−1, predict every vote of term T; eval window 1956–2024 (modern SCDB era, first ten terms reserved as burn-in). Target: justice votes to reverse the judgment below.*

## Vote-level results

| predictor | n | accuracy | Brier | log loss | AUC | ECE |
|---|---|---|---|---|---|---|
| model | 67047 | 0.6677 | 0.2158 | 0.6298 | 0.6809 | 0.0784 |
| base_rate | 67047 | 0.6461 | 0.2293 | 0.6512 | 0.4868 | 0.0151 |
| justice | 67047 | 0.6461 | 0.2271 | 0.6465 | 0.5479 | 0.0044 |
| attitudinal | 67047 | 0.6230 | 0.2281 | 0.6478 | 0.6636 | 0.1274 |
| model + prospective isotonic | 24235 | 0.6589 | 0.2149 | 0.6193 | 0.6428 | 0.0198 |

Baselines: `base_rate` = training-window base rate; `justice` = lagged EB-shrunk per-justice rate; `attitudinal` = P(justice's lean opposes the decision below).

## Model vs baselines (McNemar exact test, vote level)

| baseline | model-only correct | baseline-only correct | p |
|---|---|---|---|
| base_rate | 9450 | 8006 | 8.47e-28 |
| justice | 9450 | 8006 | 8.47e-28 |
| attitudinal | 12533 | 9535 | 8.71e-91 |

## Case-level results (Poisson-binomial majority aggregation)

| predictor | n | accuracy | Brier | log loss | AUC | ECE |
|---|---|---|---|---|---|---|
| model (raw) | 7645 | 0.6755 | 0.2424 | 0.8663 | 0.6271 | 0.1806 |

Independence across the nine votes is assumed when aggregating; correlated voting (coalitions) makes case-level probabilities overdispersed — a known limitation, listed below.

## Calibration (vote level)

Raw model reliability:

| bin | n | mean p | observed |
|---|---|---|---|
| 0.0–0.1 | 662 | 0.071 | 0.29 |
| 0.1–0.2 | 2198 | 0.156 | 0.35 |
| 0.2–0.3 | 3588 | 0.254 | 0.408 |
| 0.3–0.4 | 4875 | 0.352 | 0.479 |
| 0.4–0.5 | 6133 | 0.452 | 0.529 |
| 0.5–0.6 | 7421 | 0.552 | 0.574 |
| 0.6–0.7 | 8985 | 0.651 | 0.63 |
| 0.7–0.8 | 10725 | 0.75 | 0.687 |
| 0.8–0.9 | 12355 | 0.851 | 0.754 |
| 0.9–1.0 | 10105 | 0.942 | 0.863 |

After prospective isotonic recalibration (fitted per term on strictly earlier out-of-sample predictions only):

| bin | n | mean p | observed |
|---|---|---|---|
| 0.0–0.1 | 18 | 0.068 | 0.389 |
| 0.1–0.2 | 92 | 0.159 | 0.457 |
| 0.2–0.3 | 236 | 0.258 | 0.428 |
| 0.3–0.4 | 434 | 0.353 | 0.465 |
| 0.4–0.5 | 3158 | 0.465 | 0.488 |
| 0.5–0.6 | 4819 | 0.564 | 0.576 |
| 0.6–0.7 | 6609 | 0.644 | 0.654 |
| 0.7–0.8 | 5605 | 0.743 | 0.725 |
| 0.8–0.9 | 2524 | 0.85 | 0.833 |
| 0.9–1.0 | 740 | 0.924 | 0.888 |

## By decade (accuracy, model vs justice baseline)

| decade | n | model | justice baseline | edge |
|---|---|---|---|---|
| 1950s | 4564 | 0.6856 | 0.6293 | +0.0563 |
| 1960s | 11694 | 0.7043 | 0.6994 | +0.0049 |
| 1970s | 13349 | 0.6714 | 0.6334 | +0.0380 |
| 1980s | 13205 | 0.6568 | 0.6058 | +0.0510 |
| 1990s | 8358 | 0.6311 | 0.6158 | +0.0153 |
| 2000s | 6971 | 0.6655 | 0.6828 | -0.0173 |
| 2010s | 6307 | 0.6433 | 0.6559 | -0.0126 |
| 2020s | 2599 | 0.6903 | 0.6818 | +0.0085 |

## Per justice (≥300 evaluated votes, sorted by accuracy)

| justice | n | accuracy | Brier |
|---|---|---|---|
| WODouglas | 2600 | 0.8035 | 0.1443 |
| AJGoldberg | 422 | 0.8009 | 0.1483 |
| EWarren | 1739 | 0.7970 | 0.1583 |
| AFortas | 494 | 0.7591 | 0.1719 |
| HLBlack | 1979 | 0.7564 | 0.1790 |
| WJBrennan | 4852 | 0.7323 | 0.1911 |
| TMarshall | 3433 | 0.7174 | 0.1961 |
| JGRoberts | 1393 | 0.6949 | 0.2077 |
| WHRehnquist | 4114 | 0.6930 | 0.1963 |
| SAAlito | 1350 | 0.6756 | 0.2097 |
| BMKavanaugh | 413 | 0.6683 | 0.2084 |
| WEBurger | 2570 | 0.6658 | 0.2100 |
| AMKennedy | 2644 | 0.6638 | 0.2159 |
| BRWhite | 4477 | 0.6598 | 0.2226 |
| LFPowell | 2278 | 0.6554 | 0.2248 |
| SDOConnor | 2681 | 0.6539 | 0.2209 |
| CThomas | 2586 | 0.6485 | 0.2192 |
| SGBreyer | 2112 | 0.6458 | 0.2285 |
| AScalia | 2669 | 0.6444 | 0.2218 |
| TCClark | 1440 | 0.6444 | 0.2388 |
| EKagan | 972 | 0.6420 | 0.2257 |
| HABlackmun | 3424 | 0.6343 | 0.2339 |
| SSotomayor | 1084 | 0.6273 | 0.2294 |
| NMGorsuch | 504 | 0.6230 | 0.2370 |
| RBGinsburg | 2097 | 0.6142 | 0.2385 |
| PStewart | 3218 | 0.6091 | 0.2468 |
| FFrankfurter | 677 | 0.6086 | 0.2553 |
| DHSouter | 1613 | 0.6069 | 0.2382 |
| JPStevens | 3867 | 0.5948 | 0.2441 |
| CEWhittaker | 598 | 0.5786 | 0.2722 |
| JHarlan2 | 1982 | 0.5777 | 0.2652 |

## Feature-group ablations (reverse target, 1990–2024)

| variant | n | accuracy | Brier | log loss | AUC | ECE |
|---|---|---|---|---|---|---|
| full | 24235 | 0.6505 | 0.2214 | 0.6370 | 0.6459 | 0.0737 |
| no_case | 24235 | 0.6526 | 0.2271 | 0.6466 | 0.5269 | 0.0202 |
| no_justice | 24235 | 0.6222 | 0.2397 | 0.6829 | 0.5624 | 0.1033 |
| no_ideology | 24235 | 0.6455 | 0.2243 | 0.6450 | 0.6301 | 0.0751 |

`no_case` = justice/context features only; `no_justice` = case facts only; `no_ideology` = full minus directional-lean features.

## With lagged dynamic ideal points (1990–2024)

| variant | n | accuracy | Brier | log loss | AUC | ECE |
|---|---|---|---|---|---|---|
| full + theta_lag | 24235 | 0.6521 | 0.2218 | 0.6387 | 0.6441 | 0.0745 |

`theta_lag` is the justice's ideal point estimated from votes strictly before the prediction term (expanding refits; models/ideal_points.py).

## Deployment configuration (pending-docket forecaster)

| variant | n | accuracy | Brier | log loss | AUC | ECE |
|---|---|---|---|---|---|---|
| cert-stage subset | 67047 | 0.6438 | 0.2242 | 0.6404 | 0.6005 | 0.0384 |
| + lower-court direction (hand-codable) | 67047 | 0.6783 | 0.2076 | 0.6033 | 0.6863 | 0.0291 |
| + question-text LSA | 67047 | 0.6391 | 0.2275 | 0.6498 | 0.6011 | 0.0581 |
| + lc direction + text (interaction test) | 67047 | 0.6764 | 0.2099 | 0.6110 | 0.6841 | 0.0461 |
| full config + text (1990–2024) | 24235 | 0.6521 | 0.2203 | 0.6338 | 0.6446 | 0.0674 |

Lower-court direction is hand-codable per pending case (petitioner lost below + SCDB issue conventions; `models/pending_lc.yaml`) and was **adopted** — the lean subset plus lc_direction outperforms even the full research configuration. Question-presented text (cert-stage by construction) was tested as leakage-safe per-step TF-IDF/LSA and **rejected twice**: it does not help without lc_direction, and the interaction hypothesis fails too — with lc_direction present, text still subtracts. Content adds nothing beyond structure here; the corpus remains for richer text sources.

The live forecaster (`models/predict.py`) is restricted to features actually available for a granted-but-undecided case (justice history, hand-coded issue area, U.S.-party flags, jurisdiction). This row is that exact configuration walk-forward validated over the same window — the honest expected performance of published forecasts. The full model's extra accuracy comes from lower-court and party codings that do not exist until SCDB codes the case.

## Published benchmark context

Katz, Bommarito & Blackman (2017, *PLOS ONE*) report **71.9% justice-vote / 70.2% case accuracy** with a random forest over 1816–2015 — a much longer, structurally easier window (mandatory-jurisdiction eras, larger dockets, higher base rates). Numbers here cover the modern discretionary-cert era only, so the comparison is indicative, not head-to-head. Ruger et al. (2004) achieved 75% case accuracy on the single 2002 term against 59% for legal experts; our per-term case accuracies bracket that figure.

## Limitations (read before citing)

1. **Vote independence** in the Poisson-binomial case aggregation ignores coalition structure; case-level probabilities are overconfident in the tails even after vote-level calibration.
2. **SCDB conventions**: the reverse/affirm label follows the disposition-family mapping (partial affirmances count as reverse); the liberal target inherits the Spaeth direction-coding critiques.
3. **Issue area is coded post-hoc** by SCDB from the opinion. Treating it as a cert-stage feature follows the literature (KBB) but is optimistic for truly pre-decision forecasting; the pending-docket forecaster uses hand-coded provisional issue areas and documents them.
4. **Docket selection drift**: the discretionary docket shrank ~150→60 cases/term across the window; per-decade results are the honest view.
5. **Cold starts**: new justices carry shrunk priors only (Segal–Cover covariates are a roadmap item).
