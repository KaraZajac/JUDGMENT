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

## Addendum 2026-07-07: stage-2 config superseded by `sg_oa2`

Two further candidates were gated the day after adoption:

**SG-as-amicus** (`sg_amicus`): which side the United States supports as
amicus at oral argument, extracted from the Oyez advocate metadata already
in the corpus (723 cases, 1955–2024; no new harvesting). On SG-covered rows
it is the strongest single feature since lc_direction: **68.05% → 73.24%
(+5.19pp), Brier 0.2060 → 0.1836, McNemar p ≈ 8×10⁻¹⁷** — the SG-supported
side actually reverses 75.8% vs 42.3%, and the model prices it almost
perfectly (73.6% / 44.7%). Sparse-history note: all-NaN training windows in
the late 1950s crash sklearn's binner; fit_predict now drops features that
are all-NaN in a given training window (correct semantics for any
sparse-history feature).

**Format-robust word-centric set** (`ORAL2_FEATURES`): word differentials
plus `oa_share_vs_base` (this case's petitioner word share minus the
justice's own lagged 3-term mean — leak-free, deployable). Alone it does
not recover 2020s accuracy but improves Brier everywhere (2020s 0.2045 →
0.2003) and is markedly less harmed by the pre-1970s attribution heuristic.

**Together they solve the seriatim-era problem.** Final table (reverse):

| config | acc | Brier | AUC | 2020s covered acc |
|---|---|---|---|---|
| oa (turns, adopted 07-06) | 69.09% | 0.2025 | 0.716 | 68.6% |
| oa2 (words) | 68.99% | 0.2019 | 0.716 | 68.3% |
| oa + sg | 69.54% | 0.1998 | 0.723 | — |
| **sg_oa2 (adopted)** | **69.61%** | **0.1997** | **0.723** | **72.5%** |
| union (oa+oa2+sg) | 69.78% | 0.1998 | 0.723 | (liberal profile worse) |

`sg_oa2`'s liberal target also leads (67.96%, Brier 0.2068, AUC 0.7441).
The union's +0.17pp reverse accuracy did not justify four extra features
and a worse liberal profile — parsimony held. **2020s covered slice: 68.6%
→ 72.5%, Brier 0.2045 → 0.1872** — the current Court's format is now the
model's best modern era rather than its flatlined one.

STAGE2_CONFIG is repinned to `pending_config_lc_issue3t_sg_oa2`;
calibrators re-exported; deploy-time features replicate the training
constructions exactly (share baselines via the same EB-shrunk lagged-3-term
machinery). Verified end-to-end by simulation: SG-supports-respondent plus
respondent-side grilling moved a case from 0.679 (frozen cert) to 0.578 —
both signals integrating in the right direction.
