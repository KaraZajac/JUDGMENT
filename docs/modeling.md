# Modeling roadmap

> **Status (2026-07):** Phases 1–3 have a first implementation in `models/` —
> leak-free features, walk-forward evaluation with baselines and McNemar tests,
> prospective isotonic calibration, feature ablations, penalized-ML dynamic ideal
> points, and a deployment-matched pending-docket forecaster writing
> `data/forecasts/`. Results: `models/output/report-{reverse,liberal}.md`.
> Phase 4 text was tested twice (question-presented corpus + leakage-safe LSA,
> alone and with lower-court direction): **negative both times** — content adds
> nothing beyond structure here. Hand-codable lower-court direction was
> **adopted** instead (deployed accuracy 64.4% → 67.8%, exceeding the full
> research configuration). Richer text sources (lower-court opinions, oral
> argument) and full Bayesian posteriors remain open.

Goal: forecast, for each pending or hypothetical case, (a) the outcome (affirm/reverse,
petitioner/respondent), (b) each justice's vote and its direction, (c) the vote split
distribution, and (d) longitudinal ideology trajectories per justice — at or above the
published state of the art, with honest, leakage-free validation.

## Prediction targets

1. **Case outcome** — binary "petitioner wins" (`decision.winning_party`), and
   disposition class (affirm vs reverse-family).
2. **Justice vote** — per sitting justice: majority/dissent and directional vote.
3. **Vote split** — distribution over {9-0, 8-1, …, 5-4} conditioned on membership.
4. **Ideology trajectories** — per-justice ideal points by term, with uncertainty.

## Benchmarks to beat (published literature)

- Always-guess-reverse: ~63–68% case-outcome accuracy historically (the Court takes
  cases to reverse; base rate varies by era).
- Ruger et al. 2004 (*Columbia L. Rev.* 104) — statistical trees beat legal experts
  (75% vs 59% case outcomes, 2002 term).
- Katz, Bommarito & Blackman 2017 (*PLOS ONE* 12(4)) — random forest over SCDB
  features, 1816–2015 walk-forward: **70.2% case / 71.9% justice-vote accuracy**. This
  is the reference general model; we replicate it as our supervised baseline.
- Martin & Quinn 2002 — dynamic Bayesian ideal points; the standard ideology measure.
- FantasySCOTUS crowd forecasts — useful accuracy yardstick on recent terms.

## Phases

### Phase 0 — descriptive foundations (unblocked now)
Agreement matrices per natural court; per-justice liberal-share trajectories (already
emitted into `data/justices/*.yaml`); reversal base rates by era/issue/circuit;
docket-composition drift. Sanity-checks the dataset and seeds site visualizations.

### Phase 1 — static baselines
Party-of-appointing-president; career/issue-area directional priors; lower-court
direction heuristic (vote to reverse ⊕ lc direction); logistic regression per justice
with issue-area effects. Establishes the floor and the validation harness.

### Phase 2 — dynamic ideal points (the ideology engine)
Re-estimate Martin–Quinn-style dynamic ideal points from our own vote matrix
(Bayesian 1-D dynamic IRT: justice ideal point θ_jt with random-walk prior, case
cut-point/discrimination from vote coalitions; NUTS or EM). Deliverables: θ_jt ±
credible intervals per justice-term in `ideology.martin_quinn`-compatible form;
court median trajectory; validation against published MQ scores where they overlap.
Cold-start for new justices via Segal–Cover priors + circuit-record covariates.

### Phase 3 — supervised vote prediction
Gradient-boosted trees / random forests per the Katz-Bommarito-Blackman feature space:
justice identity & tenure, ideal point (phase 2), issue area, law type, cert reason,
lower-court direction & disagreement, origin circuit, party types (US as party, SG),
natural-court composition, term-trend features. Strict walk-forward by term (train ≤
T−1, predict T). Then: hierarchical logit with justice random effects for calibrated
probabilities; ensemble with the trees. Metrics: accuracy, Brier, log-loss, AUC,
reliability curves — reported per era, per justice, per issue area, always against
the phase-1 baselines and published benchmarks.

### Phase 4 — text & argument features
Add case text: cert-stage documents, lower-court opinion, oral-argument transcripts
(question counts and interruption asymmetries are known predictors), amicus volume.
Embedding features from opinion text for issue typing beyond SCDB codes.

### Phase 5 — forecasting service
For each granted-but-undecided case: predicted outcome + per-justice votes + split
distribution with calibrated uncertainty, versioned at prediction time (pre-argument /
post-argument snapshots), published as YAML → consumed by the Astro site; scored
publicly when the decision lands.

## Validation protocol (non-negotiable)

- **Walk-forward only.** Train on terms ≤ T−1, evaluate on term T, roll forward. No
  random splits: they leak court composition and era effects.
- Probabilistic scoring (Brier/log-loss) alongside accuracy; calibration plots per model.
- Freeze feature availability at prediction time (e.g. no post-argument features in
  pre-argument forecasts).
- Uncertainty on everything reported (bootstrap over cases; posterior for IRT).

## Known pitfalls (so we don't rediscover them)

- **Selection effects**: the cert process is strategic (Priest–Klein); reversal-heavy
  dockets make "always reverse" strong and mean model skill must be measured against
  it, not against 50%.
- **SCDB direction coding** is issue-contextual (pro-defendant = liberal in criminal
  procedure, anti-regulation = conservative in economics) and contested at the margins
  (see the Harvey/Shapiro critiques). Treat `direction` as a modeling convention, not
  ground truth; sensitivity-check against outcome-based measures.
- **Issue codes are assigned post-hoc** by coders reading the opinion — fine for
  historical fitting, but forecasting pending cases requires predicting/deriving the
  issue from cert-stage materials (phase 4).
- **Membership churn**: mid-term replacements, recusals (OT2016 8-member stretches),
  and per curiams distort per-term aggregates; condition on participation.
- **Shadow docket**: SCDB covers the signed/argued merits docket; emergency orders are
  a different (growing) universe, out of scope for now.
- **Small N per term** (~55–80 modern cases): report intervals, not point brags.

## References

Martin & Quinn 2002, *Political Analysis* 10:134–153 · Segal & Cover 1989, *APSR*
83:557–565 · Ruger, Kim, Martin & Quinn 2004, *Columbia L. Rev.* 104:1150 · Katz,
Bommarito & Blackman 2017, *PLOS ONE* 12(4):e0174698 · Epstein, Landes & Posner 2013,
*The Behavior of Federal Judges* · Spaeth et al., *Supreme Court Database* codebook.
