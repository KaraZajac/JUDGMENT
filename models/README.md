# models/

Prediction models live here (future phase — see [docs/modeling.md](../docs/modeling.md)).

Planned contents:

- `baselines/` — always-reverse, party-of-appointing-president, ideal-point cutpoint rules
- `ideal_points/` — dynamic Bayesian item-response (Martin–Quinn-style) ideal point estimation
- `supervised/` — gradient-boosted tree vote/outcome models with walk-forward term validation
- `forecasts/` — generated predictions for pending cases, consumed by the Astro site

Nothing here is implemented yet; the dataset in `data/` comes first.
