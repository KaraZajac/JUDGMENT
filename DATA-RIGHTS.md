# Data rights and attribution

This repository is a **derived research dataset** plus original code and model
outputs. Rights are layered; the umbrella license for the dataset release is
**CC BY-NC 4.0** (matching the most restrictive upstream terms), with the
layers below. The code is separately licensed under [MIT](LICENSE).

| layer | contents | provenance | terms |
|---|---|---|---|
| SCDB-derived records | `data/cases/` (canonical), `data/justices/` computed records, aggregates, codebook | Supreme Court Database (Spaeth, Epstein, Martin, Segal, Ruger & Benesh), restructured and decoded | Free for research **with attribution**, non-commercial; SCDB is the canonical source and must be cited (see below) |
| Federal court opinions & syllabus-derived votes | `data/text/lc/`, slip-opinion-derived vote records | U.S. federal courts via supremecourt.gov and CourtListener | **Public domain** (edicts of government, 17 U.S.C. § 105) |
| FJC biographical data | legacy-justice `service`/`bio` blocks | Federal Judicial Center, Biographical Directory of Article III Federal Judges | **Public domain** (U.S. government work) |
| Oyez-derived content | question-presented texts (`data/text/questions.yaml`, docket questions), provisional vote codings, party names/dates | Oyez (oyez.org) | Attribution, non-commercial |
| CourtListener-derived events | provisional decision records, citations | Free Law Project / CourtListener | Public-domain records; attribution appreciated |
| Original contributions | curated biographies, hand-coding files with bases, ideal points + uncertainty, coalition parameters, forecasts and scorecard, all pipeline/model code, documentation | this project | Code MIT; data/model outputs CC BY-NC 4.0 |

**Required citation (SCDB):** Harold J. Spaeth, Lee Epstein, Andrew D. Martin,
Jeffrey A. Segal, Theodore J. Ruger & Sara C. Benesh, *The Supreme Court
Database*, Version 2025 Release 1 and Legacy Release 7, http://scdb.wustl.edu.

**Citing this project:** see [CITATION.cff](CITATION.cff) (and the DOI once the
archival release is minted).

Research and educational use only. This project is unaffiliated with SCDB,
Oyez, the Free Law Project, the Federal Judicial Center, and the Supreme Court
of the United States. Nothing here is legal advice.
