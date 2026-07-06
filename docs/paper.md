# Forecasting the Supreme Court with Honest Features: Walk-Forward Vote Prediction, Coalition-Aware Aggregation, and a Live Preregistered Registry

**Kara Zajac** · draft v0.1, July 2026 · code, data, and all validation artifacts: https://github.com/KaraZajac/JUDGMENT · live forecasts: https://judgment.karazajac.io

## Abstract

We present JUDGMENT, an end-to-end system for forecasting Supreme Court behavior at the level of individual justice votes and case outcomes, built on the Supreme Court Database (SCDB) and evaluated exclusively by walk-forward validation over 69 terms (1956–2024). A gradient-boosted model over strictly pre-decision features attains **67.9% justice-vote accuracy** (Brier 0.207, AUC 0.688) and **69.6% case-outcome accuracy** in its deployed configuration — exceeding our own full-SCDB research configuration (66.8%/67.6%) and decisively beating base-rate, justice-history, and attitudinal baselines (McNemar p < 10⁻²⁷). Three methodological contributions travel beyond this system. First, *deployment honesty*: the configuration that publishes forecasts is restricted to features actually knowable for a granted-but-undecided case and is validated separately; we show the unrestricted model produces degenerate forecasts when confronted with deployment missingness patterns. Second, a *two-factor coalition model* over calibrated per-justice marginals replaces the ubiquitous vote-independence assumption, improving out-of-sample split-distribution log-loss by 45% (independence predicts 4.4% unanimous reversals; reality is 34.0%; the coalition model predicts 31.5%) while also improving binary outcome accuracy and Brier. Third, a *twice-tested negative result*: cert-stage question text, entered through leakage-safe per-step latent semantic features, does not improve prediction either alone or — refuting the interaction hypothesis directly — in the presence of lower-court direction; in this framework, content adds nothing beyond structure, while one hand-codable structural judgment (the ideological direction of the decision below) is worth 3.4 accuracy points. All probabilities are prospectively recalibrated (ECE ≈ 0.02), justice ideal points are estimated by a penalized-ML Martin–Quinn variant with bootstrap uncertainty, and every forecast for the pending docket is publicly timestamped in a git-versioned registry that scores itself as decisions land.

## 1. Introduction

Quantitative prediction of Supreme Court behavior has a distinguished lineage: ideal-point models of judicial ideology (Martin & Quinn 2002), pre-confirmation ideology scores (Segal & Cover 1989), the celebrated statistical-models-versus-experts contest of the 2002 term (Ruger et al. 2004), and general machine-learning models spanning two centuries of decisions (Katz, Bommarito & Blackman 2017). Yet published systems are difficult to audit as *forecasters*: evaluations vary in leakage discipline, probability calibration is rarely reported, case-level probabilities are almost universally computed under an indefensible independence assumption across the nine votes, and — most fundamentally — retrospective accuracy does not establish that a system's *deployable* configuration, facing the information actually available before decision, performs as advertised.

JUDGMENT is designed around those gaps. Its contributions:

1. **A leakage-audited feature policy** (§4.2): every justice-level feature is computed from terms strictly before the prediction term; nothing downstream of the vote enters; the first-term cold-start is honest (shrunk priors only). Automated assertions enforce the policy.
2. **Walk-forward-only evaluation** (§4.3) against principled baselines with exact significance tests, plus *prospective* isotonic recalibration in which term T's calibration map is fit only on out-of-sample predictions from terms before T.
3. **Deployment honesty** (§4.6): the published forecaster is a separately validated configuration restricted to cert-stage-available features. We document that the full research model, whose accuracy headlines would normally be quoted, collapses to degenerate output under deployment missingness — a failure mode invisible to standard evaluation.
4. **Coalition-aware aggregation** (§4.5): a two-factor probit model (case valence + signed ideology) over exactly-preserved calibrated marginals, fit on the system's own out-of-sample predictions and evaluated on held-out terms.
5. **A structural-versus-content finding** (§5.3): lower-court direction — one hand-codable judgment per case — is worth +3.4 points; question-presented text, tested twice with leakage-safe latent semantic features, is worth nothing, even with its hypothesized interaction partner present.
6. **A live preregistered registry** (§6): forecasts for every granted-but-undecided case are published with timestamps in a git-attested record — revisable only while the case remains undecided, with any post-decision vintage excluded from scoring — scored automatically as decisions land — including a same-day vote-extraction pipeline that parses the Court's own slip-opinion syllabi (validated at 98% against independently coded lineups).

## 2. Related work

**Ideal points.** Martin & Quinn (2002) introduced dynamic Bayesian item-response modeling of justices' latent positions; their scores are the field's standard ideology measure. We re-estimate ideal points in a penalized-ML variant of their model (§4.4) rather than consuming published scores, attach parametric-bootstrap uncertainty, and test their *predictive* contribution — which proves nil beyond lagged behavioral rates, an instructive redundancy.

**Prediction.** Ruger et al. (2004) showed simple classification trees beating a panel of experts on the 2002 term (75% vs 59% case accuracy). Katz, Bommarito & Blackman (2017) built random forests over SCDB features for 1816–2015, reporting 70.2% case / 71.9% justice-vote accuracy against a time-varying null; theirs is the benchmark general model. Our headline numbers are computed on the modern discretionary-certiorari era only (1946+ data; evaluation 1956–2024), a structurally harder window — mandatory-jurisdiction eras inflate predictability — so cross-paper comparisons are indicative, not head-to-head. Crowd-sourced forecasting (FantasySCOTUS) demonstrates that aggregated human prediction is strong on recent terms; our registry design (§6) is built to permit exactly such comparisons prospectively.

**Calibration and aggregation.** Probability quality is rarely front-and-center in this literature. We report Brier, log-loss, and expected calibration error throughout, and treat the independence assumption in vote-to-case aggregation as a first-class modeling defect rather than a footnote.

## 3. Data

### 3.1 Canonical corpus

The Supreme Court Database (Spaeth et al.; modern 2025 Release 1 and Legacy Release 7, Citation unit) supplies 29,202 cases and 255,832 justice-vote records spanning the 1791–2024 terms. Our pipeline restructures the corpus into per-case YAML records (votes embedded, closed code sets decoded against the SCDB codebook) and per-justice records combining curated biography with computed voting histories. Structural validation (id/filename coherence, vote-token validity, tally consistency against SCDB's own counts, membership integrity) runs on every build; residual soft findings are upstream SCDB quirks and are documented rather than silently repaired. Justice biographies for the modern era (40 justices) are hand-curated from public record; the 77 earlier justices are enriched from the Federal Judicial Center's Biographical Directory, with multi-appointment persons (elevations; the two Hughes tenures) resolved by era-overlap matching and the FJC convention that retired justices' "termination" is death handled by preferring senior-status dates.

### 3.2 The living edge

SCDB is annual; the term in progress is invisible to it for months. Three ingestion layers close the gap, each writing records flagged `provisional` and replaced wholesale when SCDB coverage arrives:

- **Oyez** supplies decided-case metadata, party names, dates, and — with days-to-weeks lag — per-justice votes with opinion authorship and joins.
- **CourtListener** search supplies near-real-time decision events for cases Oyez has not yet listed (notably signed emergency-docket opinions).
- **Slip-opinion syllabi** (this work): the Court's own PDFs are public within minutes of decision, and each syllabus ends with a canonical lineup paragraph ("*Roberts, C. J., delivered the opinion of the Court, in which…*"). We parse the term's slip-opinion index and extract per-justice votes, concurrence types, authorship, and non-participation from these paragraphs. The parser is **validation-gated**: it must reproduce the lineups of independently (Oyez-)coded cases before it may write anything; it currently agrees on 39 of 40 such cases (98%), the exception being a dismissed-as-improvidently-granted case that the comparison source itself codes only partially. Document-forensic hazards we handle explicitly — justice-title abbreviation periods that shred sentence segmentation, preliminary-print typography, ligature corruption ("filed" → "fled"), Roman-numeral clause merging, revision sub-blocks in the index markup — are enumerated in the repository for replicators.

The pending docket (granted-but-undecided cases: the forecasting targets) is maintained from Oyez grant/argument timelines and supremecourt.gov per-docket JSON (argument scheduling), with question-presented text preserved. One subtlety matters for correctness: every upstream source keys consolidated decisions to the lead docket alone — the slip-opinion index and CourtListener carry only the lead, Oyez leaves companions "pending" indefinitely, and SCDB ultimately issues one record. A map parsed from the slip-opinion syllabus footnote ("*Together with No. …") therefore resolves companion dockets to their deciding record, prunes them from the pending docket, and routes their forecasts to the correct outcome (seven such pairs in OT2025 alone).

### 3.3 Auxiliary corpora

Question-presented texts for 3,418 historical cases (Oyez; near-complete for the 2000s–2020s, sparse before the mid-1990s) support the text experiments of §5.3. Lower-court opinions matched via docket-number joins through CourtListener accumulate as training data for a direction classifier (in progress; the deployed system uses hand-coded direction with documented bases, §4.6).

## 4. Methods

### 4.1 Targets

Primary: does justice *j* vote to **disturb the judgment below** (reverse family = reversed / reversed-and-remanded / vacated(-and-remanded) / partial reversals; affirm = affirmed), defined where SCDB codes both disposition and majority membership — the observable, ideology-coding-free target comparable to Katz et al. Secondary: the SCDB **liberal/conservative direction** of the vote, which inherits the Spaeth coding conventions and their critiques. Case outcome is the majority side of the nine (or fewer, with recusals) votes.

### 4.2 Features and the availability policy

All features must be knowable before decision. Case features are cert-stage facts as coded by SCDB: issue area, law type, certiorari reason, jurisdiction, lower-court disposition direction and inter-court disagreement, three-judge-district-court flag, origin/source court and party codes (top-K categoricals), United-States-as-party indicators, and term. Justice features are computed from votes in terms **strictly before** the prediction term, at term granularity: tenure; appointing president's party; empirical-Bayes-shrunk career and last-three-term rates of reversal-voting and liberal-voting; the justice's lagged lean within the case's issue area (career and, as a tested variant, last-three-terms); majority-membership and dissent rates; and a pooled court-level reversal-drift term. Shrinkage priors are themselves lagged global means, so no channel leaks. First-term justices carry pure priors with zero prior observations — asserted programmatically on every feature build.

Nothing downstream of the vote (disposition, direction, majority size, opinion data, decision type) is ever a feature. We follow the literature (and flag the optimism) in treating SCDB's post-hoc issue coding as cert-stage-knowable for historical evaluation; the deployed forecaster uses hand-coded provisional issue areas instead (§4.6).

### 4.3 Evaluation protocol

Train on terms ≤ T−1, predict every vote of term T, roll T over 1956–2024 (ten burn-in terms). Never random splits: they leak court composition and era. The learner is gradient-boosted trees (`HistGradientBoostingClassifier`; native categorical handling and missingness; fixed seed). Baselines, all computed within each training window: (i) base rate; (ii) the justice's own lagged shrunk rate; (iii) the classic attitudinal heuristic — P(reverse) = P(justice's lean opposes the direction of the decision below); (iv) for the direction target, P(liberal | appointing party). Significance: exact McNemar tests at the vote level. Metrics: accuracy, Brier, log-loss, ROC-AUC, and expected calibration error, sliced by decade, justice, and issue area.

**Prospective recalibration.** Raw model probabilities are recalibrated by isotonic regression fitted, for each evaluation term T, only on out-of-sample predictions from terms before T — exactly what a live forecaster could have done at the time. This is evaluated like everything else and reduces vote-level ECE from 0.078 to 0.020 (reverse) and 0.077 to 0.012 (liberal) with slight Brier improvements.

### 4.4 Dynamic ideal points with uncertainty

We estimate a one-dimensional dynamic item-response model — P(vote_ij = reverse) = σ(β_i θ_j,t(i) − α_i) with random-walk smoothing on trajectories and ridge priors on case parameters — by alternating Newton steps (per-case 2×2 solves; per-justice banded/tridiagonal smoothing), i.e., a penalized-ML/MAP variant of Martin & Quinn's sampler, with location/scale/sign identification per sweep (conservative positive). Uncertainty comes from a parametric bootstrap (B = 60 sign-aligned, warm-started refits): median per-justice-term standard error 0.104, widening exactly where data thin (short tenures, sparse terms). Face validity: the 2024-term ordering reproduces the consensus (Sotomayor −1.44 … Roberts +0.09, Kavanaugh +0.23 … Thomas +1.39); Blackmun's canonical leftward drift (+0.86 → −1.11) and Ginsburg's (−0.25 → −1.18) emerge unprompted, as does Black's late-career rightward move.

### 4.5 Coalition-aware aggregation

Aggregating nine per-justice probabilities into case-level outcomes by independence is statistically indefensible: it predicted 4.4% unanimous reversals on our evaluation window against an observed 34.0%. We replace it with a two-factor probit coalition structure over the calibrated marginals:

  vote_j | (u, v) ~ Bernoulli( Φ( μ_j + λ₀u + λ₁ s_j v ) ),  u, v ~ N(0,1) shared within a case,

with μ_j = √(1 + λ₀² + λ₁²s_j²) · Φ⁻¹(p_j) so that **each justice's calibrated marginal p_j is preserved exactly**. The factor u is case *valence* (clear cases move everyone together); v is *ideology*, loaded by the signed, leakage-free lean s_j = 2(0.5 − lagged liberal share). Split distributions are computed by two-dimensional Gauss–Hermite quadrature (no Monte Carlo). The two loadings are fit by maximizing the likelihood of actual reverse-vote counts on the system's own cached walk-forward predictions for terms ≤ 2010 (λ₀ = 1.85, λ₁ = 2.15) and evaluated on 2011–2024.

### 4.6 Deployment honesty

The configuration that publishes forecasts is **pinned** — never inferred from artifact presence — and is restricted to features that exist for a real granted-but-undecided case: the justice-history block, hand-coded issue area and lower-court direction (each with a documented per-case basis; the anchor for direction is that certiorari petitioners lost below, classified under SCDB conventions; ambiguous cases stay honestly uncoded), U.S.-party name flags, and certiorari jurisdiction. This subset is walk-forward validated end-to-end like every other configuration, and its own out-of-sample predictions supply its calibrator.

This discipline is not decorative. When the full research model was first pointed at pending cases, its never-seen missingness constellation (absent lower-court codings, party codes, court codes) routed into unreliable leaves and produced degenerate ~1.00 forecasts for every case — a catastrophic failure invisible to conventional evaluation, caught only because deployment was treated as its own validated configuration.

## 5. Results

### 5.1 Main results (walk-forward, 1956–2024)

Vote-level, reverse target (n = 67,047–75,787 depending on configuration window):

| configuration | accuracy | Brier | AUC |
|---|---|---|---|
| base rate | 64.6% | 0.229 | 0.49 |
| justice lagged rate | 64.6% | 0.227 | 0.55 |
| attitudinal heuristic | 62.3% | 0.228 | 0.66 |
| full research configuration | 66.8% | 0.216 | 0.68 |
| deployed: cert-stage subset | 64.4% | 0.224 | 0.60 |
| deployed + lower-court direction | 67.8% | 0.208 | 0.686 |
| **deployed + lc + recent topic lean (final)** | **67.9%** | **0.207** | **0.688** |

Model-vs-baseline McNemar: p ≈ 8×10⁻²⁸ (justice baseline), p ≈ 9×10⁻⁹¹ (attitudinal). Case-level (coalition aggregation, 2011–2024 evaluation window): **69.6% accuracy, Brier 0.211** — versus 69.0%/0.227 under independence on identical inputs. The direction target reaches 66.1% (AUC 0.727). Prospective recalibration: ECE 0.020 (reverse), 0.012 (liberal).

Two orderings deserve emphasis. The lean deployed configuration **outperforms the full research configuration** — the battery of post-hoc court/party codings adds more variance than signal once the decision below and justice history are known. And a single hand-codable judgment per case (lower-court direction) is worth **+3.4 accuracy points and +0.09 AUC**, the largest single-feature effect in the system.

### 5.2 Ablations and the ideal-point redundancy

Feature-group ablations (reverse, 1990–2024): removing case features costs discrimination (AUC 0.646 → 0.527) while accuracy hides behind the base rate; removing justice features costs both (accuracy 65.1% → 62.2%); removing ideology features costs AUC (→ 0.630). Adding leak-free lagged ideal points (expanding refits) to the full configuration changes nothing (65.2% vs 65.1%; Brier within 0.001): the behavioral priors already carry the latent-position signal — a redundancy worth knowing before anyone treats estimated ideal points as privileged predictive inputs.

### 5.3 Content versus structure: a twice-tested negative

We harvested question-presented text for 3,418 cases and entered it through leakage-safe, per-step TF-IDF + truncated-SVD features (vocabulary, IDF, and basis fit on each training window only; missing text handled natively). Tested alone on the deployment subset: **64.4% → 63.9%**, Brier worse. The natural rescue hypothesis — topic matters only through its interaction with the direction of the decision below — was then tested directly by adding text to the configuration that *has* lower-court direction: **67.8% → 67.6%**. Both negative. The residual topic signal is already carried by the issue-area feature; in this framework, *content adds nothing beyond structure*. (The recent topic-lean feature — the justice's last-three-term lean within the case's issue area — was adopted on probability-quality grounds: Brier 0.2076 → 0.2069, AUC 0.686 → 0.688, accuracy within noise.)

### 5.4 Coalition model results

Out-of-sample (2011–2024) split-distribution log-loss improves from 3.752 (independence) to 2.064 (**−45%**). Predicted-versus-actual split frequencies on nine-member cases:

| split | actual | independence | coalition |
|---|---|---|---|
| 9–0 | .340 | .044 | .315 |
| 8–1 | .067 | .128 | .120 |
| 7–2 | .076 | .206 | .093 |
| 6–3 | .117 | .233 | .084 |
| 5–4 | .128 | .193 | .072 |
| 0–9 | .103 | .000 | .084 |

The pathology of independence is stark — essentially zero mass on unanimity in a Court that is unanimous a third of the time. The coalition model recovers both unanimity modes and, non-obviously, also improves the *binary* case outcome (accuracy 69.0% → 69.6%; Brier 0.227 → 0.211; log-loss 0.725 → 0.613): it is strictly better, not a splits-for-sharpness trade. Residual honesty: 5–4 mass remains underpredicted — the bimodal "big case" regime likely needs a third factor or mixture, left to future work.

## 6. The live registry

Every granted-but-undecided case receives a forecast: calibrated P(reverse), per-justice probabilities for both targets, and the full coalition split distribution, each file carrying model version, feature-availability notes, and hand-coding bases. Pending-case forecasts are re-issued at each refresh as hand-codings improve; every vintage is timestamped in the public git history, and the scorer enforces the preregistration property directly rather than by convention: a forecast whose file was (re)generated on or after its case's decision date is excluded from the track record as *not ex-ante*, never scored. Post-hoc revision is thus both detectable and inert. As decisions land (via the interim and syllabus pipelines, with consolidated companions resolved to their deciding record per §3), a scorer resolves outcomes (SCDB disposition tokens when available; a flagged winning-party proxy for provisional records), computes case- and justice-level hits and Brier, and publishes a running track record. At this writing the registry holds 17 forecasts, 16 awaiting decision (every case leaning reverse, reflecting certiorari selection's ~70% recent-term reversal base rate). The registry's first resolution exercised the exclusion rule rather than the scorer: *Little v. Hecox* was decided as a consolidated companion of *West Virginia v. B.P.J.* days before its forecast's final regeneration, so it enters the record as not ex-ante — excluded even though it would have scored as a hit. The system self-updates: daily decision-day pipeline (interim ingest, syllabus vote extraction, scoring), daily lower-court-opinion harvesting, weekly full refresh — all committed by CI with substantive-change detection.

## 7. Limitations

(1) Historical evaluation treats SCDB issue coding as cert-stage-knowable; deployment uses hand-coded provisional values with documented bases — an unavoidable asymmetry we surface rather than hide. (2) Lower-court direction, the most valuable deployment feature, is presently a human judgment call per grant (two minutes; classifier assistance in progress) — coding bases are published for audit. (3) The coalition model underpredicts 5–4 outcomes; two factors cannot express bimodal polarization fully. (4) Forecasts are conditional on a merits ruling: mootness, DIGs, and other procedural off-ramps lie outside the outcome space. (5) The direction target inherits SCDB's ideological coding conventions and their critiques. (6) MAP ideal points carry bootstrap standard errors, not full posteriors. (7) Docket composition drifts across the evaluation window (~150 → ~60 cases/term); per-decade slices are reported and no single headline number should be quoted without them. (8) Provisional-era records (votes parsed from syllabi or Oyez) are re-writable until SCDB supersedes them; the registry's scored outcomes flag their resolution basis.

## 8. Conclusion

A Supreme Court forecaster can be simultaneously simple, honest, and strong: a lean set of behavioral priors plus one structural judgment about the decision below outperforms both rich post-hoc codings and text-derived content, provided the evaluation never peeks. The methodological centerpiece is not any single accuracy number but the discipline connecting them: leakage-audited features, walk-forward-only evaluation, prospective calibration, deployment-matched validation, coalition-aware probabilities, and a public registry that will confirm or embarrass every claim here in real time.

## Data and code availability

All code (MIT), the derived dataset, validation artifacts, and the forecast registry are public at https://github.com/KaraZajac/JUDGMENT and archived at DOI [10.5281/zenodo.21211376](https://doi.org/10.5281/zenodo.21211376) (concept DOI; resolves to the latest archived version); the browsable site is https://judgment.karazajac.io. The dataset derives from the Supreme Court Database (Spaeth, Epstein, Martin, Segal, Ruger & Benesh — required citation; free for research with attribution), Oyez, CourtListener/Free Law Project, the Federal Judicial Center, and public-domain federal court opinions.

## References

Katz, D. M., Bommarito, M. J., & Blackman, J. (2017). A general approach for predicting the behavior of the Supreme Court of the United States. *PLOS ONE*, 12(4), e0174698.

Martin, A. D., & Quinn, K. M. (2002). Dynamic ideal point estimation via Markov chain Monte Carlo for the U.S. Supreme Court, 1953–1999. *Political Analysis*, 10(2), 134–153.

Ruger, T. W., Kim, P. T., Martin, A. D., & Quinn, K. M. (2004). The Supreme Court forecasting project: Legal and political science approaches to predicting Supreme Court decisionmaking. *Columbia Law Review*, 104(4), 1150–1210.

Segal, J. A., & Cover, A. D. (1989). Ideological values and the votes of U.S. Supreme Court justices. *American Political Science Review*, 83(2), 557–565.

Spaeth, H. J., Epstein, L., Martin, A. D., Segal, J. A., Ruger, T. J., & Benesh, S. C. *The Supreme Court Database*, Version 2025 Release 1 and Legacy Release 7. http://scdb.wustl.edu.

Epstein, L., Landes, W. M., & Posner, R. A. (2013). *The Behavior of Federal Judges*. Harvard University Press.
