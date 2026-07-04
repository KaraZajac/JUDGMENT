"""Match SCOTUS cases to their lower-court opinions and harvest the text.

The pilot (git history) showed name-similarity search fails: rate limits
unauthenticated and matches "Cruz v. Arizona" to "Cruz v. Cruz". This version
joins precisely: the supremecourt.gov docket JSON carries `LowerCourt` (name)
and `LowerCourtCaseNumbers` (circuit docket numbers, or a neutral citation for
state courts); those resolve on CourtListener's authenticated API
(COURTLISTENER_TOKEN in .env or the environment) via the dockets endpoint or a
quoted-citation search. Opinion text lands in sources/lc/ (gitignored); match
metadata + SCDB labels land in data/text/lc-matches.yaml for the classifier
(models/lc_classifier.py).

  python3 -m pipeline.lc_opinions --harvest --start 2017   # historical training pairs
  python3 -m pipeline.lc_opinions --pending                # pending docket cases
"""

import argparse
import datetime
import json
import os
import re
import urllib.parse
from urllib.error import HTTPError, URLError

import yaml

from . import _env  # noqa: F401
from .build import DATA, SOURCES, clean, read_rows, to_int
from .interim import docket_slug, fetch_json, scotus_docket

# Committed with the dataset: court opinions are public-domain text, and the
# CI harvest tranches need persistence across runs.
LC_DIR = DATA / "text" / "lc"

# CourtListener free-tier limits: 5/min, 50/hr, 125/day. Space authenticated
# calls at 13s (≈4.6/min) and retry once after a full minute on 429. Cached
# responses cost nothing, so resumed runs skip already-fetched cases.
CL_SPACING_S = 13.0
_last_cl_call = [0.0]
cl_requests_made = [0]


def _throttle():
    import time as _t
    wait = CL_SPACING_S - (_t.monotonic() - _last_cl_call[0])
    if wait > 0:
        _t.sleep(wait)
    _last_cl_call[0] = _t.monotonic()

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


def cl_get(url, cache_name, refresh=False):
    from .interim import CACHE
    if not refresh and (CACHE / cache_name).exists():
        return fetch_json(url, cache_name, False, {})  # cache hit, no request
    headers = {}
    token = os.environ.get("COURTLISTENER_TOKEN")
    if token:
        headers["Authorization"] = f"Token {token}"
    _throttle()
    cl_requests_made[0] += 1
    try:
        return fetch_json(url, cache_name, refresh, headers)
    except HTTPError as e:
        if e.code == 429:  # over the per-minute window: wait it out once
            import time as _t
            _t.sleep(65)
            _last_cl_call[0] = _t.monotonic()
            cl_requests_made[0] += 1
            return fetch_json(url, cache_name, refresh, headers)
        raise


def court_id_for(lower_court_name):
    name = (lower_court_name or "").lower()
    for key, cid in CIRCUITS.items():
        if key in name:
            return cid
    return None  # state courts etc. resolved by citation instead


def resolve_cluster(lower_court, case_numbers, decided_hint):
    """-> (cluster_id, how) or (None, reason)."""
    cite_m = CITATION_RE.search(case_numbers or "")
    if cite_m:
        cite = re.sub(r"\s+", " ", cite_m.group(1)).strip()
        q = urllib.parse.urlencode({"q": f'"{cite}"', "type": "o"})
        payload = cl_get(f"https://www.courtlistener.com/api/rest/v4/search/?{q}",
                         f"cl-cite-{docket_slug(cite)}.json")
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
        payload = cl_get(f"https://www.courtlistener.com/api/rest/v4/dockets/?{q}",
                         f"cl-docket-{cid}-{docket_slug(dn)}.json")
        for d in (payload.get("results") or []):
            clusters = d.get("clusters") or []
            if clusters:
                m = re.search(r"/(\d+)/?$", str(clusters[0]))
                if m:
                    return int(m.group(1)), f"docket:{cid}/{dn}"
    return None, f"docket-no-cluster:{cid}/{dockets[0]}"


def opinion_text(cluster_id):
    payload = cl_get(f"https://www.courtlistener.com/api/rest/v4/clusters/{cluster_id}/",
                     f"cl-cluster-{cluster_id}.json")
    subs = payload.get("sub_opinions") or []
    texts = []
    for sub in subs[:2]:
        m = re.search(r"/(\d+)/?$", str(sub))
        if not m:
            continue
        op = cl_get(f"https://www.courtlistener.com/api/rest/v4/opinions/{m.group(1)}/",
                    f"cl-opinion-{m.group(1)}.json")
        text = (op.get("plain_text") or "").strip()
        if not text:
            html_src = op.get("html_with_citations") or op.get("html") or ""
            text = re.sub(r"<[^>]+>", " ", html_src)
            text = re.sub(r"\s+", " ", text).strip()
        if text:
            texts.append(text)
    return "\n\n".join(texts) if texts else None


def process_case(case_id, scotus_docket_number, label=None, refresh=False):
    dj = scotus_docket(scotus_docket_number, refresh)
    if not dj:
        return {"caseId": case_id, "status": "no-scotus-docket"}
    lower_court = clean(dj.get("LowerCourt"))
    numbers = clean(dj.get("LowerCourtCaseNumbers"))
    if not lower_court:
        return {"caseId": case_id, "status": "no-lower-court"}
    try:
        cluster, how = resolve_cluster(lower_court, numbers, dj.get("LowerCourtDecision"))
    except (HTTPError, URLError, TimeoutError, ValueError) as e:
        return {"caseId": case_id, "status": f"fetch-error:{type(e).__name__}"}
    if cluster is None:
        return {"caseId": case_id, "status": how, "lower_court": lower_court}
    try:
        text = opinion_text(cluster)
    except (HTTPError, URLError, TimeoutError, ValueError) as e:
        return {"caseId": case_id, "status": f"fetch-error:{type(e).__name__}"}
    if not text or len(text) < 500:
        return {"caseId": case_id, "status": "no-text", "cluster": cluster}
    LC_DIR.mkdir(parents=True, exist_ok=True)
    with open(LC_DIR / f"{case_id}.json", "w", encoding="utf-8") as f:
        json.dump({"caseId": case_id, "cluster": cluster, "how": how,
                   "lower_court": lower_court, "text": text}, f)
    return {"caseId": case_id, "status": "ok", "cluster": cluster, "how": how,
            "lower_court": lower_court, "chars": len(text), "label": label}


def harvest(start, end, refresh=False, budget=100):
    manifest = yaml.safe_load((SOURCES / "manifest.yaml").read_text())
    rows = []
    for row in read_rows(manifest["files"]["modern_case"]):
        term = to_int(row.get("term"))
        docket = clean(row.get("docket"))
        label = to_int(row.get("lcDispositionDirection"))
        if term is None or not (start <= term <= end) or not docket:
            continue
        rows.append((clean(row.get("caseId")), docket, label))

    already = set()
    manifest_path = DATA / "text" / "lc-matches.yaml"
    if manifest_path.exists():
        already = set((yaml.safe_load(manifest_path.read_text()) or {})
                      .get("matches", {}))

    print(f"harvest: {len(rows)} SCDB cases with dockets, terms {start}-{end}; "
          f"{len(already)} already matched; CL budget {budget} requests "
          f"(free tier: 125/day — resumable, cached cases cost nothing)")
    results, ok = [], 0
    for i, (cid, docket, label) in enumerate(rows, 1):
        if cl_requests_made[0] >= budget:
            print(f"  request budget reached at case {i}/{len(rows)} — "
                  f"run again tomorrow (or after a limit bump) to continue")
            break
        r = process_case(cid, docket, label)
        results.append(r)
        ok += r["status"] == "ok"
        if i % 20 == 0:
            print(f"  ... {i}/{len(rows)} (matched-with-text {ok}, "
                  f"CL requests {cl_requests_made[0]})", flush=True)

    matches = {r["caseId"]: {"cluster": r["cluster"], "how": r["how"],
                             "lower_court": r["lower_court"], "chars": r["chars"],
                             "lc_direction_label": r["label"]}
               for r in results if r["status"] == "ok"}
    if manifest_path.exists():  # merge with prior partial runs (resumable)
        prior = (yaml.safe_load(manifest_path.read_text()) or {}).get("matches", {})
        matches = {**prior, **matches}
    statuses = {}
    for r in results:
        key = r["status"].split(":")[0]
        statuses[key] = statuses.get(key, 0) + 1
    dest = DATA / "text"
    dest.mkdir(exist_ok=True)
    with open(dest / "lc-matches.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "generated": datetime.datetime.now(datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "terms": [start, end],
            "status_counts": statuses,
            "matches": matches,
        }, f, sort_keys=False, width=110)
    print(f"\nwrote data/text/lc-matches.yaml: {ok}/{len(rows)} matched with text")
    print("status counts:", statuses)


def pending(refresh=False):
    docket_root = DATA / "docket"
    results = []
    for tdir in sorted(docket_root.iterdir()):
        if not tdir.is_dir():
            continue
        for f in sorted(tdir.glob("*.yaml")):
            case = yaml.safe_load(f.read_text(encoding="utf-8"))
            r = process_case(f"pending-{case['id']}", case.get("docket"))
            r["id"] = case["id"]
            results.append(r)
            print(f"  {case['id']}: {r['status']}"
                  + (f" ({r.get('how')}, {r.get('chars'):,} chars)"
                     if r["status"] == "ok" else ""), flush=True)
    ok = sum(r["status"] == "ok" for r in results)
    print(f"\npending: {ok}/{len(results)} lower-court opinions resolved")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harvest", action="store_true")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--start", type=int, default=2017)
    ap.add_argument("--end", type=int, default=2024)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--budget", type=int, default=100,
                    help="max CourtListener requests this run (free tier: 125/day)")
    args = ap.parse_args()
    if not os.environ.get("COURTLISTENER_TOKEN"):
        raise SystemExit("COURTLISTENER_TOKEN not set (.env or environment)")
    if args.harvest:
        harvest(args.start, args.end, args.refresh, args.budget)
    if args.pending:
        pending(args.refresh)
    if not (args.harvest or args.pending):
        ap.print_help()


if __name__ == "__main__":
    main()
