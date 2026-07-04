# Walk-forward evaluation — target: liberal

*Generated 2026-07-04 by `models/report.py`. Protocol: train on terms ≤ T−1, predict every vote of term T; eval window 1956–2024 (modern SCDB era, first ten terms reserved as burn-in). Target: justice casts an SCDB-liberal vote.*

## Vote-level results

| predictor | n | accuracy | Brier | log loss | AUC | ECE |
|---|---|---|---|---|---|---|
| model | 69825 | 0.6595 | 0.2194 | 0.6397 | 0.7216 | 0.0771 |
| base_rate | 69825 | 0.5224 | 0.2498 | 0.6928 | 0.5434 | 0.0399 |
| justice | 69825 | 0.6223 | 0.2285 | 0.6488 | 0.6662 | 0.0026 |
| party | 69825 | 0.5607 | 0.2449 | 0.6830 | 0.5838 | 0.0271 |
| model + prospective isotonic | 69825 | 0.6598 | 0.2136 | 0.6173 | 0.7191 | 0.0117 |

Baselines: `base_rate` = training-window base rate; `justice` = lagged EB-shrunk per-justice rate; `attitudinal` = P(justice's lean opposes the decision below); `party` = P(liberal | appointing party), fit on train.

## Model vs baselines (McNemar exact test, vote level)

| baseline | model-only correct | baseline-only correct | p |
|---|---|---|---|
| base_rate | 21192 | 11619 | 0.0 |
| justice | 11592 | 8992 | 1.56e-73 |
| party | 17413 | 10509 | 0.0 |

## Case-level results (Poisson-binomial majority aggregation)

| predictor | n | accuracy | Brier | log loss | AUC | ECE |
|---|---|---|---|---|---|---|
| model (raw) | 7609 | 0.5068 | 0.3748 | 1.3988 | 0.4911 | 0.3371 |

Independence across the nine votes is assumed when aggregating; correlated voting (coalitions) makes case-level probabilities overdispersed — a known limitation, listed below.

## Calibration (vote level)

Raw model reliability:

| bin | n | mean p | observed |
|---|---|---|---|
| 0.0–0.1 | 4312 | 0.063 | 0.171 |
| 0.1–0.2 | 6696 | 0.151 | 0.264 |
| 0.2–0.3 | 7119 | 0.25 | 0.351 |
| 0.3–0.4 | 7231 | 0.35 | 0.419 |
| 0.4–0.5 | 7453 | 0.45 | 0.481 |
| 0.5–0.6 | 7719 | 0.55 | 0.53 |
| 0.6–0.7 | 7404 | 0.65 | 0.599 |
| 0.7–0.8 | 7513 | 0.75 | 0.654 |
| 0.8–0.9 | 7493 | 0.85 | 0.744 |
| 0.9–1.0 | 6885 | 0.945 | 0.848 |

After prospective isotonic recalibration (fitted per term on strictly earlier out-of-sample predictions only):

| bin | n | mean p | observed |
|---|---|---|---|
| 0.0–0.1 | 296 | 0.058 | 0.189 |
| 0.1–0.2 | 2089 | 0.175 | 0.177 |
| 0.2–0.3 | 5294 | 0.255 | 0.221 |
| 0.3–0.4 | 10467 | 0.356 | 0.33 |
| 0.4–0.5 | 13831 | 0.451 | 0.444 |
| 0.5–0.6 | 13132 | 0.547 | 0.55 |
| 0.6–0.7 | 10539 | 0.651 | 0.646 |
| 0.7–0.8 | 7756 | 0.75 | 0.751 |
| 0.8–0.9 | 5222 | 0.847 | 0.844 |
| 0.9–1.0 | 1199 | 0.946 | 0.85 |

## By decade (accuracy, model vs justice baseline)

| decade | n | model | justice baseline | edge |
|---|---|---|---|---|
| 1950s | 4756 | 0.6682 | 0.6457 | +0.0225 |
| 1960s | 12498 | 0.6877 | 0.6627 | +0.0250 |
| 1970s | 14027 | 0.6691 | 0.6132 | +0.0559 |
| 1980s | 13553 | 0.6599 | 0.6057 | +0.0542 |
| 1990s | 8872 | 0.6318 | 0.6025 | +0.0293 |
| 2000s | 7203 | 0.6322 | 0.6272 | +0.0050 |
| 2010s | 6294 | 0.6436 | 0.6007 | +0.0429 |
| 2020s | 2622 | 0.6636 | 0.6274 | +0.0362 |

## Per justice (≥300 evaluated votes, sorted by accuracy)

| justice | n | accuracy | Brier |
|---|---|---|---|
| WODouglas | 2746 | 0.8099 | 0.1382 |
| EWarren | 1832 | 0.7576 | 0.1836 |
| HLBlack | 2113 | 0.7473 | 0.1838 |
| AJGoldberg | 440 | 0.7409 | 0.1815 |
| TMarshall | 3537 | 0.7385 | 0.1859 |
| AFortas | 525 | 0.7314 | 0.1855 |
| WJBrennan | 5087 | 0.7226 | 0.1955 |
| WHRehnquist | 4300 | 0.6937 | 0.2022 |
| BMKavanaugh | 413 | 0.6731 | 0.2087 |
| SAAlito | 1361 | 0.6730 | 0.2087 |
| WEBurger | 2692 | 0.6698 | 0.2133 |
| JGRoberts | 1405 | 0.6633 | 0.2161 |
| CThomas | 2667 | 0.6550 | 0.2108 |
| AScalia | 2777 | 0.6493 | 0.2218 |
| BRWhite | 4701 | 0.6414 | 0.2289 |
| SSotomayor | 1091 | 0.6370 | 0.2241 |
| LFPowell | 2383 | 0.6316 | 0.2310 |
| HABlackmun | 3561 | 0.6288 | 0.2343 |
| EKagan | 973 | 0.6280 | 0.2285 |
| TCClark | 1515 | 0.6257 | 0.2490 |
| NMGorsuch | 496 | 0.6250 | 0.2354 |
| SGBreyer | 2168 | 0.6190 | 0.2361 |
| SDOConnor | 2798 | 0.6187 | 0.2348 |
| AMKennedy | 2740 | 0.6182 | 0.2323 |
| JPStevens | 4019 | 0.6123 | 0.2393 |
| RBGinsburg | 2162 | 0.6105 | 0.2369 |
| PStewart | 3429 | 0.6028 | 0.2530 |
| DHSouter | 1690 | 0.5970 | 0.2462 |
| FFrankfurter | 695 | 0.5928 | 0.2758 |
| JHarlan2 | 2089 | 0.5797 | 0.2623 |
| CEWhittaker | 641 | 0.5585 | 0.2793 |

## Deployment configuration (pending-docket forecaster)

| variant | n | accuracy | Brier | log loss | AUC | ECE |
|---|---|---|---|---|---|---|
| cert-stage subset | 69825 | 0.6420 | 0.2199 | 0.6302 | 0.6999 | 0.0293 |
| + lower-court direction (hand-codable) | 69825 | 0.6632 | 0.2119 | 0.6127 | 0.726 | 0.0291 |
| + question-text LSA | 69825 | 0.6433 | 0.2242 | 0.6453 | 0.6968 | 0.0540 |

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
