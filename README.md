# JUDGMENT

[![DOI](https://zenodo.org/badge/1288707509.svg)](https://doi.org/10.5281/zenodo.21211376)

**A statistical model of every U.S. Supreme Court judgment — every justice, every
vote, every opinion — built toward forecasting how the Court will rule.**

**Live site: [judgment.karazajac.io](https://judgment.karazajac.io/)** —
browse every case since 1791, justice ideology trajectories, and calibrated
forecasts for the pending docket, publicly timestamped before the Court rules.

This repository contains, as browsable YAML:

| | |
|---|---:|
| Cases (1791 term – 2024 term) | **29,202** |
| Individual justice votes | **255,832** |
| Justices (40 with curated biographies) | **117** |
| Natural courts | **108** |

plus the ETL pipeline that regenerates all of it from the authoritative sources, and
a [modeling roadmap](docs/modeling.md) aimed at publication-grade prediction of case
outcomes, per-justice votes, and ideology trajectories over time.

## What's here

```
data/
├── cases/<term>/<caseId>.yaml   # one file per case: outcome, issue, lower court,
│                                #   parties, opinions, and all 9 justice votes
├── docket/<term>/<id>.yaml      # pending cases (granted/argued, awaiting decision)
├── oral/<term>.yaml             # per-justice oral-argument questioning counts
│                                #   (side-attributed turns/words; 1955–present)
├── timing/<term>.yaml           # cert-grant dates (Oyez-derived; dense 2004+)
├── justices/<slug>.yaml         # bio + appointment + computed voting record and
│                                #   term-by-term ideological trajectory
├── justices/index.yaml          # roster with SCDB ids and mnemonics
├── courts/natural-courts.yaml   # membership of each stable court composition
├── codebook/                    # code ↔ token ↔ label tables for decoded fields
└── meta.yaml                    # source versions and dataset counts
pipeline/                        # download → build → validate (Python, stdlib + PyYAML)
docs/                            # data model, source registry, paper, modeling roadmap
models/                          # walk-forward vote prediction, ideal points, forecasts
site/                            # Astro site: browse the data, live forecasts
```

A case file looks like this (Dobbs, abridged):

```yaml
id: 2021-019
name: DOBBS v. JACKSON WOMEN'S HEALTH ORGANIZATION
term: 2021
decision:
  type: opinion-of-the-court
  disposition: reversed-and-remanded
  direction: conservative
  precedent_altered: true
  majority_votes: 6
  minority_votes: 3
issue: {code: 50020, area: privacy}
opinions:
  majority_author: SAAlito
votes:
- justice: JGRoberts
  vote: special-concurrence
  opinion: wrote
  in_majority: true
- justice: SGBreyer
  vote: dissent
  opinion: co-wrote
  in_majority: false
  joined: [SSotomayor, EKagan]
# ... all nine justices
```

and each justice file carries the "leanings over time" series computed from their
actual votes:

```yaml
name: Ruth Bader Ginsburg
service: {appointed_by: Bill Clinton, party: Democratic, oath: '1993-08-10'}
ideology:
  career_liberal_share: 0.604
  by_term:
    1993: {liberal_share: 0.543, n: 94}
    # ... every term through 2019
```

Full schema reference: [docs/data-model.md](docs/data-model.md).

## Regenerating the dataset

Requires Python ≥ 3.11 and PyYAML. From the repo root:

```sh
python3 -m pipeline.download   # fetch newest SCDB releases (~96 MB CSV into sources/)
python3 -m pipeline.build      # regenerate data/ (~29k YAML files, ~2 minutes)
python3 -m pipeline.interim    # provisional current-term cases (Oyez + CourtListener)
python3 -m pipeline.aggregates # per-term rollups for the site
python3 -m pipeline.agreement  # justice-pair agreement matrices per natural court
python3 -m pipeline.questions  # question-presented text corpus (manual; ~1h first run)
python3 -m pipeline.oral_args --terms 1955 2024  # oral-argument questioning corpus
python3 -m pipeline.validate   # structural + consistency checks
```

A weekly GitHub Action (`.github/workflows/refresh.yml`) runs the whole chain —
including new-SCDB-release pickup, forecasting, and forecast scoring — and commits
only substantive changes; `.github/workflows/ci.yml` validates the corpus and
builds every site page on each push.

SCDB lands annually, so `interim` bridges the gap: the term in progress (and the one
just ended) is ingested from Oyez and CourtListener as `provisional: true` records —
votes and outcomes only, no SCDB coding — and replaced wholesale when the next SCDB
release covers it.

The build is deterministic: same sources + same curated inputs ⇒ identical YAML.
Hand-maintained facts (appointments, confirmation votes, bios) live in
`pipeline/curated/justices.yaml`, never in `data/`.

## Data sources

- **Supreme Court Database (SCDB)** — modern (2025 Release 1) and legacy (Release 7),
  Citation unit, case- and justice-centered. The backbone of everything here.
  *Required citation:* Harold J. Spaeth, Lee Epstein, Andrew D. Martin, Jeffrey A.
  Segal, Theodore J. Ruger & Sara C. Benesh, **The Supreme Court Database**
  (http://scdb.wustl.edu / https://scdb.la.psu.edu).
- **Curated justice background** — maintained in this repo for all 40 modern-era
  justices (see docs/sources.md for conventions).
- **Oyez + CourtListener** — interim ingest of the current term (per-justice votes,
  outcomes, dates) until SCDB's annual release catches up.
- **Oral-argument transcripts (Oyez)** — per-justice questioning features for 7,023
  argued cases (96% of 1955–2024), powering the post-argument forecast stage
  (gate result: [docs/postargument-gate.md](docs/postargument-gate.md)).
- Planned: Martin–Quinn ideal points, Segal–Cover nominee scores, opinion texts
  (supremecourt.gov U.S. Reports, CourtListener).
  Details and status: [docs/sources.md](docs/sources.md).

## The goal

Phase by phase (full detail in [docs/modeling.md](docs/modeling.md)):

1. **Descriptive** — agreement matrices, reversal base rates, ideology trajectories ✦ *done*
2. **Baselines** — party-of-appointer, issue-area priors, lower-court heuristics ✦ *done*
3. **Dynamic ideal points** — Bayesian IRT re-estimation of justice ideology over time ✦ *done*
4. **Supervised vote prediction** — walk-forward validated, benchmarked against
   Katz–Bommarito–Blackman (70.2% case / 71.9% justice-vote accuracy) ✦ *done:
   67.9% per-vote at cert stage; 69.6% post-argument (Brier 0.200)*
5. **Text features** — question text rejected twice on evidence; oral-argument
   questioning + the SG's amicus position adopted for the post-argument stage
6. **Forecasts** — calibrated predictions for pending cases, published via the Astro
   site in `site/` and scored when decisions land; scoring is strictly ex-ante (a
   forecast regenerated on or after decision day never enters the track record), and
   consolidated decisions resolve to their lead docket via `data/consolidations.yaml`

## Paper and citation

A full methods paper draft lives at [docs/paper.md](docs/paper.md). To cite this
project, see [CITATION.cff](CITATION.cff) or use the archival concept DOI
[10.5281/zenodo.21211376](https://doi.org/10.5281/zenodo.21211376), which always
resolves to the latest archived version (v1.1.0: 10.5281/zenodo.21213039); rights and
attribution for the layered dataset are documented in
[DATA-RIGHTS.md](DATA-RIGHTS.md).

## Licensing

Code and original documentation: [MIT](LICENSE). The generated dataset derives from
the Supreme Court Database, which is free for research use with attribution and
carries its own terms — cite SCDB (above) in any work built on `data/`. This project
is unaffiliated with SCDB and with the Supreme Court of the United States.

*Research and educational use only; nothing here is legal advice or a claim about
how any real case should be decided.*
