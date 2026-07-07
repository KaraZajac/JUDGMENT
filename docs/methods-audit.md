# Methods audit: three committee questions, answered with experiments

*2026-07-07. Prompted by the question "is this defendable as a dissertation?"
— the three sharpest methodological criticisms we could level at ourselves,
each turned into a runnable experiment. Scripts inline in the session record;
all inputs are the committed walk-forward per-row prediction artifacts.*

## 1. Adaptive selection on a reused validation window → nested replay

**The criticism.** Every feature gate (five rejections, four adoptions) was
evaluated on the same 1956–2024 walk-forward window; adopting the best of
~10 comparisons risks overfitting the validation set, inflating the headline.

**The experiment.** Replay the entire adoption sequence making every
adopt/reject decision from metrics computed on **1956–2010 only** (the same
decision rules: accuracy for the lc/text steps, the six-metric two-target
profile rule thereafter), then score the surviving configuration on
**2011–2024, which no decision ever touched.**

**Result: the nested procedure reproduces the actual configuration chain
exactly** — lc adopted, text rejected, issue3t adopted (5/6 profile),
Segal–Cover/circuit/dissent-below rejected (1/6, 0/6, 2/6), oa adopted,
and sg_oa2 winning the stage-2 tournament (6/6 against oa_sg; the union
rejected 2/6) — with no access to the 2020s evidence that informally
motivated parts of the actual choice. On the untouched holdout:

| config | reverse acc | Brier | AUC | liberal acc | Brier | AUC |
|---|---|---|---|---|---|---|
| base pending_config | 64.46% | 0.2295 | 0.534 | 59.55% | 0.2386 | 0.632 |
| cert (nested = actual) | 66.32% | 0.2172 | 0.623 | 64.51% | 0.2212 | 0.700 |
| stage 2 (nested = actual) | **71.47%** | **0.1902** | **0.737** | **69.00%** | **0.2019** | **0.754** |

The selected configuration performs *better* on the untouched window than on
the full window. The adaptive-selection criticism is answered.

## 2. Vote clustering in significance tests → case-clustered bootstrap

**The criticism.** McNemar tests treated the nine votes of a case as
independent; they share an outcome, so naive p-values overstate evidence.

**The experiment.** Case-clustered bootstrap (4,000 draws, resampling
caseIds) of the accuracy difference for every load-bearing claim:

| comparison | Δ accuracy | 95% CI | clustered p |
|---|---|---|---|
| lc_direction vs base | +3.45pp | [+3.02, +3.86] | ≤ 0.0005 |
| issue3t vs lc | +0.07pp | [−0.11, +0.26] | 0.45 |
| oral args vs cert (covered rows) | +1.73pp | [+1.11, +2.33] | ≤ 0.0005 |
| SG-amicus vs oa (SG-covered rows) | +5.19pp | [+3.32, +7.10] | ≤ 0.0005 |
| final sg_oa2 vs oa (all rows) | +0.52pp | [+0.11, +0.92] | 0.015 |
| cert config vs justice baseline | +3.28pp | [+2.72, +3.84] | ≤ 0.0005 |

Every accuracy-based adoption survives clustering. The one null — issue3t's
accuracy — matches its adoption record exactly: it was adopted on
probability quality with accuracy declared "within noise," and the nested
replay independently re-adopts it on the profile rule.

## 3. The pre-1970s order heuristic → validated against ground truth

**The criticism.** Side attribution for pre-1970s arguments uses an order
heuristic (petitioner opens and rebuts) that was asserted, never measured.

**The experiment.** On 527 description-era cases (1985–2023, nine terms),
delete the advocate descriptions, apply the heuristic blind, compare
(1,760 sections, 61,955 justice-turns):

| argument structure | section agreement |
|---|---|
| 2 distinct advocates (the pre-1970s norm) | **99.0%** (861/870) |
| 3 distinct advocates | 61.0% |
| 4+ | 40.9% |
| aggregate (modern mix) | 79.2% |

On the two-advocate structure that dominates the era the heuristic serves,
it is essentially exact. Its errors concentrate in multi-advocate arguments
(amicus participation, divided argument) — a minority of pre-1970s cases —
which quantifies the residual noise behind the 1950s–60s negative deltas in
the questioning features. Optional refinement (not taken; would require
re-gating the corpus): refuse attribution when ≥3 distinct advocates argue,
trading wrong labels for missing ones.

## Standing pre-commitment

When SCDB's annual release covers OT2025 (~October 2026), we will publish
the agreement rate between our cert-stage hand-codes (issue area,
lower-court direction) and SCDB's official coding for the same cases —
whatever it turns out to be. That measures the train/deploy coding
asymmetry (paper §7, limitation 1) on the exact cases we forecast.
