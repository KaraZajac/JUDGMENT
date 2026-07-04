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
.venv/bin/python -m models.predict                        # forecast the pending docket
```

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
