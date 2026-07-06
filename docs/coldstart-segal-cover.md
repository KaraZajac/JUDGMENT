# Cold-start experiment: Segal–Cover scores — tested, not adopted

*2026-07-06. Config `pending_config_lc_issue3t_sc` = deployed cert config +
`sc_ideology` (perceived nomination-time liberalism, 0–1, from
pre-confirmation newspaper editorials; `pipeline/curated/segal_cover.yaml`,
41 confirmed nominees 1937–2020, hand-checked). Nomination-time constants
are cert-stage-knowable, so this was a candidate for the deployed cert
config. Hypothesis: the score informs the cold-start slice where behavioral
priors carry nothing.*

## Verdict: NOT adopted

| Slice (reverse target) | n | Δ accuracy | Δ Brier | McNemar p |
|---|---|---|---|---|
| All rows | 67,047 | −0.08pp | +0.0003 | 0.28 |
| Tenure ≤ 2 | 8,347 | +0.01pp | +0.0001 | 1.0 |
| **First term only** | **2,133** | **+0.70pp** | +0.0004 | **0.18** |

Liberal target, first term: +0.89pp (p = 0.11), Brier +0.0018.

Reading: directionally positive exactly where the hypothesis lives — the
first-term slice — on both targets, but underpowered (two thousand votes
cannot confirm a sub-point effect) and with no probability-quality gain. Two
structural reasons the marginal effect is small:

1. **`appointer_party` is already in the deployed config**, so the score's
   crude half is priced in; what was tested is only its residual (the
   within-party variation: Souter 0.325 vs Scalia 0.000, both Republican
   appointees).
2. One editorial-derived scalar per justice is a thin signal against a
   feature block that dominates from term 2 onward.

Per the house rule (text features were rejected twice on evidence like
this), `sc_ideology` stays out of the deployed configuration. The curated
scores remain in the repo — they are the fallback cold-start covariate for
justices with no prior judicial record (Kagan, Warren, Rehnquist), which
matters for the next tier.

## Why this strengthens the behavioral-records tier

If a single perceived-ideology scalar noisily buys +0.7–0.9pp on first-term
votes, an actual pre-SCOTUS *voting record* — years of circuit-court
behavior, direction-coded — is the same hypothesis with far more signal:
per-issue-area rates, dissent behavior, en banc votes. Plan of record:

- **Songer/Kuersten–Haire Courts of Appeals Database** (judge-level coded
  votes, 1925–2002) for twentieth-century appointees' circuit records;
- **CourtListener harvest** for post-2002 circuit service (Roberts, Alito,
  Sotomayor, Gorsuch, Kavanaugh, Barrett, Jackson — FJC service windows
  already ingested);
- integrate as justice-specific **shrinkage anchors** for the behavioral
  priors (shrink toward the pre-SCOTUS-informed rate instead of the global
  mean; self-phases-out as SCOTUS history accumulates), with Segal–Cover as
  the anchor of last resort for never-judges;
- gate on the first-term/first-3-terms slice, powered by pooling all ~40
  modern justices' debuts.

Artifacts: `models/output/metrics-{reverse,liberal}-pending-config-lc-issue3t-sc.yaml`.
