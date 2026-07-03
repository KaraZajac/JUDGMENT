# Data model

Everything under `data/` is **generated** by `python3 -m pipeline.build` from the raw
SCDB downloads plus the hand-maintained inputs in `pipeline/curated/`. Never edit
`data/` by hand — edit the pipeline or the curated inputs and rebuild.

## Conventions

- **Dates are plain strings**, `YYYY-MM-DD`. (Not YAML timestamps — string dates load
  identically in Python, JS/Astro, and everything else.)
- **Absent means absent.** Fields the source did not code are omitted, not `null`.
- **Two decoding tiers**, chosen per field:
  - *Complete decode* — where the SCDB code set is small, closed, and fully mapped in
    `pipeline/codes.py`, the YAML stores a human-readable kebab-case token
    (e.g. `disposition: reversed-and-remanded`). The code↔token↔label tables are
    emitted to `data/codebook/`.
  - *Raw code* — where the SCDB code set is huge (issue: ~280 codes, parties: ~350,
    courts: ~200), the YAML keeps the numeric code in a small dict, e.g.
    `issue: {code: 20130, area: civil-rights}`. Decode with the official SCDB online
    codebook (see `data/codebook/README.md`). Enriching these into local codebook
    files is a roadmap item.
- **Join key for justices** is the SCDB `justiceName` mnemonic (e.g. `JGRoberts`,
  `RBGinsburg`). `data/justices/index.yaml` maps mnemonics to file slugs and numeric
  SCDB ids.

## Case files — `data/cases/<term>/<caseId>.yaml`

One file per case, keyed by SCDB `caseId` (`<term>-<seq>`, e.g. `2022-055`). Built from
the *Citation*-unit SCDB releases: one record per case as published in the U.S. Reports;
consolidated dockets and multi-issue votes are collapsed to the lead record.

```yaml
id: 2022-055
name: STUDENTS FOR FAIR ADMISSIONS, INC. v. PRESIDENT AND FELLOWS OF HARVARD COLLEGE
term: 2022                     # October Term (OT2022 runs Oct 2022 – early Oct 2023)
chief: Roberts                 # chief justice at decision
natural_court: 1707            # SCDB naturalCourt code; see data/courts/natural-courts.yaml
docket: "20-1199"
citation:                      # omitted sub-keys were not assigned
  us: 600 U.S. 181
  sct: ...
  lexis: ...
dates:
  argued: "2022-10-31"
  decided: "2023-06-29"
decision:
  type: opinion-of-the-court   # decisionType (complete decode)
  disposition: reversed        # caseDisposition (complete decode)
  winning_party: petitioner    # partyWinning: petitioner | respondent | unclear
  direction: conservative      # decisionDirection: conservative | liberal | unspecifiable
  precedent_altered: false     # precedentAlteration
  unconstitutional: none       # declarationUncon: none | federal-statute | state-law | local-ordinance
  majority_votes: 6            # majVotes
  minority_votes: 2            # minVotes
issue:
  code: 20130                  # SCDB issue (raw)
  area: civil-rights           # issueArea (complete decode, 14 areas)
law:                           # legal provision considered
  type: constitutional-amendment  # lawType (complete decode)
  supp: 210                    # lawSupp (raw)
  minor: "..."                 # lawMinor (free text, rare)
authority: [judicial-review-national]   # authorityDecision1/2 (complete decode)
jurisdiction: {code: 1, label: certiorari}  # label present only for common codes
cert_reason: to-resolve-important-question  # certReason (complete decode)
lower_court:
  origin: {code: 300}          # caseOrigin (raw court code)
  source: {code: 300}          # caseSource (court reviewed, raw)
  disposition: affirmed        # lcDisposition (complete decode)
  direction: liberal           # lcDispositionDirection
  disagreement: false          # lcDisagreement (dissent noted below)
parties:
  petitioner: {code: 249}      # SCDB party codes (raw)
  respondent: {code: 176}
  petitioner_state: {code: 0}  # only when coded
admin_action: {agency: 117}    # only when an administrative agency acted first
flags:                         # only emitted when true / unusual
  three_judge_district_court: true
  vote_unclear: true
  disposition_unusual: true
  second_vote: true            # splitVote == 2
opinions:
  majority_author: JGRoberts   # majOpinWriter, decoded to justiceName mnemonic
  majority_assigner: JGRoberts # majOpinAssigner
votes:                         # from the justice-centered release; docket order
  - justice: JGRoberts
    vote: majority             # see data/codebook/vote.yaml (8 vote types)
    opinion: wrote             # none omitted | wrote | co-wrote
    direction: conservative    # this justice's vote direction
    in_majority: true
    joined: [CThomas]          # firstAgreement/secondAgreement, when coded
  - justice: KBJackson
    participated: false        # justice sat but SCDB records no vote (recusal etc.)
```

### Vote tokens (`votes[].vote`)

| token | SCDB code | meaning |
|---|---|---|
| `majority` | 1 | voted with majority or plurality |
| `dissent` | 2 | dissent |
| `regular-concurrence` | 3 | concurrence in majority opinion |
| `special-concurrence` | 4 | concurs in result but not majority opinion |
| `judgment-of-the-court` | 5 | judgment of the Court |
| `dissent-from-cert-denial` | 6 | dissent from denial/dismissal of cert or appeal |
| `jurisdictional-dissent` | 7 | jurisdictional dissent |
| `equally-divided` | 8 | participation in an equally divided vote |

## Justice files — `data/justices/<slug>.yaml`

One file per justice who has ever cast a recorded vote (legacy + modern eras merged).
Two blocks with different provenance:

```yaml
slug: ruth-bader-ginsburg
name: Ruth Bader Ginsburg
scdb: {name: RBGinsburg, id: 109}
service:                       # curated (pipeline/curated/justices.yaml) — modern era only
  position: associate          # associate | chief
  appointed_by: Bill Clinton
  party: Democratic            # party of the appointing president
  oath: "1993-08-10"
  ended: "2020-09-18"
  end_reason: died             # died | retired | resigned (in office ⇒ `ended` absent)
  confirmation_vote: 96-3
bio:                           # curated — modern era only
  born: "1933-03-15"
  died: "2020-09-18"
  law_school: Columbia
  prior: [D.C. Circuit judge, ACLU Women's Rights Project co-founder]
record:                        # computed from SCDB votes — every justice has this
  first_decision: "1993-10-04"
  last_decision: "2020-07-09"
  first_term: 1993
  last_term: 2019
  terms: 27
  cases: 2300                  # votes recorded (participations)
  majority_share: 0.82         # share of votes in the majority
  dissents: 401
  opinions_written: 692
ideology:                      # computed from SCDB vote directions
  career_liberal_share: 0.68   # share of directional votes coded liberal
  by_term:                     # the "leanings over time" series (integer term keys)
    1993: {liberal_share: 0.62, n: 84}
    1994: {liberal_share: 0.64, n: 82}
  by_issue_area:
    civil-rights: {liberal_share: 0.81, n: 312}
  # reserved: martin_quinn (dynamic ideal points — see docs/sources.md)
```

Caveats worth internalizing before modeling: SCDB "direction" coding embeds the
Spaeth ideological coding scheme (e.g. pro-defendant = liberal in criminal procedure);
it is conventional in the literature but contested at the margins — see
docs/modeling.md § pitfalls.

`record.*` and `ideology.by_term` derive from SCDB's *term* coding, which keys a case
to its docket era. A handful of long-pending legacy cases were decided a decade after
their docket term (e.g. caseId `1895-077`, decided 1905), so a justice's `first_term`
can slightly predate actual service; `first_decision`/`last_decision` are always true
decision dates.

`data/justices/index.yaml` lists every justice: slug, name, SCDB mnemonic + id, first/last
term, and appointment metadata when curated.

## Natural courts — `data/courts/natural-courts.yaml`

A natural court is a period of stable membership. Computed from the data: SCDB
`naturalCourt` code, chief, first/last decision dates observed, and member mnemonics.

## Codebook — `data/codebook/`

One YAML per fully-decoded field: `{code, token, label}` triples as emitted from
`pipeline/codes.py`. Raw-code fields (issue, parties, courts, lawSupp) are documented
in `data/codebook/README.md` with pointers to the official SCDB codebook.
