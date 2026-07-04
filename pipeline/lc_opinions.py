"""PILOT: can SCDB cases be matched to their lower-court opinions on CourtListener?

Before committing to a direction classifier trained on lower-court opinion text,
measure the matching yield: for recent-term SCDB cases, search CourtListener's
free search API for the case name among non-SCOTUS opinions filed in a window
before the Supreme Court decision, and score name similarity.

  python3 -m pipeline.lc_opinions --pilot          # 2022-2024 terms (~180 cases)
  python3 -m pipeline.lc_opinions --pilot --start 2018

Emits a match-rate report and caches candidates in sources/interim/. No data/
output yet — this is reconnaissance (task: LC-opinion matching pilot).
"""

import argparse
import difflib
import re
import urllib.parse
from urllib.error import HTTPError, URLError

import yaml

from .build import SOURCES, clean, read_rows, to_int
from .interim import fetch_json

STOP = {"et", "al", "al.", "etc", "the", "of"}


def norm_name(name):
    """SCDB ALL-CAPS caption -> compact 'x v. y' for querying/matching."""
    if not name:
        return None
    s = re.sub(r"[^A-Za-z0-9 ]", " ", name.lower())
    s = re.sub(r"\b(versus|vs)\b", "v", s)
    words = [w for w in s.split() if w not in STOP]
    return " ".join(words[:12])


def similarity(a, b):
    return difflib.SequenceMatcher(None, norm_name(a) or "", norm_name(b) or "").ratio()


def cl_candidates(case_name, decided_year, refresh=False):
    """Top CL non-SCOTUS opinion hits for this name in a plausible window."""
    q = norm_name(case_name)
    if not q or len(q) < 8:
        return []
    params = urllib.parse.urlencode({
        "type": "o", "q": f'"{q.split(" v ")[0][:40]}"',
        "filed_after": f"{decided_year - 5}-01-01",
        "filed_before": f"{decided_year}-12-31",
        "order_by": "score desc",
    })
    url = f"https://www.courtlistener.com/api/rest/v4/search/?{params}"
    slug = re.sub(r"[^a-z0-9]+", "-", q)[:60]
    try:
        payload = fetch_json(url, f"cl-lc-{slug}.json", refresh)
    except (HTTPError, URLError, TimeoutError, ValueError) as e:
        return None  # fetch failure, distinct from "no match"
    out = []
    for r in (payload.get("results") or [])[:10]:
        if r.get("court_id") == "scotus":
            continue
        out.append({
            "cl_case": r.get("caseName"),
            "court": r.get("court"),
            "court_id": r.get("court_id"),
            "filed": r.get("dateFiled"),
            "cluster": r.get("cluster_id"),
            "sim": round(similarity(case_name, r.get("caseName")), 3),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true", required=True)
    ap.add_argument("--start", type=int, default=2022)
    ap.add_argument("--end", type=int, default=2024)
    args = ap.parse_args()

    manifest = yaml.safe_load((SOURCES / "manifest.yaml").read_text())
    cases = []
    for row in read_rows(manifest["files"]["modern_case"]):
        term = to_int(row.get("term"))
        if term is None or not (args.start <= term <= args.end):
            continue
        lc_dir = to_int(row.get("lcDispositionDirection"))
        year = to_int((clean(row.get("dateDecision")) or "//0").split("/")[-1])
        cases.append({"caseId": clean(row.get("caseId")),
                      "name": clean(row.get("caseName")),
                      "year": year or term + 1,
                      "lc_direction": lc_dir})

    print(f"pilot: {len(cases)} SCDB cases, terms {args.start}-{args.end}")
    matched = strong = failed = 0
    samples = []
    for i, c in enumerate(cases, 1):
        cands = cl_candidates(c["name"], c["year"])
        if cands is None:
            failed += 1
            continue
        best = max(cands, key=lambda x: x["sim"], default=None)
        if best and best["sim"] >= 0.55:
            matched += 1
            if best["sim"] >= 0.75:
                strong += 1
            if len(samples) < 8:
                samples.append((c["name"][:44], best["cl_case"][:44],
                                best["court_id"], best["sim"]))
        if i % 25 == 0:
            print(f"  ... {i}/{len(cases)} (matched {matched}, strong {strong}, "
                  f"fetch-failed {failed})", flush=True)

    n_ok = len(cases) - failed
    print(f"\nRESULT: {matched}/{n_ok} matched at sim>=0.55 "
          f"({matched / max(n_ok, 1):.0%}), {strong} strong (>=0.75); "
          f"{failed} fetch failures")
    print("samples (SCDB -> CL, court, sim):")
    for s in samples:
        print("  ", s)


if __name__ == "__main__":
    main()
