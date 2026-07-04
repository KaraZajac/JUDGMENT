"""Build the YAML dataset under data/ from sources/ + pipeline/curated/.

Two streaming passes over the SCDB CSVs:
  1. justice-centered rows -> per-case vote lists, per-justice statistics,
     natural-court membership, justice id<->mnemonic maps
  2. case-centered rows    -> data/cases/<term>/<caseId>.yaml (votes embedded)

Then per-justice files (curated bios merged with computed records), the justice
index, natural courts, the codebook, and data/meta.yaml.

Everything under data/ is deleted and regenerated; see docs/data-model.md.
"""

import csv
import datetime
import io
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from . import codes

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"
DATA = ROOT / "data"
CURATED_JUSTICES = Path(__file__).resolve().parent / "curated" / "justices.yaml"

Dumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)

unmapped = Counter()   # "<column>:<code>" -> rows where codes.py lacked a mapping
coverage = Counter()   # emitted case field -> number of cases carrying it


class Flow(dict):
    """dict rendered in YAML flow style, e.g. {code: 300, area: civil-rights}."""


def _repr_flow(dumper, data):
    return dumper.represent_mapping("tag:yaml.org,2002:map", data, flow_style=True)


Dumper.add_representer(Flow, _repr_flow)


# ---------------------------------------------------------------- primitives

def read_rows(filename):
    data = (SOURCES / filename).read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return csv.DictReader(io.StringIO(text))


def clean(v):
    if v is None:
        return None
    v = v.strip()
    if v in ("", "NULL", "NA"):  # SCDB null literals (legacy "NULL", modern "NA")
        return None
    return v


def to_int(v):
    v = clean(v)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        try:
            return int(float(v))
        except ValueError:
            return None


def to_date(v):
    v = clean(v)
    if v is None:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def to_bool(v):
    i = to_int(v)
    return None if i is None else bool(i)


def put(d, key, value):
    """Set key unless the value is empty; False and 0 are kept."""
    if value is None or value == "" or value == [] or value == {}:
        return
    d[key] = value


def put_bool(d, key, value):
    if value is not None:
        d[key] = value


def decoded(column, table, code):
    """Complete-decode field: token, or the raw code (+ warning) if unmapped."""
    if code is None:
        return None
    t = codes.token(table, code)
    if t is None:
        unmapped[f"{column}:{code}"] += 1
        return code
    return t


def stringify_dates(obj):
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, dict):
        return {k: stringify_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [stringify_dates(v) for v in obj]
    return obj


def dump_yaml(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(obj, f, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=110)


# ---------------------------------------------------------------- pass 1: votes

def extract_vote(row):
    entry = {"justice": clean(row.get("justiceName"))
             or f"id-{to_int(row.get('justice'))}"}
    v = to_int(row.get("vote"))
    if v is None:
        entry["participated"] = False
        return entry, None
    entry["vote"] = decoded("vote", codes.VOTE, v)
    if to_int(row.get("opinion")) in (2, 3):
        entry["opinion"] = codes.token(codes.OPINION, to_int(row.get("opinion")))
    put(entry, "direction",
        codes.token(codes.VOTE_DIRECTION, to_int(row.get("direction"))))
    mj = to_int(row.get("majority"))
    if mj is not None:
        entry["in_majority"] = mj == 2
    joined = [j for j in (to_int(row.get("firstAgreement")),
                          to_int(row.get("secondAgreement"))) if j]
    return entry, joined or None


def new_stats(jid):
    return {"id": jid, "rows": 0, "maj": 0, "maj_n": 0, "dissents": 0,
            "opinions": 0, "lib": 0, "dir_n": 0, "terms": set(),
            "first": None, "last": None,
            "dir_term": defaultdict(lambda: [0, 0]),
            "dir_area": defaultdict(lambda: [0, 0]),
            "dir_area_term": defaultdict(lambda: [0, 0])}


def pass_votes(filenames):
    votes_by_case = defaultdict(list)
    pending_joins = []
    name_by_id = {}
    stats = {}
    courts = {}
    n = 0

    for fn in filenames:
        print(f"  reading {fn}")
        for row in read_rows(fn):
            cid = clean(row.get("caseId"))
            if not cid:
                continue
            # SCDB Legacy placeholder rows: justice coded -99, no vote data, for
            # 25 caseIds that the case-centered file deliberately omits.
            if to_int(row.get("justice")) == -99:
                continue
            n += 1
            entry, joined = extract_vote(row)
            votes_by_case[cid].append(entry)
            if joined:
                pending_joins.append((entry, joined))

            jname = entry["justice"]
            jid = to_int(row.get("justice"))
            if jid is not None:
                name_by_id[jid] = jname
            st = stats.get(jname)
            if st is None:
                st = stats[jname] = new_stats(jid)
            st["rows"] += 1
            term = to_int(row.get("term"))
            if term is not None:
                st["terms"].add(term)
            d = to_date(row.get("dateDecision"))
            if d:
                if st["first"] is None or d < st["first"]:
                    st["first"] = d
                if st["last"] is None or d > st["last"]:
                    st["last"] = d
            if to_int(row.get("vote")) == 2:
                st["dissents"] += 1
            if to_int(row.get("opinion")) in (2, 3):
                st["opinions"] += 1
            mj = to_int(row.get("majority"))
            if mj in (1, 2):
                st["maj_n"] += 1
                st["maj"] += mj == 2
            dr = to_int(row.get("direction"))
            if dr in (1, 2):
                lib = 1 if dr == 2 else 0
                st["lib"] += lib
                st["dir_n"] += 1
                if term is not None:
                    cell = st["dir_term"][term]
                    cell[0] += lib
                    cell[1] += 1
                area = codes.token(codes.ISSUE_AREA, to_int(row.get("issueArea")))
                if area:
                    cell = st["dir_area"][area]
                    cell[0] += lib
                    cell[1] += 1
                    if term is not None:
                        cell = st["dir_area_term"][(area, term)]
                        cell[0] += lib
                        cell[1] += 1

            nc = to_int(row.get("naturalCourt"))
            if nc is not None:
                c = courts.get(nc)
                if c is None:
                    c = courts[nc] = {"chief": None, "justices": set(),
                                      "first": None, "last": None}
                c["justices"].add(jname)
                ch = clean(row.get("chief"))
                if ch:
                    c["chief"] = ch
                if d:
                    if c["first"] is None or d < c["first"]:
                        c["first"] = d
                    if c["last"] is None or d > c["last"]:
                        c["last"] = d
            if n % 50000 == 0:
                print(f"  ... {n:,} vote rows")

    unresolved = 0
    for entry, ids in pending_joins:
        names = [name_by_id[i] for i in ids if i in name_by_id]
        unresolved += len(ids) - len(names)
        put(entry, "joined", names)

    print(f"  {n:,} vote rows, {len(votes_by_case):,} cases with votes, "
          f"{len(stats)} justices, {len(courts)} natural courts, "
          f"unresolved agreement ids: {unresolved}")
    return votes_by_case, stats, name_by_id, courts


# ---------------------------------------------------------------- pass 2: cases

def build_case(row, votes, name_by_id):
    case = {}
    put(case, "id", clean(row.get("caseId")))
    put(case, "name", clean(row.get("caseName")))
    put(case, "term", to_int(row.get("term")))
    put(case, "chief", clean(row.get("chief")))
    put(case, "natural_court", to_int(row.get("naturalCourt")))
    put(case, "docket", clean(row.get("docket")))

    cit = {}
    put(cit, "us", clean(row.get("usCite")))
    put(cit, "sct", clean(row.get("sctCite")))
    put(cit, "led", clean(row.get("ledCite")))
    put(cit, "lexis", clean(row.get("lexisCite")))
    put(case, "citation", cit)

    dates = {}
    put(dates, "argued", to_date(row.get("dateArgument")))
    put(dates, "reargued", to_date(row.get("dateRearg")))
    put(dates, "decided", to_date(row.get("dateDecision")))
    put(case, "dates", dates)

    dec = {}
    put(dec, "type",
        decoded("decisionType", codes.DECISION_TYPE, to_int(row.get("decisionType"))))
    put(dec, "disposition",
        decoded("caseDisposition", codes.CASE_DISPOSITION, to_int(row.get("caseDisposition"))))
    put(dec, "winning_party",
        decoded("partyWinning", codes.PARTY_WINNING, to_int(row.get("partyWinning"))))
    put(dec, "direction",
        decoded("decisionDirection", codes.DECISION_DIRECTION, to_int(row.get("decisionDirection"))))
    put_bool(dec, "precedent_altered", to_bool(row.get("precedentAlteration")))
    put(dec, "unconstitutional",
        decoded("declarationUncon", codes.DECLARATION_UNCON, to_int(row.get("declarationUncon"))))
    put(dec, "majority_votes", to_int(row.get("majVotes")))
    put(dec, "minority_votes", to_int(row.get("minVotes")))
    put(case, "decision", dec)

    iss = Flow()
    put(iss, "code", to_int(row.get("issue")))
    put(iss, "area", decoded("issueArea", codes.ISSUE_AREA, to_int(row.get("issueArea"))))
    put(case, "issue", iss)

    law = {}
    put(law, "type", decoded("lawType", codes.LAW_TYPE, to_int(row.get("lawType"))))
    put(law, "supp", to_int(row.get("lawSupp")))
    put(law, "minor", clean(row.get("lawMinor")))
    put(case, "law", law)

    auth = [decoded("authorityDecision", codes.AUTHORITY, to_int(row.get(c)))
            for c in ("authorityDecision1", "authorityDecision2")]
    put(case, "authority", [a for a in auth if a is not None])

    jur = to_int(row.get("jurisdiction"))
    if jur is not None:
        jd = Flow({"code": jur})
        put(jd, "label", codes.token(codes.JURISDICTION_PARTIAL, jur))
        case["jurisdiction"] = jd

    put(case, "cert_reason",
        decoded("certReason", codes.CERT_REASON, to_int(row.get("certReason"))))

    lc = {}
    for key, col in (("origin", "caseOrigin"), ("source", "caseSource")):
        code = to_int(row.get(col))
        if code is not None:
            d = Flow({"code": code})
            put(d, "state", to_int(row.get(col + "State")))
            lc[key] = d
    put(lc, "disposition",
        decoded("lcDisposition", codes.LC_DISPOSITION, to_int(row.get("lcDisposition"))))
    put(lc, "direction",
        decoded("lcDispositionDirection", codes.DECISION_DIRECTION,
                to_int(row.get("lcDispositionDirection"))))
    put_bool(lc, "disagreement", to_bool(row.get("lcDisagreement")))
    put(case, "lower_court", lc)

    parties = {}
    for col in ("petitioner", "respondent"):
        code = to_int(row.get(col))
        if code is not None:
            parties[col] = Flow({"code": code})
        state = to_int(row.get(col + "State"))
        if state is not None:
            parties[col + "_state"] = Flow({"code": state})
    put(case, "parties", parties)

    aa = Flow()
    put(aa, "agency", to_int(row.get("adminAction")))
    put(aa, "state", to_int(row.get("adminActionState")))
    put(case, "admin_action", aa)

    flags = {}
    for key, col in (("three_judge_district_court", "threeJudgeFdc"),
                     ("vote_unclear", "voteUnclear"),
                     ("disposition_unusual", "caseDispositionUnusual")):
        if to_bool(row.get(col)):
            flags[key] = True
    if to_int(row.get("splitVote")) == 2:
        flags["second_vote"] = True
    put(case, "flags", flags)

    ops = {}
    for key, col in (("majority_author", "majOpinWriter"),
                     ("majority_assigner", "majOpinAssigner")):
        wid = to_int(row.get(col))
        if wid is not None:
            if wid not in name_by_id:
                unmapped[f"{col}:{wid}"] += 1
            ops[key] = name_by_id.get(wid, wid)
    put(case, "opinions", ops)

    put(case, "votes", votes)
    for k in case:
        coverage[k] += 1
    return case


def write_cases(case_files, votes_by_case, name_by_id):
    out = DATA / "cases"
    counts = Counter()
    n = 0
    for era, fn in case_files:
        print(f"  reading {fn}")
        for row in read_rows(fn):
            cid = clean(row.get("caseId"))
            if not cid:
                continue
            votes = votes_by_case.pop(cid, None)
            case = build_case(row, votes, name_by_id)
            term = case.get("term") or to_int(cid[:4])
            tdir = out / str(term)
            tdir.mkdir(parents=True, exist_ok=True)
            path = tdir / f"{cid}.yaml"
            if path.exists():
                unmapped[f"duplicate-caseId:{cid}"] += 1
            dump_yaml(case, path)
            counts[era] += 1
            n += 1
            if n % 5000 == 0:
                print(f"  ... {n:,} case files")
    return counts


# ---------------------------------------------------------------- justices

SERVICE_KEYS = ("position", "appointed_by", "party", "oath", "ended",
                "end_reason", "confirmation_vote", "elevated")
BIO_KEYS = ("born", "died", "law_school", "prior")


def mechanical(jname):
    """Derive (slug, display name) from an SCDB mnemonic like 'HBLivingston'."""
    m = re.match(r"^([A-Z]+)([A-Z][A-Za-z']+?)(\d*)$", jname)
    if not m:
        return jname.lower(), jname
    initials, surname, sfx = m.groups()
    name = " ".join(f"{c}." for c in initials) + f" {surname}"
    slug = re.sub(r"[^a-z0-9]+", "-", f"{initials.lower()}-{surname.lower()}")
    if sfx:
        roman = {"1": "i", "2": "ii", "3": "iii"}.get(sfx, sfx)
        name += f" {roman.upper()}"
        slug += f"-{roman}"
    return slug, name


def build_justices(stats, curated):
    out = DATA / "justices"
    out.mkdir(parents=True)
    index = []
    seen_slugs = set()

    unmatched = set(curated) - set(stats)
    if unmatched:
        print(f"  WARNING: curated justices not found in SCDB data: {sorted(unmatched)}")

    def sort_key(item):
        st = item[1]
        return (st["id"] if st["id"] is not None else 10 ** 6, item[0])

    for jname, st in sorted(stats.items(), key=sort_key):
        cur = curated.get(jname) or {}
        slug = cur.get("slug") or mechanical(jname)[0]
        name = cur.get("name") or mechanical(jname)[1]
        if slug in seen_slugs:
            slug = f"{slug}-{st['id']}"
        seen_slugs.add(slug)

        j = {"slug": slug, "name": name,
             "scdb": Flow({"name": jname, "id": st["id"]})}
        put(j, "service", {k: cur[k] for k in SERVICE_KEYS if k in cur})
        put(j, "bio", {k: cur[k] for k in BIO_KEYS if k in cur})

        record = {}
        put(record, "first_decision", st["first"])
        put(record, "last_decision", st["last"])
        terms = sorted(st["terms"])
        if terms:
            record["first_term"] = terms[0]
            record["last_term"] = terms[-1]
            record["terms"] = len(terms)
        record["cases"] = st["rows"]
        if st["maj_n"]:
            record["majority_share"] = round(st["maj"] / st["maj_n"], 3)
        record["dissents"] = st["dissents"]
        record["opinions_written"] = st["opinions"]
        j["record"] = record

        ideology = {}
        if st["dir_n"]:
            ideology["career_liberal_share"] = round(st["lib"] / st["dir_n"], 3)
            ideology["by_term"] = {
                t: Flow({"liberal_share": round(lib / n, 3), "n": n})
                for t, (lib, n) in sorted(st["dir_term"].items()) if n}
            ideology["by_issue_area"] = {
                a: Flow({"liberal_share": round(lib / n, 3), "n": n})
                for a, (lib, n) in sorted(st["dir_area"].items()) if n}
            by_area_term = {}
            for (a, t), (lib, n) in sorted(st["dir_area_term"].items()):
                if n:
                    by_area_term.setdefault(a, {})[t] = Flow(
                        {"liberal_share": round(lib / n, 3), "n": n})
            put(ideology, "by_issue_area_term", by_area_term)
        put(j, "ideology", ideology)

        dump_yaml(j, out / f"{slug}.yaml")

        idx = {"slug": slug, "name": name, "scdb_name": jname, "scdb_id": st["id"]}
        if terms:
            idx["first_term"] = terms[0]
            idx["last_term"] = terms[-1]
        for k in ("position", "appointed_by", "party"):
            if k in cur:
                idx[k] = cur[k]
        index.append(idx)

    dump_yaml(index, out / "index.yaml")
    print(f"  {len(index)} justices ({sum(1 for j in index if 'appointed_by' in j)} curated)")


def write_courts(courts, stats):
    out = DATA / "courts"
    out.mkdir(parents=True)

    def jkey(jname):
        jid = stats[jname]["id"]
        return jid if jid is not None else 10 ** 6

    rows = []
    for code in sorted(courts):
        c = courts[code]
        rows.append({"code": code, "chief": c["chief"],
                     "first_decision": c["first"], "last_decision": c["last"],
                     "justices": sorted(c["justices"], key=jkey)})
    dump_yaml(rows, out / "natural-courts.yaml")


# ---------------------------------------------------------------- codebook, meta

CODEBOOK_README = """\
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
"""


def write_codebook():
    out = DATA / "codebook"
    out.mkdir(parents=True)
    for name, table in codes.CODEBOOK_EXPORTS.items():
        entries = [{"code": c, "token": t, "label": l}
                   for c, (t, l) in sorted(table.items())]
        dump_yaml(entries, out / f"{name}.yaml")
    (out / "README.md").write_text(CODEBOOK_README, encoding="utf-8")


def write_meta(manifest, counts, stats, courts):
    all_terms = sorted(t for st in stats.values() for t in st["terms"])
    meta = {
        "generated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "python3 -m pipeline.build",
        "scdb": {
            "modern_release": manifest.get("modern_release"),
            "legacy_release": manifest.get("legacy_release"),
            "downloaded": manifest.get("downloaded"),
        },
        "counts": {
            "cases": counts["modern"] + counts["legacy"],
            "cases_modern": counts["modern"],
            "cases_legacy": counts["legacy"],
            "vote_records": sum(st["rows"] for st in stats.values()),
            "justices": len(stats),
            "natural_courts": len(courts),
            "first_term": all_terms[0] if all_terms else None,
            "last_term": all_terms[-1] if all_terms else None,
        },
    }
    dump_yaml(meta, DATA / "meta.yaml")


# ---------------------------------------------------------------- main

def main():
    man_path = SOURCES / "manifest.yaml"
    if not man_path.exists():
        raise SystemExit("sources/manifest.yaml missing — run "
                         "`python3 -m pipeline.download` first")
    manifest = yaml.safe_load(man_path.read_text())
    files = manifest["files"]

    curated = {}
    fjc_path = CURATED_JUSTICES.parent / "justices-fjc.yaml"
    if fjc_path.exists():  # FJC fallback first; hand-curated entries override
        curated.update(stringify_dates(yaml.safe_load(fjc_path.read_text()) or {}))
    if CURATED_JUSTICES.exists():
        curated.update(stringify_dates(yaml.safe_load(CURATED_JUSTICES.read_text()) or {}))

    print("pass 1/2: justice-centered vote rows")
    votes_by_case, stats, name_by_id, courts = pass_votes(
        [files["modern_justice"], files["legacy_justice"]])

    for sub in ("cases", "justices", "codebook", "courts"):
        shutil.rmtree(DATA / sub, ignore_errors=True)
    DATA.mkdir(exist_ok=True)

    print("pass 2/2: case-centered records -> data/cases/")
    counts = write_cases(
        [("modern", files["modern_case"]), ("legacy", files["legacy_case"])],
        votes_by_case, name_by_id)
    print(f"  {counts['modern']:,} modern + {counts['legacy']:,} legacy case files; "
          f"orphan vote groups (votes without a case record): {len(votes_by_case)}")

    print("justices, courts, codebook, meta")
    build_justices(stats, curated)
    write_courts(courts, stats)
    write_codebook()
    write_meta(manifest, counts, stats, courts)

    if unmapped:
        print("unmapped codes (raw value kept in YAML):")
        for k, n in unmapped.most_common(20):
            print(f"  {k}: {n:,}")
    total = counts["modern"] + counts["legacy"]
    print("case field coverage:")
    for k, n in coverage.most_common():
        print(f"  {k:>14}: {n:,} ({n / total:.0%})")
    print("done.")


if __name__ == "__main__":
    main()
