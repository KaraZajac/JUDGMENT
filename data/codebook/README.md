# Codebook

`{code, token, label}` tables for every fully-decoded SCDB field (the YAML files in
`data/` store the `token`). Emitted from `pipeline/codes.py` — edit there, rebuild.

Fields kept as **raw numeric codes** in the dataset, decodable via the official SCDB
online codebook (http://scdb.wustl.edu/documentation.php):

- `issue.code` (~280 issue codes)
- `parties.*.code` and `*_state.code` (party typology and state codes)
- `lower_court.origin.code` / `lower_court.source.code` (court codes)
- `admin_action.agency` (agency codes)
- `law.supp` (specific legal provision)
- `jurisdiction.code` values without a `label` (uncommon jurisdiction types)
- `natural_court` (SCDB naturalCourt id; see ../courts/natural-courts.yaml)

SCDB columns intentionally not carried into the YAML: `docketId`, `caseIssuesId`,
`voteId` (derivable from `caseId`), and `decisionDirectionDissent` (rarely used;
consult SCDB directly if needed).
