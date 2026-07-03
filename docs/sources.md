# Data sources

## 1. Supreme Court Database (SCDB) — in use, primary

The canonical, justice-vote-level database of every Supreme Court decision, maintained
by Spaeth, Epstein, Martin, Segal, Ruger & Benesh. Two eras, four files ingested:

| file | unit | coverage |
|---|---|---|
| `SCDB_2025_01_caseCentered_Citation` | case | 1946 term – 2024 term |
| `SCDB_2025_01_justiceCentered_Citation` | justice × case | 1946 – 2024 |
| `SCDB_Legacy_07_caseCentered_Citation` | case | 1791 – 1945 |
| `SCDB_Legacy_07_justiceCentered_Citation` | justice × case | 1791 – 1945 |

- Mirrors: http://scdb.wustl.edu (brick files under `/_brickFiles/<release>/`; used by
  `pipeline/download.py`) and https://scdb.la.psu.edu/ (current maintenance home).
- Unit choice: *Citation* = one record per case citation (consolidated dockets and
  split votes collapsed). The finer-grained Docket/LegalProvision/Vote units exist
  upstream if we ever need them.
- New releases land roughly annually (release `<year>_01`); the downloader probes for
  the newest.
- License/terms: free for research with attribution; see the SCDB site for terms.
- **Required citation:** Harold J. Spaeth, Lee Epstein, Andrew D. Martin, Jeffrey A.
  Segal, Theodore J. Ruger, and Sara C. Benesh. *Supreme Court Database*, Version 2025
  Release 1 (modern) and Legacy Release 7. URL: http://scdb.wustl.edu

## 2. Curated justice background — in use

`pipeline/curated/justices.yaml`, hand-maintained in this repo: full names, appointing
president + party, oath/departure dates, confirmation votes, birth/death, law school,
prior roles. Coverage: all 40 justices of the modern era (every justice serving during
the 1946+ terms). Legacy-era justices currently get mechanically-derived names and
computed voting records only; enriching them from the Epstein et al. *U.S. Supreme
Court Justices Database* is a roadmap item.

## 3. Martin–Quinn scores — planned (source currently unreachable)

Dynamic ideal-point estimates per justice-term (Martin & Quinn 2002, *Political
Analysis* 10:134–153), the standard "ideology over time" measure. As of 2026-07 the
distribution site (mqscores.wustl.edu) serves no data files; the old
`/media/justices.csv` path 404s. `ideology.martin_quinn` is reserved in the justice
schema. Interim substitute (already computed): per-term liberal vote share from SCDB
directions. Longer term we intend to re-estimate ideal points ourselves
(docs/modeling.md, phase 2), which also removes the dependency.

## 4. Segal–Cover scores — planned

Perceived qualifications/ideology of nominees from pre-confirmation newspaper
editorials (Segal & Cover 1989, *APSR* 83:557–565). Useful as a cold-start prior for
newly seated justices. Values to be ingested with verification against the published
table (post-1937 nominees).

## 5. Opinion texts — planned (modeling phase 3)

- U.S. Reports bound-volume PDFs: https://www.supremecourt.gov/opinions/USReports.aspx
  (authoritative, but PDF; slip and in-chambers opinions also on supremecourt.gov)
- CourtListener / Free Law Project API and the Caselaw Access Project: machine-readable
  full text, better suited to feature extraction than the PDFs.
- Oyez (api.oyez.org): oral-argument audio/transcripts and justice bios.

Text is deliberately out of scope for the v0.1 dataset; the YAML schema keeps case
files citation-keyed (`us`, `docket`) so texts can be joined later without rework.
