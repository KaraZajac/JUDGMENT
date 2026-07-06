# Post-argument configuration: walk-forward gate result

*2026-07-06. Config `pending_config_lc_issue3t_oa` = the deployed cert-stage
config + five oral-argument questioning features (per-justice turn
differential, word share toward the petitioner side, engagement; two
bench-wide case aggregates). Corpus: `data/oral/` — 7,023 argued cases,
96% of 1955–2024 (pipeline.oral_args). Same walk-forward protocol as every
deployed configuration: train < term T, predict T, 1956–2024.*

## Verdict: PASSES the gate — adopt for the post-argument stage

| Metric (reverse target) | cert config | + oral args | Δ |
|---|---|---|---|
| Vote accuracy, all rows | 67.90% | **69.09%** | +1.19pp |
| Vote accuracy, covered rows | 66.54% | **68.26%** | **+1.72pp** |
| Brier, all rows | 0.2069 | **0.2025** | −0.0044 |
| AUC, all rows | 0.688 | **0.716** | +0.028 |
| McNemar (covered rows) | | fixes 4,671 / breaks 3,933 | p ≈ 1.9×10⁻¹⁵ |

Liberal target, covered rows: 65.11% → 66.58% (+1.47pp).

## The signal is era-structured — this is the finding that matters

Per-decade covered-rows deltas (reverse):

| Era | Δ accuracy | Δ Brier | Reading |
|---|---|---|---|
| 1950s | −4.8pp | +0.037 | hurts: order-heuristic side attribution, cold benches, thin oral training data |
| 1960s | −1.3pp | +0.010 | slightly hurts |
| 1970s | −0.2pp | +0.002 | neutral |
| **1980s** | **+3.8pp** | **−0.013** | strong |
| **1990s** | **+4.1pp** | **−0.021** | strong |
| **2000s** | **+3.8pp** | **−0.020** | strong |
| **2010s** | **+4.7pp** | **−0.027** | strongest |
| 2020s | −0.3pp | −0.001 | **neutral so far — see caveat** |

Across 1980–2019 the questioning signal is worth **+4 points of per-vote
accuracy, sustained for four decades** — the per-justice, walk-forward
counterpart of Kaufman–Kraft–Sen's +5–6 case-level points (pooled CV,
2005–2015), and consistent with the Johnson/Black questioning-asymmetry
literature.

**The 2020s caveat.** Since OT2020 the Court's argument format changed:
free-for-all questioning is followed by seriatim justice-by-justice rounds,
in which *every* justice questions *every* advocate. That mechanically
compresses turn-count asymmetries, and the 2020s covered delta is ~zero
(n=2,405 — wide CI, but visibly weaker than the four prior decades). The
early-era negative deltas are the mirror image: attribution and behavior
both differ from the signal's home era.

## Deployment decision

Adopt `pending_config_lc_issue3t_oa` as the **post-argument stage** config
(paper §6): argued pending cases get a second, separately-registered and
separately-scored forecast. The cert-stage forecast and its validated
config are untouched. The 2020s format caveat ships with it — the live
stage-2 track record is the arbiter, which is what the registry is for.

Follow-up worth one experiment: format-robust features for the seriatim era
(word-based shares normalized within justice, engagement-above-own-baseline)
evaluated on the 2020s slice specifically.

Artifacts: `models/output/metrics-{reverse,liberal}-pending-config-lc-issue3t-oa.yaml`;
per-row predictions in the walk-forward cache; corpus and coverage in
`data/oral/<term>.yaml`.
