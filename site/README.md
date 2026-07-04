# site/

Astro frontend over the YAML dataset in `../data` — no database, no API; pages read
the YAML directly (small shared files cached per process, case files parsed on demand).

## Run it

```sh
cd site
npm install
npm run dev        # http://localhost:4321
```

Dev mode renders on demand, so the ~29k case routes cost nothing until visited.
A full `astro build` prerenders every page (slow, only needed for static hosting).

## Pages

| route | what |
|---|---|
| `/` | headline stats, the Court's direction term-by-term (1791–present), latest decisions, and the pending docket |
| `/predict` | calibrated forecasts for every pending case: P(reverse), split distributions, per-justice probabilities, argument schedule, and the scored track record |
| `/justices` | all 117 justices: tenure, appointer, career lean |
| `/justices/<slug>` | bio, record, ideological trajectory, lean by issue area |
| `/terms` | every term: direction mix, reversal rate, unanimity |
| `/terms/<term>` | one term: splits histogram, direction, full case table |
| `/cases/<caseId>` | one case: facts grid + the vote, grouped majority/dissent |
| `/courts` | natural courts (stable benches) with linked members |

## Design notes

Charts follow a validated diverging convention throughout: **blue = liberal side,
red = conservative side** (SCDB direction coding), columns diverging from the 50%
baseline. Light/dark are both first-class (`prefers-color-scheme`). Every chart has
hover/focus tooltips and a collapsible data table; identity is never color-alone.

Term aggregates come from `python3 -m pipeline.aggregates` (→ `data/aggregates/`);
re-run it after rebuilding the dataset. Provisional current-term cases (from
`pipeline.interim`) render with a notice banner and honest "—" wherever SCDB coding
doesn't exist yet.
