"""Provisional current-term ingest: Oyez + CourtListener -> data/cases/<term>/.

SCDB is released annually (~October), so the term that just ended is invisible to
the canonical dataset for months. This module fills the gap with *provisional*
case records carrying only source-verifiable facts:

- spine: Oyez (api.oyez.org) — decided merits cases with per-justice votes,
  opinion authorship, joins, party names, vote counts, and timeline dates
- supplement: CourtListener search (free tier) — decided SCOTUS opinions Oyez
  does not list (e.g. signed emergency-docket opinions), as thin records, plus
  citations for matched cases

Provisional records are marked `provisional: true`, use docket-derived ids
(`2025-d24-539`) rather than SCDB caseIds, and carry NO SCDB coding (no issue,
direction, disposition, or formal vote typology beyond majority/dissent).
They exist to be replaced: once an SCDB release covers the term, this module
skips it and `pipeline.build` regenerates the term canonically.

`pipeline.build` deletes all of data/cases/, so re-run this after every build:

    python3 -m pipeline.download && python3 -m pipeline.build
    python3 -m pipeline.interim      # provisional gap terms (cached; --refresh to refetch)
    python3 -m pipeline.aggregates   # term rollups, incl. provisional terms

Set COURTLISTENER_TOKEN for authenticated CL rates (optional).
"""

import datetime
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

import yaml

from .build import DATA, SOURCES, dump_yaml, put

CACHE = SOURCES / "interim"
UA = "JUDGEMENT-pipeline/0.1 (academic research)"
ET = ZoneInfo("America/New_York")

# Oyez member identifier -> SCDB justiceName mnemonic. Extend when the bench changes;
# unknown identifiers pass through raw and are reported.
OYEZ_MNEMONIC = {
    "john_g_roberts_jr": "JGRoberts",
    "clarence_thomas": "CThomas",
    "samuel_a_alito_jr": "SAAlito",
    "sonia_sotomayor": "SSotomayor",
    "elena_kagan": "EKagan",
    "neil_gorsuch": "NMGorsuch",
    "brett_m_kavanaugh": "BMKavanaugh",
    "amy_coney_barrett": "ACBarrett",
    "ketanji_brown_jackson": "KBJackson",
}

unknown_members = set()


# ---------------------------------------------------------------- fetching

def fetch_json(url, cache_name, refresh=False, headers=None):
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / cache_name
    if cached.exists() and not refresh:
        return json.loads(cached.read_text(encoding="utf-8"))
    req_headers = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.load(resp)
    cached.write_text(json.dumps(payload), encoding="utf-8")
    time.sleep(0.2)  # be polite to free APIs
    return payload


def oyez_term_stubs(term, refresh):
    listing = fetch_json(
        f"https://api.oyez.org/cases?filter=term:{term}&per_page=300",
        f"oyez-term-{term}.json", refresh)
    return [s for s in listing
            if (s.get("docket_number") or "").strip() and s.get("href")]


def _is_decided(stub):
    return any(t and t.get("event") == "Decided" for t in (stub.get("timeline") or []))


def oyez_detail(term, stub, refresh):
    docket = stub["docket_number"].strip()
    return fetch_json(stub["href"], f"oyez-case-{term}-{docket_slug(docket)}.json",
                      refresh)


def oyez_decided_cases(term, refresh):
    """Oyez term list filtered to cases with a Decided event, with full details."""
    return [oyez_detail(term, s, refresh)
            for s in oyez_term_stubs(term, refresh) if _is_decided(s)]


def cl_search(term, refresh):
    """CourtListener v4 search: published SCOTUS opinion clusters in the term window."""
    start, end = f"{term}-10-01", f"{term + 1}-09-30"
    params = urllib.parse.urlencode({
        "type": "o", "court": "scotus", "order_by": "dateFiled desc",
        "filed_after": start, "filed_before": end,
    })
    url = f"https://www.courtlistener.com/api/rest/v4/search/?{params}"
    headers = {}
    token = os.environ.get("COURTLISTENER_TOKEN")
    if token:
        headers["Authorization"] = f"Token {token}"
    results, page = [], 0
    while url and page < 12:
        try:
            payload = fetch_json(url, f"cl-search-{term}-p{page}.json", refresh, headers)
        except (HTTPError, URLError) as e:
            print(f"  CL search stopped at page {page}: {e}")
            break
        results.extend(payload.get("results") or [])
        url = payload.get("next")
        page += 1
    # client-side window filter (belt and suspenders) + dedupe by docket,
    # preferring the shortest case name (revision clusters carry suffixed names)
    by_docket = {}
    for r in results:
        d = (r.get("docketNumber") or "").strip()
        filed = r.get("dateFiled") or ""
        if not d or not (start <= filed <= end):
            continue
        prev = by_docket.get(d)
        if prev is None or len(r.get("caseName") or "") < len(prev.get("caseName") or ""):
            by_docket[d] = r
    return by_docket


# ---------------------------------------------------------------- mapping

def docket_slug(docket):
    return re.sub(r"[^a-z0-9]+", "-", docket.lower()).strip("-")


def case_id(term, docket):
    return f"{term}-d{docket_slug(docket)}"


def ts_to_date(ts):
    if not ts:
        return None
    return datetime.datetime.fromtimestamp(int(ts), tz=ET).date().isoformat()


def timeline_dates(detail):
    dates = {}
    for entry in detail.get("timeline") or []:
        if not entry:
            continue
        event = (entry.get("event") or "").lower()
        ts = (entry.get("dates") or [None])[0]
        iso = ts_to_date(ts)
        if not iso:
            continue
        if event == "granted":
            dates.setdefault("granted", iso)
        elif event == "argued":
            dates.setdefault("argued", iso)
        elif event == "reargued":
            dates.setdefault("reargued", iso)
        elif event == "decided":
            dates["decided"] = iso
    return dates


def mnemonic_for(member):
    ident = (member or {}).get("identifier") or ""
    if ident in OYEZ_MNEMONIC:
        return OYEZ_MNEMONIC[ident]
    name = (member or {}).get("name") or ident or "unknown"
    unknown_members.add(name)
    return name


def map_votes(decision):
    """Oyez decision.votes -> (votes list, majority_author).

    Coarse by design: majority/dissent only, plus authorship and joins.
    Oyez concurrences are split regular/special by whether the justice also
    joined the majority author's opinion (SCDB's own definition)."""
    votes_raw = decision.get("votes") or []
    majority_author = None
    for v in votes_raw:
        if (v.get("opinion_type") or "") in ("majority", "plurality"):
            majority_author = mnemonic_for(v.get("member"))
            break
    votes = []
    for v in votes_raw:
        side = (v.get("vote") or "").lower()
        entry = {"justice": mnemonic_for(v.get("member"))}
        opinion_type = (v.get("opinion_type") or "none").lower()
        joined = [mnemonic_for(m) for m in (v.get("joining") or []) if m]
        if side == "majority":
            if opinion_type == "concurrence":
                entry["vote"] = ("regular-concurrence"
                                 if majority_author and majority_author in joined
                                 else "special-concurrence")
            else:
                entry["vote"] = "majority"
            entry["in_majority"] = True
        elif side == "minority":
            entry["vote"] = "dissent"
            entry["in_majority"] = False
        else:
            entry["participated"] = False
            votes.append(entry)
            continue
        if opinion_type != "none":
            entry["opinion"] = "wrote"
        put(entry, "joined", joined)
        votes.append(entry)
    return votes, majority_author


def oyez_citation(detail):
    cit = detail.get("citation") or {}
    vol, page = cit.get("volume"), cit.get("page")
    if vol and page:
        return f"{vol} U.S. {page}"
    return None


def cl_citations(cl_row):
    """CourtListener search `citation` is a list of cite strings."""
    out = {}
    for c in cl_row.get("citation") or []:
        if not isinstance(c, str):
            continue
        if " U.S. " in c and "us" not in out:
            out["us"] = c
        elif " S. Ct. " in c and "sct" not in out:
            out["sct"] = c
        elif " L. Ed. " in c and "led" not in out:
            out["led"] = c
    if cl_row.get("lexisCite"):
        out.setdefault("lexis", cl_row["lexisCite"])
    return out


def party_fields(detail):
    """first/second party + labels -> petitioner/respondent names where labels say so."""
    first, second = detail.get("first_party"), detail.get("second_party")
    fl = (detail.get("first_party_label") or "").lower()
    sl = (detail.get("second_party_label") or "").lower()
    parties = {}
    pet_words = ("petitioner", "appellant", "plaintiff")
    if any(w in fl for w in pet_words) or "respondent" in sl or "appellee" in sl:
        put(parties, "petitioner_name", first)
        put(parties, "respondent_name", second)
    elif any(w in sl for w in pet_words) or "respondent" in fl:
        put(parties, "petitioner_name", second)
        put(parties, "respondent_name", first)
    else:
        put(parties, "first_party", first)
        put(parties, "second_party", second)
    return parties


def winning_token(decision, parties):
    winner = (decision.get("winning_party") or "").strip()
    if not winner:
        return None, None
    w = winner.casefold()
    pet = (parties.get("petitioner_name") or "").casefold()
    res = (parties.get("respondent_name") or "").casefold()
    if pet and (w in pet or pet in w):
        return "petitioner", None
    if res and (w in res or res in w):
        return "respondent", None
    return None, winner


DECISION_TYPE_MAP = {
    "majority opinion": "opinion-of-the-court",
    "plurality opinion": "judgment-of-the-court",
    "equally divided": "equally-divided",
}


def build_from_oyez(term, detail, cl_by_docket):
    docket = (detail.get("docket_number") or "").strip()
    cid = case_id(term, docket)
    dates = timeline_dates(detail)
    decision = (detail.get("decisions") or [{}])[0] or {}
    votes, majority_author = map_votes(decision)
    parties = party_fields(detail)
    win_token, win_name = winning_token(decision, parties)

    cl_row = cl_by_docket.pop(docket, None)
    sources = ["oyez"] + (["courtlistener"] if cl_row else [])

    case = {
        "id": cid,
        "name": detail.get("name"),
        "term": term,
        "provisional": True,
        "sources": sources,
    }
    put(case, "docket", docket)

    citation = cl_citations(cl_row) if cl_row else {}
    citation.setdefault("us", oyez_citation(detail))
    put(case, "citation", {k: v for k, v in citation.items() if v})
    put(case, "dates", dates)

    dec = {}
    dtype = (decision.get("decision_type") or "").lower()
    if dtype == "per curiam":
        dec["type"] = "per-curiam-argued" if dates.get("argued") else "per-curiam-no-argument"
    else:
        put(dec, "type", DECISION_TYPE_MAP.get(dtype))
    put(dec, "winning_party", win_token)
    put(dec, "winning_party_name", win_name)
    maj, mnr = decision.get("majority_vote"), decision.get("minority_vote")
    if isinstance(maj, int) and isinstance(mnr, int) and (maj or mnr):
        dec["majority_votes"] = maj
        dec["minority_votes"] = mnr
    put(case, "decision", dec)

    lower = detail.get("lower_court") or {}
    if isinstance(lower, dict) and lower.get("name"):
        case["lower_court"] = {"name": lower["name"]}
    put(case, "parties", parties)
    put(case, "question", strip_html(detail.get("question")))
    href = detail.get("href") or ""
    put(case, "oyez_url", href.replace("api.oyez.org", "www.oyez.org") or None)
    if majority_author:
        case["opinions"] = {"majority_author": majority_author}
    put(case, "votes", votes)
    return case


def strip_html(s):
    if not s:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"\s+", " ", text).strip() or None


def build_pending(term, detail):
    """Granted/argued-but-undecided case -> data/docket/ record (a forecasting target)."""
    docket = (detail.get("docket_number") or "").strip()
    case = {
        "id": case_id(term, docket),
        "name": detail.get("name"),
        "term": term,
        "pending": True,
        "sources": ["oyez"],
    }
    put(case, "docket", docket)
    put(case, "dates", timeline_dates(detail))
    lower = detail.get("lower_court") or {}
    if isinstance(lower, dict) and lower.get("name"):
        case["lower_court"] = {"name": lower["name"]}
    put(case, "parties", party_fields(detail))
    put(case, "question", strip_html(detail.get("question")))
    href = detail.get("href") or ""
    put(case, "oyez_url", href.replace("api.oyez.org", "www.oyez.org") or None)
    return case


def build_from_cl(term, row, oyez=None):
    """Thin decided record from CourtListener search, enriched with Oyez case
    metadata (question, parties, grant date) when Oyez lists the case but has
    not yet coded the decision."""
    docket = (row.get("docketNumber") or "").strip()
    case = {
        "id": case_id(term, docket),
        "name": row.get("caseName"),
        "term": term,
        "provisional": True,
        "sources": ["courtlistener"] + (["oyez"] if oyez else []),
    }
    put(case, "docket", docket)
    put(case, "citation", cl_citations(row))
    dates = {}
    if oyez:
        put(dates, "granted", timeline_dates(oyez).get("granted"))
    put(dates, "argued", row.get("dateArgued"))
    put(dates, "reargued", row.get("dateReargued"))
    put(dates, "decided", row.get("dateFiled"))
    put(case, "dates", dates)
    if oyez:
        lower = oyez.get("lower_court") or {}
        if isinstance(lower, dict) and lower.get("name"):
            case["lower_court"] = {"name": lower["name"]}
        put(case, "parties", party_fields(oyez))
        put(case, "question", strip_html(oyez.get("question")))
        href = oyez.get("href") or ""
        put(case, "oyez_url", href.replace("api.oyez.org", "www.oyez.org") or None)
    return case


# ---------------------------------------------------------------- main

def target_terms():
    meta_path = DATA / "meta.yaml"
    if not meta_path.exists():
        raise SystemExit("data/meta.yaml missing — run `python3 -m pipeline.build` first")
    last_scdb = yaml.safe_load(meta_path.read_text())["counts"]["last_term"]
    today = datetime.date.today()
    current_ot = today.year if today.month >= 10 else today.year - 1
    return list(range(last_scdb + 1, current_ot + 1))


def ingest_decided(term, refresh):
    print(f"term {term}: fetching Oyez + CourtListener (cache: sources/interim/)")
    stubs = oyez_term_stubs(term, refresh)
    oyez_cases = [oyez_detail(term, s, refresh) for s in stubs if _is_decided(s)]
    # Oyez records not yet marked decided still enrich CL-only records
    oyez_undecided = {docket_slug(s["docket_number"].strip()): s
                      for s in stubs if not _is_decided(s)}
    cl_by_docket = cl_search(term, refresh)
    print(f"  {len(oyez_cases)} decided Oyez cases, "
          f"{len(cl_by_docket)} CL clusters in window")

    tdir = DATA / "cases" / str(term)
    tdir.mkdir(parents=True, exist_ok=True)
    written = skipped = 0

    records = [build_from_oyez(term, d, cl_by_docket) for d in oyez_cases]
    for row in cl_by_docket.values():
        stub = oyez_undecided.get(docket_slug((row.get("docketNumber") or "").strip()))
        oyez = oyez_detail(term, stub, refresh) if stub else None
        records.append(build_from_cl(term, row, oyez))

    for case in records:
        if not case.get("docket"):
            continue
        path = tdir / f"{case['id']}.yaml"
        if path.exists():
            existing = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not existing.get("provisional"):
                skipped += 1  # canonical SCDB record wins, always
                continue
        dump_yaml(case, path)
        written += 1

    with_votes = sum(1 for r in records if r.get("votes"))
    print(f"  wrote {written} provisional case files "
          f"({with_votes} with per-justice votes); skipped {skipped} canonical")


def ingest_pending(term, refresh):
    """Granted/argued cases awaiting decision -> data/docket/<term>/ (wiped each run,
    so cases that get decided migrate to data/cases/ automatically)."""
    stubs = [s for s in oyez_term_stubs(term, refresh) if not _is_decided(s)]
    tdir = DATA / "docket" / str(term)
    shutil.rmtree(tdir, ignore_errors=True)
    if not stubs:
        print(f"term {term}: no pending cases on the Oyez docket")
        return
    tdir.mkdir(parents=True, exist_ok=True)
    written = argued = already_decided = 0
    for stub in stubs:
        case = build_pending(term, oyez_detail(term, stub, refresh))
        if not case.get("docket"):
            continue
        # Oyez timelines lag decision days; if a decided record for this docket
        # already exists (e.g. from CourtListener), the decision wins.
        if (DATA / "cases" / str(term) / f"{case['id']}.yaml").exists():
            already_decided += 1
            continue
        dump_yaml(case, tdir / f"{case['id']}.yaml")
        written += 1
        if case.get("dates", {}).get("argued"):
            argued += 1
    if written == 0:
        shutil.rmtree(tdir, ignore_errors=True)
    print(f"term {term}: {written} pending docket cases "
          f"({argued} argued, awaiting decision; {already_decided} already decided "
          f"per CourtListener) -> data/docket/{term}/")


def main():
    refresh = "--refresh" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    decided_terms = [int(a) for a in args] if args else target_terms()

    for term in decided_terms:
        ingest_decided(term, refresh)

    # pending docket: the current OT plus grants already stacked for the next one
    today = datetime.date.today()
    current_ot = today.year if today.month >= 10 else today.year - 1
    for term in (current_ot, current_ot + 1):
        # skip a duplicate refetch when the decided pass just refreshed this term
        ingest_pending(term, refresh and term not in decided_terms)

    if not decided_terms:
        print("note: SCDB already covers all completed terms; only the docket was refreshed.")

    if unknown_members:
        print(f"  WARNING: unmapped Oyez members kept as raw names: {sorted(unknown_members)}")
        print("  -> add them to OYEZ_MNEMONIC in pipeline/interim.py")


if __name__ == "__main__":
    main()
