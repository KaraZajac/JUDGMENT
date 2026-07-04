# The prediction engine

Forecasts Supreme Court behavior at two levels — each justice's vote and the case
outcome — with a methodology built to survive committee scrutiny: leak-free
features, walk-forward validation only, principled baselines, calibrated
probabilities, ablations, and a written limitations section. Results live in
[`output/report-reverse.md`](output/report-reverse.md) (primary target) and
[`output/report-liberal.md`](output/report-liberal.md).

## Pipeline

```sh
.venv/bin/python -m models.features                       # leak-free feature table (cached)
.venv/bin/python -m models.walkforward                    # main evaluation, both targets
.venv/bin/python -m models.walkforward --ablations        # feature-group ablations
.venv/bin/python -m models.walkforward --pending-config --target both   # deployed subset
.venv/bin/python -m models.ideal_points --filtered        # dynamic ideal points (+ leak-free)
.venv/bin/python -m models.walkforward --theta            # ideal-point contribution test
.venv/bin/python -m models.report                         # render reports + calibration
.venv/bin/python -m models.export_calibrators             # portable calibrators (for CI)
.venv/bin/python -m models.predict                        # forecast the pending docket
.venv/bin/python -m models.score                          # score decided forecasts
```

Forecast files are immutable once issued (git history is the preregistration
record); `models.score` writes `data/forecasts/scorecard.yaml`, surfaced as the
Track record on the site's /predict page. A weekly GitHub Action
(`.github/workflows/refresh.yml`) re-runs ingestion, forecasting, and scoring.

## Design, in dissertation terms

**Targets.** Primary: the justice votes to disturb the judgment below
(reverse/affirm — observable, ideology-coding-free, comparable to Katz–Bommarito–
Blackman 2017). Secondary: the SCDB-liberal directional vote.

**Features** (`features.py`) obey a strict availability policy: case facts knowable
at cert (issue area, law type, cert reason, jurisdiction, lower-court direction and
disagreement, court and party codes, U.S.-party flags) and justice history computed
from terms *strictly before* the prediction term (tenure, appointing party, EB-shrunk
career/recent reverse and liberal rates, per-issue-area lean, majority/dissent
rates, pooled court reversal drift). Nothing downstream of the vote is a feature.
First-term justices carry pure priors — the cold start is honest.

**Model.** Gradient-boosted trees (`HistGradientBoostingClassifier`) with native
categoricals and missing-value handling; fixed seed. Case outcomes aggregate the
nine vote probabilities by Poisson-binomial majority (independence assumption —
documented limitation).

**Validation.** Train on terms ≤ T−1, predict term T, roll 1956→2024. Never random
splits. Compared against: training-window base rate, the justice's own lagged rate,
the attitudinal lower-court heuristic, and (direction target) party-of-appointer.
Significance via exact McNemar. Probabilities are recalibrated **prospectively** —
term T's calibration map is isotonic regression fitted only on out-of-sample
predictions from terms before T.

**Ideal points** (`ideal_points.py`). A penalized-ML variant of Martin–Quinn dynamic
IRT (alternating Newton: per-case 2×2 solves, per-justice banded smoothing;
location/scale/sign identified per sweep). Full-history trajectories go to
`data/scores/ideal-points.yaml`; an expanding-refit variant provides leak-free
lagged scores whose predictive contribution is tested as a model variant.

**Lower-court direction (adopted 2026-07).** The single highest-value deployment
feature: the ideological direction of the decision below, hand-codable per pending
case from the petitioner-lost-below anchor plus SCDB issue conventions
(`pending_lc.yaml`, with per-case bases). Walk-forward validated at **67.8%**
reverse / 66.3% liberal — the lean cert-stage subset plus lc_direction outperforms
the full research configuration (66.8%), whose extra court/party codings apparently
add more variance than signal. Per-justice forecasts now carry the attitudinal
structure (conservatives high P(reverse) on liberal rulings below, inverted on
conservative ones).

**Recent topic lean (adopted 2026-07).** The justice's last-3-terms liberal share
within the case's issue area (`prior_issue_liberal_3t`) — the "topic trend"
hypothesis. Marginal but consistent gain on the primary target (reverse Brier
0.2076 → 0.2069, AUC 0.686 → 0.688, accuracy within noise; liberal target a wash);
adopted on probability-quality grounds. Per-justice topic trajectories are also
visualized on every justice page ("Voting by topic over time").

**Text features (tested twice, not deployed).** Question-presented text —
cert-stage by construction — was harvested for 3,418 historical cases
(`pipeline/questions.py`) and entered as leakage-safe per-step TF-IDF/LSA
components (`--text`). **Negative both times:** without lc_direction (64.4% →
63.9%) and, refuting the interaction hypothesis, with it (67.8% → 67.6%).
Content adds nothing beyond structure in this framework. The corpus and machinery
remain for richer text sources (lower-court opinions, oral argument). The deployed
configuration is pinned in `predict.py` (`DEPLOY_CONFIG`) and changes only with
fresh validation evidence.

**Deployment honesty.** The live forecaster (`predict.py`) uses only the feature
subset that exists for a granted-but-undecided case, and that exact subset is
walk-forward validated separately (`--pending-config`) — the full model's
missing-pattern behavior on never-seen feature constellations is degenerate, so
publishing full-model forecasts on sparse rows would be indefensible. Hand-coded
provisional issue areas for pending cases live in `pending_issues.yaml` with their
coding basis. Forecasts land in `data/forecasts/<term>/<id>.yaml` with model
version, feature-availability notes, per-justice probabilities, and the full
reverse-vote split distribution.

## Known limitations

Vote-independence in case aggregation; SCDB direction-coding conventions; post-hoc
issue coding (optimistic in historical evaluation, hand-coded provisionally in
deployment); docket-composition drift across eras; shrunk-prior cold starts for new
justices; MAP (not posterior) ideal points. Each is expanded in the reports.
