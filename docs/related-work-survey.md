# Who beats JUDGMENT, and why: a verified survey of SCOTUS prediction systems

*Compiled 2026-07-06 via multi-agent deep research: 5 search angles, 15+ primary
sources fetched, every load-bearing claim adversarially verified by independent
3-vote panels (a claim dies on 2/3 refutations). Votes below are cumulative
across merged claims. Baseline for comparison: JUDGMENT's walk-forward 1956–2024
deployed configuration — 67.9% justice-vote (Brier 0.207, AUC 0.688), 69.6% case
outcome, cert-stage features only, isotonic-calibrated (ECE ≈ 0.02).*

## Scoreboard

| System | Reported | Window / regime | Beats JUDGMENT? |
|---|---|---|---|
| Katz–Bommarito–Blackman 2017 (random forest) | 70.2% case / 71.9% vote | 1816–2015, out-of-sample, **decision-date** features | Nominally; regime-inflated |
| Kaufman–Kraft–Sen 2019 (AdaBoost) | 74.04% case | 2005–2015, **pooled 10-fold CV**, oral-argument text | Post-argument only |
| FantasySCOTUS crowd, OT2011–2016 | ~74.1% case / ~73.5% vote (fair); 80.8/77.1 post-hoc ceiling | 425 cases, revisable until decision eve | **Yes** (with later information) |
| FantasySCOTUS crowd, live OT2025 | 94.74% case / 91.42% vote (self-scored) | 57 decided cases, single term | **Yes** (post-argument info) |
| FantasySCOTUS crowd, OT2009 | crowd ~50%; top-3 post-hoc 75.7% | 81 cases, single term | No |
| Hamilton 2023 (9 × GPT-2 agents) | 60% case (κ≈0.18) | 96 cases, 2010–2016 held-out | No |
| JUSTICE benchmark (Oyez facts text) | ≤68% (best single model) | Augmented + mirrored data, random split (leaky) | No |
| {Marshall}+ (algorithmic, FantasySCOTUS) | 0 predictions OT2025 | Dormant | No (inactive) |
| Polymarket | ~$2.4M across ~12 SCOTUS markets; one $3 merits market | Episodic salient cases only | Not comparable |

## The three systems with higher numbers, and where the gaps come from

### 1. Katz–Bommarito–Blackman 2017 — regime, not modeling *(verified 9-0)*

70.2% case / 71.9% justice-vote over 1816–2015 (~28,000 cases, 240k+ votes),
time-evolving random forest, genuinely out-of-sample. Three qualifiers:

- **Leakage discipline is decision-date, not cert-stage.** Features explicitly
  include whether oral argument was heard, whether there was a rehearing, and
  elapsed time from argument to decision — all unavailable at cert.
  (Feature list verified verbatim in the PLOS ONE text; "certiorari" appears
  once, in procedural background.)
- **Two-century window** vs JUDGMENT's modern-only evaluation.
- **The edge over trivial nulls is ~2 points**: their own toughest null reaches
  67.5%, and Medvedeva et al. (AI & Law, 2022) characterize the result as "a
  small improvement over the 68% baseline accuracy where the petitioner always
  wins."
- A tempting stronger claim — that KBB's own Roberts-era performance dip proves
  historical-era inflation — was **refuted 0-3** (the dip is relative to
  strengthening null baselines, and the authors explicitly decline that
  interpretation). Only the window *difference* can be asserted, not era
  inflation.

Sources: doi:10.1371/journal.pone.0174698; doi:10.1007/s10506-021-09306-3.

### 2. Kaufman–Kraft–Sen 2019 — the whole edge is oral argument *(verified 9-0)*

74.04% case accuracy (highest published academic number) vs a 67.98%
always-petitioner baseline, AdaBoosted trees, 2005–2015 (~900 cases). Verified
from the published *Political Analysis* version, Table 1:

- **Oral-argument features alone: 72.5%. SCDB case covariates alone: 60.6% —
  7.4 points BELOW the baseline.** The authors state no case-covariates-only
  model surpasses baseline.
- Evaluation is **pooled tenfold cross-validation** — training folds contain
  cases *later* than test cases — and a footnote concedes some covariates
  (e.g., issue area) are coded post-ruling.
- Verdict: no evidence against JUDGMENT at cert stage; strong evidence that
  **argument-stage text is worth ~5–6 points** as a post-argument update.

Sources: doi:10.1017/pan.2018.59.

### 3. The FantasySCOTUS human crowd — information, not modeling *(verified 11-1 / 6-0)*

The one system that genuinely outperforms, under fair readings:

- **OT2011–2016** (425 cases, 7,284 participants, 600k+ predictions; arXiv
  1712.03846): mean/median aggregation ~74.1% case / ~73.5% vote. The famous
  80.8%/77.1% is the authors' own **post-hoc ceiling** over 277,201 aggregation
  configurations evaluated on the same sample — not a deployable number. A
  pre-committable "follow the leader" rule scores 72.8/72.2. No Brier, AUC, or
  calibration anywhere.
- **Live OT2025** (fetched 2026-07-05/06 from the platform's own JSON): 57 of
  58 argued cases decided; crowd self-scores **94.74% case (54/57) and 91.42%
  per-vote (469/513)**. Decisive detail: in a term with 64.9% reversals and
  42.1% unanimous decisions, an *oracle that knows every outcome* and predicts
  all-majority votes would score only **83.2% per-vote** — the crowd beats the
  outcome-oracle ceiling, so it is genuinely predicting **dissent structure**.
- **Mechanism**: predictions are revisable until midnight before decision, so
  they embed briefing, oral argument, and news — information a cert-stage
  system cannot have. Single self-scored term; no calibration; no
  preregistration; no probabilities.
- Historical honesty: the **OT2009** crowd predicted only "more than fifty
  percent" correctly (below the always-reverse null); the era's famous "75%"
  belongs to a post-hoc-selected top-3 subgroup, and the platform's creators
  later excluded OT2009 data as incomparable.

Sources: arXiv:1712.03846; fantasyscotus.net/case/list/;
Northwestern J. Tech. & Intell. Prop. 10(3).

## What does NOT beat JUDGMENT

- **LLM predictors, 2023–2026** *(9-0)*: Hamilton's nine-GPT-2-agent Court
  simulation: 60% case, per-justice 50–65% (all below 67.9%). Posner & Saran's
  "Judge AI" (GPT-4o): a simulated ICTY appeal, reports no real-court accuracy.
  The 2025 31-LLM study on 59 real 2024-term cases does ideological scaling,
  reports no accuracy. **No verified LLM system reports SCOTUS prediction
  accuracy above JUDGMENT.**
- **JUSTICE benchmark** *(6-0)*: ≤68% despite an easier and demonstrably leaky
  regime (BERT-augmented near-duplicates + party-mirroring to 50-50 balance,
  then a random split with no case grouping — up to 10 variants of one case
  straddle train/test; a k=3 KNN topping the table is the leakage signature).
- **Most of the "legal judgment prediction" literature** *(3-0, medium)*:
  Medvedeva, Wieling & Vols (AI & Law, 2022) find most published work
  classifies **post-decision documents** — categorisation, not forecasting.
  (Scope limit: their survey classifies KBB 2017 and KKS 2019 as genuine
  forecasting; the critique hits the broad text literature, not the flagships.)

## The empty lane *(verified 3-0 / 2-1)*

As of mid-2026 there is **no live algorithmic SCOTUS forecaster**:
{Marshall}+ is dormant for OT2025 (0.00% in every algorithmic field, zero
predictions, "Prediction pending..." on cases decided months ago), and
Polymarket's SCOTUS section (~$2.4M, ~12 markets) is personnel/vacancy
dominated — the only active merits-outcome market on a pending case holds $3
of volume, though clusters do appear episodically for salient cases (a
~$4.8M tariffs cluster, including a per-justice vote-count market, resolved
2026-02-20). The only live benchmark is the human crowd: accurate,
uncalibrated, self-scored, post-argument-informed.

**JUDGMENT's prospective, preregistered, calibrated registry currently has the
lane to itself.**

## Adoptable improvements, ranked

1. **Argument-stage features** (KKS: +5–6 points; KBB uses argument-occurrence
   features too). Oyez transcripts are already a planned source. The right
   architecture is a **staged forecast**: the cert-stage forecast stands as
   registered, and a post-argument update re-registers with its own timestamp
   — both scored separately. This extends the registry rather than diluting
   its cert-stage claim.
2. **Crowd/market signals as a benchmark, not a feature**: score the registry
   against the FantasySCOTUS crowd per term (they publish per-case data);
   report Brier/calibration the crowd cannot. The 83.2%-oracle-ceiling
   analysis is worth reporting alongside — it shows what per-vote accuracy
   above ~83% *means*.
3. **Not adoptable**: JUSTICE-style text augmentation (leaky), LLM vote
   simulation (below baseline so far), market prices (no systematic coverage).

## For paper §2 (related work)

- KBB: keep as benchmark, add the decision-date-vs-cert-stage distinction and
  the ~2-point null edge (with Medvedeva's characterization).
- Add KKS as the highest academic number, with the 60.6%-below-baseline
  covariates-only result — it independently corroborates JUDGMENT's finding
  that structure-at-cert is hard and content arrives with argument.
- FantasySCOTUS: cite the 74.1% fair-aggregation number, not the 80.8%
  post-hoc ceiling; note the live OT2025 crowd and its revisable-until-eve
  information regime.
- The prospective-registry paragraph can now cite the dormancy of {Marshall}+
  and the absence of any live calibrated algorithmic forecaster.
