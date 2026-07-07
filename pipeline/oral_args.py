"""Oral-argument transcripts -> per-justice questioning features.

Source: Oyez case media (api.oyez.org) — structured per-speaker transcripts
with advocate sections, back to the 1955 term. supremecourt.gov argument-
transcript PDFs (1968+) are the documented fallback for cases Oyez lacks or
lags; deliberately not implemented — PDF speaker attribution is strictly
worse than Oyez's JSON, and the daily pipeline can wait days for Oyez.

Per argued case: match the Oyez docket to our case id; attribute each
transcript section to the petitioner or respondent side via the arguing
advocate's description ("for the petitioner", amicus "supporting the
respondent", ...); count each justice's turns and words while each side
holds the floor. The side differential is the literature's signal — the
side that draws more questioning tends to lose (Johnson et al.; Black et
al.; Kaufman, Kraft & Sen 2019's entire above-baseline margin came from
these transcripts) — and per-justice counts feed our per-vote model.

Output: data/oral/<term>.yaml — compact per-case per-justice counts
(tp/wp = turns/words while the petitioner side argues; tr/wr respondent).
Raw transcript JSON is gzip-cached under sources/oral-args/ (gitignored);
term files are skipped once written, so runs resume at term granularity
and cached fetches cost nothing.

  python3 -m pipeline.oral_args --terms 2019 2024      # harvest a range
  python3 -m pipeline.oral_args --pilot 2024           # one term, verbose
  python3 -m pipeline.oral_args --terms 1955 2024 --budget 20000
"""

import argparse
import gzip
import json
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError

import yaml

from .build import DATA, SOURCES, dump_yaml
from .interim import OYEZ_MNEMONIC, docket_slug

CACHE = SOURCES / "oral-args"
UA = "JUDGMENT-pipeline/0.1 (academic research)"
ORAL = DATA / "oral"

PET_WORDS = ("petitioner", "appellant", "plaintiff", "applicant", "movant")
RESP_WORDS = ("respondent", "appellee", "defendant")


class BudgetExhausted(Exception):
    pass


_spent = 0
_spend_lock = threading.Lock()


def fetch_json(url, cache_name, budget, fresh=False):
    """Cached (gzipped) GET; uncached fetches count against the budget.
    fresh=True bypasses the read side of the cache (still writes it) — for
    volatile resources like the current term's listing and case details,
    which grow new entries as cases are argued. Transcript media is
    immutable once posted and never needs it. Thread-safe: workers each
    sleep per request, so aggregate politeness scales with --workers
    (4 workers ~ 3 req/s against Oyez's static CDN)."""
    global _spent
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{cache_name}.json.gz"
    if path.exists() and not fresh:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    with _spend_lock:
        if _spent >= budget:
            raise BudgetExhausted()
        _spent += 1
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.load(resp)
    except (HTTPError, URLError, TimeoutError, ValueError) as e:
        time.sleep(0.5)
        print(f"    fetch failed ({type(e).__name__}): {url[:90]}")
        return None
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f)
    time.sleep(0.5)
    return payload


# ---------------------------------------------------------------- justices

def _name_key(name):
    """'John G. Roberts, Jr.' -> ('roberts', 'john'); robust to middles/suffixes."""
    clean = re.sub(r"[.,]", " ", name or "").lower()
    toks = [t for t in clean.split()
            if t not in ("jr", "sr", "ii", "iii", "iv") and len(t) > 1]
    if len(toks) < 2:
        return None
    return (toks[-1], toks[0])


def justice_matcher():
    """(last, first) -> [(first_term, last_term, scdb_name)]; term-filtered at
    lookup so the two John Marshall Harlans cannot collide."""
    index = yaml.safe_load((DATA / "justices" / "index.yaml").read_text(
        encoding="utf-8"))
    table = {}
    for j in index:
        key = _name_key(j["name"])
        if key:
            table.setdefault(key, []).append(
                (j["first_term"], j["last_term"] or 9999, j["scdb_name"]))
    ident_map = dict(OYEZ_MNEMONIC)  # identifier fast path (sitting bench)

    def match(speaker, term):
        ident = (speaker or {}).get("identifier") or ""
        if ident in ident_map:
            return ident_map[ident]
        key = _name_key((speaker or {}).get("name"))
        hits = [m for (a, b, m) in table.get(key, []) if a - 1 <= term <= b + 1]
        return hits[0] if len(hits) == 1 else None

    return match


# ---------------------------------------------------------------- sides

def side_of_description(desc):
    """Advocate description -> 'pet' | 'resp' | None.

    Amici follow the side they support ("supporting the Petitioner");
    court-appointed amici follow what they defend ("in support of the
    judgment below" = respondent side, "vacatur" = petitioner side);
    "supporting neither party" stays None. Emergency-docket "applicants"
    and original-jurisdiction "plaintiffs" count as the petitioner side."""
    d = (desc or "").lower()
    if not d:
        return None

    def word_side(w):
        if any(w.startswith(p) for p in PET_WORDS):
            return "pet"
        if any(w.startswith(p) for p in RESP_WORDS):
            return "resp"
        return None

    m = re.search(r"support(?:ing)?\s+(?:of\s+)?(?:the\s+)?(\w+)", d)
    if m and word_side(m.group(1)):
        return word_side(m.group(1))
    if "judgment below" in d or "decision below" in d or "affirmance" in d:
        return "resp"
    if "vacatur" in d or "reversal" in d:
        return "pet"
    if "amicus" in d or "amici" in d:
        return None  # unresolvable support clause (e.g. "neither party")
    for w in re.findall(r"\w+", d):
        if word_side(w):
            return word_side(w)
    return None


def advocate_sides(detail):
    """identifier -> side, from the case detail's advocates block."""
    sides = {}
    for row in detail.get("advocates") or []:
        adv = (row or {}).get("advocate") or {}
        ident = adv.get("identifier")
        if ident:
            sides[ident] = side_of_description(row.get("advocate_description"))
    return sides


def sg_amicus_side(detail):
    """'pet' | 'resp' | None: which side the United States supports as amicus
    at oral argument (the Solicitor General's office; e.g. 'for the United
    States, as amicus curiae, supporting the Petitioner'). The SG-supported
    side wins disproportionately — a classic predictor. State amici do not
    match (requires 'united states'); the US as a PARTY does not match
    (requires an amicus clause). Not cert-stage-knowable: merits amicus
    participation lands months after grant, so this feeds the post-argument
    stage, whose harvest is also its data source."""
    for row in detail.get("advocates") or []:
        d = (row or {}).get("advocate_description") or ""
        low = d.lower()
        if "united states" in low and ("amicus" in low or "amici" in low):
            side = side_of_description(d)
            if side:
                return side
    return None


def _turn_words(turn):
    return sum(len((tb.get("text") or "").split())
               for tb in (turn.get("text_blocks") or []))


def dominant_speaker(section, match, term):
    """The non-justice speaker holding the floor (most words) in a section."""
    words = {}
    for turn in section.get("turns") or []:
        sp = turn.get("speaker") or {}
        key = sp.get("identifier") or sp.get("name")
        if not key or match(sp, term):
            continue  # justices and unidentified speakers don't hold the floor
        words[key] = words.get(key, 0) + _turn_words(turn)
    return max(words, key=words.get) if words else None


def order_heuristic_sides(dominants):
    """Sides for one argument session with no advocate metadata (the norm
    before the ~1970s): petitioner's counsel opens and rebuts, respondent's
    argues in between — so the first-appearing arguing speaker is the
    petitioner side, the second distinct one the respondent, and any further
    new speaker (amicus, divided argument) stays unknown."""
    assign, seen = {}, []
    for dom in dominants:
        if dom and dom not in assign:
            seen.append(dom)
            assign[dom] = "pet" if len(seen) == 1 else (
                "resp" if len(seen) == 2 else None)
    return assign


# ---------------------------------------------------------------- features

def case_features(detail, term, match, budget):
    """All argument sessions of one case -> per-justice side-attributed
    counts {mn: {tp, wp, tr, wr}}, plus audit info. None if no transcript."""
    sides = advocate_sides(detail)
    counts, unattributed, sessions = {}, 0, 0
    order_fallback = False
    for oa in detail.get("oral_argument_audio") or []:
        href = oa.get("href")
        if not href:
            continue
        media = fetch_json(href, f"oa-{oa.get('id')}", budget)
        transcript = (media or {}).get("transcript")
        if not transcript:
            continue
        sessions += 1
        sections = transcript.get("sections") or []
        dominants = [dominant_speaker(s, match, term) for s in sections]
        session_sides = sides
        if not any(sides.get(d) for d in dominants if d):
            # no usable advocate metadata for this session (pre-1970s norm)
            session_sides = order_heuristic_sides(dominants)
            order_fallback = True
        for section, dom in zip(sections, dominants):
            side = session_sides.get(dom)
            for turn in section.get("turns") or []:
                mn = match(turn.get("speaker"), term)
                if not mn:
                    continue
                if side is None:
                    unattributed += 1
                    continue
                row = counts.setdefault(mn, {"tp": 0, "wp": 0, "tr": 0, "wr": 0})
                row["t" + side[0]] += 1
                row["w" + side[0]] += _turn_words(turn)
    if not sessions:
        return None
    out = {"sessions": sessions, "justices": counts}
    sg = sg_amicus_side(detail)
    if sg:
        out["sg_amicus"] = sg
    if order_fallback:
        out["side_basis"] = "section-order"  # heuristic, not advocate metadata
    if unattributed:
        out["unattributed_turns"] = unattributed
    if any(v is None for v in sides.values()):
        out["unsided_advocates"] = sorted(k for k, v in sides.items() if v is None)
    return out


# ---------------------------------------------------------------- harvest

def argued_cases(term):
    """Argued case records for a term, keyed by docket slug — decided cases
    (data/cases) plus argued-but-undecided ones (data/docket), so the current
    term's pending cases get questioning features the day their transcript
    posts (the post-argument forecast stage feeds on this)."""
    out = {}
    for root in (DATA / "cases" / str(term), DATA / "docket" / str(term)):
        if not root.exists():
            continue
        for f in sorted(root.glob("*.yaml")):
            case = yaml.safe_load(f.read_text(encoding="utf-8"))
            docket = case.get("docket")
            if docket and (case.get("dates") or {}).get("argued"):
                out.setdefault(docket_slug(str(docket)), case["id"])
    return out


def harvest_term(term, budget, verbose=False, workers=4, fresh=False):
    out_path = ORAL / f"{term}.yaml"
    ours = argued_cases(term)
    if not ours:
        print(f"term {term}: no argued cases in data/cases or data/docket — skipped")
        return
    listing = fetch_json(
        f"https://api.oyez.org/cases?filter=term:{term}&per_page=300",
        f"term-{term}", budget, fresh=fresh) or []
    stubs = {docket_slug((s.get("docket_number") or "").strip()): s
             for s in listing if s.get("docket_number") and s.get("href")}
    match = justice_matcher()

    def one(item):
        dslug, cid = item
        stub = stubs.get(dslug)
        if not stub:
            return None
        detail = fetch_json(stub["href"], f"case-{term}-{dslug}", budget, fresh=fresh)
        if not detail:
            return None
        feats = case_features(detail, term, match, budget)
        if feats is None:
            return None
        return cid, stub["docket_number"].strip(), feats

    cases, with_transcript = {}, 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        results = ex.map(one, sorted(ours.items()))
        for res in results:
            if res is None:
                continue
            cid, docket, feats = res
            with_transcript += 1
            cases[cid] = {"docket": docket, **feats}
            if verbose:
                tot = {k: sum(j[k] for j in feats["justices"].values())
                       for k in ("tp", "tr")}
                print(f"  {cid} ({docket}): "
                      f"{feats['sessions']} session(s), "
                      f"turns pet {tot['tp']} / resp {tot['tr']}, "
                      f"{len(feats['justices'])} justices"
                      + (f", unattributed {feats.get('unattributed_turns')}"
                         if feats.get("unattributed_turns") else ""))

    ORAL.mkdir(parents=True, exist_ok=True)
    dump_yaml({"term": term,
               "coverage": {"argued": len(ours), "oyez_matched":
                            sum(1 for d in ours if d in stubs),
                            "with_transcript": with_transcript},
               "cases": cases}, out_path)
    print(f"term {term}: {with_transcript}/{len(ours)} argued cases with "
          f"transcript features -> {out_path.relative_to(DATA.parent)} "
          f"({_spent} requests spent)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--terms", type=int, nargs=2, metavar=("FIRST", "LAST"))
    ap.add_argument("--current", action="store_true",
                    help="harvest the term in progress (and the next term's early "
                         "arguments) with --refresh, so just-argued pending cases "
                         "gain features as Oyez posts transcripts")
    ap.add_argument("--pilot", type=int, help="single term, verbose per-case report")
    ap.add_argument("--budget", type=int, default=2000,
                    help="max network requests this run (cached fetches free)")
    ap.add_argument("--refresh", action="store_true",
                    help="rebuild term files that already exist")
    ap.add_argument("--workers", type=int, default=4,
                    help="concurrent fetch workers within a term (default 4)")
    args = ap.parse_args()

    if args.pilot:
        terms = [args.pilot]
    elif args.current:
        import datetime
        today = datetime.date.today()
        current_ot = today.year if today.month >= 10 else today.year - 1
        terms = [current_ot, current_ot + 1]
        args.refresh = True  # transcripts accrue as cases get argued
    elif args.terms:
        terms = list(range(args.terms[0], args.terms[1] + 1))
    else:
        ap.error("--terms FIRST LAST, --current, or --pilot TERM required")

    for term in terms:
        out_path = ORAL / f"{term}.yaml"
        if out_path.exists() and not args.refresh and not args.pilot:
            continue  # term already harvested — resume granularity
        try:
            harvest_term(term, args.budget, verbose=bool(args.pilot),
                         workers=args.workers, fresh=bool(args.current))
        except BudgetExhausted:
            print(f"request budget ({args.budget}) exhausted at term {term} — "
                  f"resume with the same command (cache makes re-entry free)")
            return
    print(f"done: {_spent} requests spent")


if __name__ == "__main__":
    main()
