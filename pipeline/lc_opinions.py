"""Match SCOTUS cases to their lower-court opinions and harvest the text.

The pilot (git history) showed name-similarity search fails: rate limits
unauthenticated and matches "Cruz v. Arizona" to "Cruz v. Cruz". This version
joins precisely: the supremecourt.gov docket JSON carries `LowerCourt` (name)
and `LowerCourtCaseNumbers` (circuit docket numbers, or a neutral citation for
state courts); those resolve on CourtListener's authenticated API
(COURTLISTENER_TOKEN in .env or the environment) via the dockets endpoint or a
quoted-citation search. Opinion text lands in data/text/lc/ (committed);
match metadata + SCDB labels land in data/text/lc-matches.yaml for the
classifier (models/lc_classifier.py).

Both modes resume where the last run stopped. CourtListener allows 125
requests a day (pipeline/courtlistener.py keeps each run inside that), so the
work spreads over many runs, and every CI run starts with an empty download
cache. Each case's outcome is therefore recorded in a committed manifest
(lc-matches.yaml for the harvest, lc-pending.yaml for the docket), and a run
spends requests only on cases with no outcome yet, then on retries.

  python3 -m pipeline.lc_opinions --harvest --start 2017   # historical training pairs
  python3 -m pipeline.lc_opinions --pending                # pending docket cases
  python3 -m pipeline.lc_opinions --pending --harvest      # both, docket first (CI)
"""

import argparse
import datetime
import json
import re
import urllib.parse
from urllib.error import HTTPError

import yaml

from . import _env  # noqa: F401
from . import courtlistener as cl
from .build import DATA, SOURCES, clean, read_rows, to_int
from .interim import docket_slug, scotus_docket

# Committed with the dataset: court opinions are public-domain text, and the
# CI harvest tranches need persistence across runs.
LC_DIR = DATA / "text" / "lc"
MATCHES = DATA / "text" / "lc-matches.yaml"
PENDING = DATA / "text" / "lc-pending.yaml"

# Outcomes another try won't change. Anything else (a failed fetch, a
# supremecourt.gov docket that didn't load) is tried again on later runs,
# MAX_TRIES runs in all.
SETTLED = {"no-lower-court", "unresolvable", "citation-no-hit", "docket-no-cluster",
           "no-text", "not-found", "cl-error", "gave-up"}
MAX_TRIES = 3
RECHECK_DAYS = 14  # how often a docket case without lower-court text is looked up again

CIRCUITS = {
    "first circuit": "ca1", "second circuit": "ca2", "third circuit": "ca3",
    "fourth circuit": "ca4", "fifth circuit": "ca5", "sixth circuit": "ca6",
    "seventh circuit": "ca7", "eighth circuit": "ca8", "ninth circuit": "ca9",
    "tenth circuit": "ca10", "eleventh circuit": "ca11",
    "district of columbia circuit": "cadc", "federal circuit": "cafc",
    "armed forces": "afcca",
}

CITATION_RE = re.compile(r"\(\s*(\d{4}\s+[A-Z]{2,6}\s+\d+[^)]*)\)")
DOCKET_RE = re.compile(r"\b(\d{2}-\d{2,5})\b")


def court_id_for(lower_court_name):
    name = (lower_court_name or "").lower()
    for key, cid in CIRCUITS.items():
        if key in name:
            return cid
    return None  # state courts etc. resolved by citation instead


def resolve_cluster(lower_court, case_numbers, decided_hint, refresh=False):
    """-> (cluster_id, how) or (None, reason)."""
    cite_m = CITATION_RE.search(case_numbers or "")
    if cite_m:
        cite = re.sub(r"\s+", " ", cite_m.group(1)).strip()
        q = urllib.parse.urlencode({"q": f'"{cite}"', "type": "o"})
        payload = cl.get(f"{cl.API}/search/?{q}", f"cl-cite-{docket_slug(cite)}.json", refresh)
        hits = [r for r in (payload.get("results") or []) if r.get("court_id") != "scotus"]
        if hits:
            return hits[0].get("cluster_id"), f"citation:{cite}"
        return None, f"citation-no-hit:{cite}"

    cid = court_id_for(lower_court)
    dockets = DOCKET_RE.findall(case_numbers or "")
    if not cid or not dockets:
        return None, f"unresolvable:{(lower_court or '?')[:40]}|{(case_numbers or '?')[:40]}"
    for dn in dockets[:3]:
        q = urllib.parse.urlencode({"docket_number": dn, "court": cid})
        payload = cl.get(f"{cl.API}/dockets/?{q}",
                         f"cl-docket-{cid}-{docket_slug(dn)}.json", refresh)
        for d in (payload.get("results") or []):
            clusters = d.get("clusters") or []
            if clusters:
                m = re.search(r"/(\d+)/?$", str(clusters[0]))
                if m:
                    return int(m.group(1)), f"docket:{cid}/{dn}"
    return None, f"docket-no-cluster:{cid}/{dockets[0]}"


def opinion_text(cluster_id, refresh=False):
    payload = cl.get(f"{cl.API}/clusters/{cluster_id}/", f"cl-cluster-{cluster_id}.json",
                     refresh)
    subs = payload.get("sub_opinions") or []
    texts = []
    for sub in subs[:2]:
        m = re.search(r"/(\d+)/?$", str(sub))
        if not m:
            continue
        op = cl.get(f"{cl.API}/opinions/{m.group(1)}/", f"cl-opinion-{m.group(1)}.json",
                    refresh)
        text = (op.get("plain_text") or "").strip()
        if not text:
            html_src = op.get("html_with_citations") or op.get("html") or ""
            text = re.sub(r"<[^>]+>", " ", html_src)
            text = re.sub(r"\s+", " ", text).strip()
        if text:
            texts.append(text)
    return "\n\n".join(texts) if texts else None


def process_case(case_id, scotus_docket_number, label=None, refresh=False):
    """-> {"caseId", "status", ...}. Raises cl.Exhausted when the run may not
    send another CourtListener request; the case then stays unrecorded."""
    dj = scotus_docket(scotus_docket_number, refresh)
    if not dj:
        return {"caseId": case_id, "status": "no-scotus-docket"}
    lower_court = clean(dj.get("LowerCourt"))
    numbers = clean(dj.get("LowerCourtCaseNumbers"))
    if not lower_court:
        return {"caseId": case_id, "status": "no-lower-court"}
    try:
        cluster, how = resolve_cluster(lower_court, numbers,
                                       dj.get("LowerCourtDecision"), refresh)
        if cluster is None:
            return {"caseId": case_id, "status": how, "lower_court": lower_court}
        text = opinion_text(cluster, refresh)
    except HTTPError as e:
        if e.code >= 500:
            return {"caseId": case_id, "status": f"fetch-error:HTTP {e.code}"}
        # any other 4xx is CourtListener's answer about this case: it won't change
        status = "not-found" if e.code == 404 else f"cl-error:HTTP {e.code}"
        return {"caseId": case_id, "status": status, "lower_court": lower_court}
    except (OSError, ValueError) as e:  # network trouble or a garbled body: retry later
        return {"caseId": case_id, "status": f"fetch-error:{type(e).__name__}"}
    if not text or len(text) < 500:
        return {"caseId": case_id, "status": "no-text", "cluster": cluster}
    LC_DIR.mkdir(parents=True, exist_ok=True)
    with open(LC_DIR / f"{case_id}.json", "w", encoding="utf-8") as f:
        json.dump({"caseId": case_id, "cluster": cluster, "how": how,
                   "lower_court": lower_court, "text": text}, f)
    return {"caseId": case_id, "status": "ok", "cluster": cluster, "how": how,
            "lower_court": lower_court, "chars": len(text), "label": label}


def _kind(status):
    return status.split(":")[0]


def _load(path):
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _dump(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"generated": datetime.datetime.now(datetime.timezone.utc)
           .strftime("%Y-%m-%dT%H:%M:%SZ"), **doc}
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, sort_keys=False, width=110)


def harvest(start, end, refresh=False):
    manifest = yaml.safe_load((SOURCES / "manifest.yaml").read_text())
    rows = []
    for row in read_rows(manifest["files"]["modern_case"]):
        term = to_int(row.get("term"))
        docket = clean(row.get("docket"))
        label = to_int(row.get("lcDispositionDirection"))
        if term is None or not (start <= term <= end) or not docket:
            continue
        rows.append((clean(row.get("caseId")), docket, label))

    prior = _load(MATCHES)
    # a match whose text file has gone missing is fetched again
    matches = {cid: m for cid, m in (prior.get("matches") or {}).items()
               if (LC_DIR / f"{cid}.json").exists()}
    settled = dict(prior.get("settled") or {})
    retrying = dict(prior.get("retrying") or {})

    def tries(cid):
        return (retrying.get(cid) or {}).get("tries", 0)

    todo = [r for r in rows if r[0] not in matches and (refresh or r[0] not in settled)]
    todo.sort(key=lambda r: tries(r[0]))  # cases never tried first, in SCDB order
    print(f"harvest: {len(rows)} SCDB cases with dockets, terms {start}-{end}: "
          f"{len(matches)} matched, {len(settled)} settled without text, "
          f"{len(todo)} to try ({sum(1 for r in todo if tries(r[0]))} of them retries)",
          flush=True)

    tried, stop = 0, None
    try:
        for cid, docket, label in todo:
            try:
                r = process_case(cid, docket, label, refresh)
            except cl.Exhausted as e:
                stop = str(e)
                break
            tried += 1
            status = r["status"]
            if status == "ok":
                matches[cid] = {"cluster": r["cluster"], "how": r["how"],
                                "lower_court": r["lower_court"], "chars": r["chars"],
                                "lc_direction_label": r["label"]}
                settled.pop(cid, None)
                retrying.pop(cid, None)
            elif _kind(status) in SETTLED:
                settled[cid] = status
                retrying.pop(cid, None)
            elif tries(cid) + 1 >= MAX_TRIES:
                settled[cid] = f"gave-up:{status}"
                retrying.pop(cid, None)
            else:
                retrying[cid] = {"tries": tries(cid) + 1, "last": status}
            if tried % 10 == 0:
                print(f"  ... {tried} tried this run, {len(matches)} matched "
                      f"({cl.S.sent} CourtListener requests)", flush=True)
    finally:  # keep whatever this run learned, even if it dies part-way
        counts = {"matched": len(matches)}
        for kind in sorted({_kind(s) for s in settled.values()}):
            counts[kind] = sum(1 for s in settled.values() if _kind(s) == kind)
        counts["retrying"] = len(retrying)
        counts["untried"] = sum(1 for r in rows if r[0] not in matches
                                and r[0] not in settled and r[0] not in retrying)
        _dump(MATCHES, {"terms": [start, end], "status_counts": counts,
                        "matches": dict(sorted(matches.items())),
                        "settled": dict(sorted(settled.items())),
                        "retrying": dict(sorted(retrying.items()))})
    left = sum(1 for r in rows if r[0] not in matches and r[0] not in settled)
    print(f"\nwrote data/text/lc-matches.yaml: tried {tried} case(s) this run; "
          f"{len(matches)}/{len(rows)} matched with text, {len(settled)} settled "
          f"without, {left} still to do")
    print("status counts:", counts)
    if stop:
        print(f"  stopped: {stop}. The next run continues from here.")


def pending(refresh=False):
    """Lower-court opinions for the cases on the docket (the forecasting targets).
    A case with text on file is done; one without is looked up again every
    RECHECK_DAYS days, or on the next run after a failed fetch."""
    today = datetime.date.today()
    prior = _load(PENDING).get("cases") or {}
    cases = []
    for tdir in sorted((DATA / "docket").iterdir()):
        if not tdir.is_dir():
            continue
        for f in sorted(tdir.glob("*.yaml")):
            case = yaml.safe_load(f.read_text(encoding="utf-8"))
            cases.append((case["id"], case.get("docket")))

    def has_text(cid):
        return (LC_DIR / f"pending-{cid}.json").exists()

    def due(cid):
        seen = prior.get(cid)
        if refresh or not seen:
            return refresh or not has_text(cid)
        if has_text(cid):
            return False
        if _kind(seen["status"]) not in SETTLED and seen.get("tries", 1) < MAX_TRIES:
            return True  # a failed fetch: try again now
        checked = datetime.date.fromisoformat(seen["checked"])
        return (today - checked).days >= RECHECK_DAYS

    todo = [c for c in cases if due(c[0])]
    # new cases first, then the longest unchecked
    todo.sort(key=lambda c: (c[0] in prior, (prior.get(c[0]) or {}).get("checked", "")))
    print(f"pending: {len(cases)} docket cases, {sum(has_text(c) for c, _ in cases)} "
          f"with lower-court text; {len(todo)} to look up", flush=True)
    state = {cid: prior[cid] for cid, _ in cases if cid in prior}  # drop decided cases
    stop = None
    try:
        for cid, docket in todo:
            try:
                r = process_case(f"pending-{cid}", docket, refresh=refresh)
            except cl.Exhausted as e:
                stop = str(e)
                break
            entry = {"status": r["status"], "checked": today.isoformat()}
            if r["status"] != "ok" and _kind(r["status"]) not in SETTLED:
                # only failed fetches carry "tries", so a run of them counts up
                entry["tries"] = (state.get(cid) or {}).get("tries", 0) + 1
            state[cid] = entry
            print(f"  {cid}: {r['status']}"
                  + (f" ({r.get('how')}, {r.get('chars'):,} chars)"
                     if r["status"] == "ok" else ""), flush=True)
    finally:
        _dump(PENDING, {"recheck_days": RECHECK_DAYS, "cases": dict(sorted(state.items()))})
    print(f"\npending: {sum(has_text(c) for c, _ in cases)}/{len(cases)} docket cases "
          f"have lower-court text")
    if stop:
        print(f"  stopped: {stop}. The next run continues from here.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harvest", action="store_true",
                    help="historical training pairs, SCDB terms --start to --end")
    ap.add_argument("--pending", action="store_true",
                    help="the cases on the docket (run before --harvest when both are given)")
    ap.add_argument("--start", type=int, default=2017)
    ap.add_argument("--end", type=int, default=2024)
    ap.add_argument("--refresh", action="store_true",
                    help="ignore the download cache and look up settled cases again")
    ap.add_argument("--budget", type=int, default=cl.DEFAULT_BUDGET,
                    help="most CourtListener requests this run, retries included; set "
                         f"lower on its own so {cl.RESERVE} of the account's 125/day stay free")
    args = ap.parse_args()
    if not (args.harvest or args.pending):
        ap.print_help()
        return
    if not cl.token():
        raise SystemExit("COURTLISTENER_TOKEN not set (.env or environment)")
    cl.set_budget(args.budget)
    if args.pending:  # first: the docket feeds live forecasts; the backfill can wait
        pending(args.refresh)
    if args.harvest:
        harvest(args.start, args.end, args.refresh)
    print(cl.report())


if __name__ == "__main__":
    main()
