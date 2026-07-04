"""Harvest question-presented text for the historical corpus -> data/text/.

The question presented is fixed when certiorari is granted, so unlike SCDB's
post-hoc issue coding it is genuinely knowable pre-decision — a legitimate
forecasting feature. Source: Oyez case records (solid coverage of argued cases
since the mid-1950s; earlier terms are spotty and simply yield fewer matches).
Oyez's facts/conclusion narratives are deliberately NOT harvested — they are
editor-written, often post-decision, and would leak.

Joins to SCDB caseIds by (term, normalized docket). Fetches share the
sources/interim/ cache with pipeline.interim, so re-runs and interim runs
never refetch the same case.

  python3 -m pipeline.questions              # fetch (resumable) + write
  python3 -m pipeline.questions --start 1946 # override first term
"""

import argparse
import datetime
from urllib.error import HTTPError, URLError

import yaml

from .build import DATA, SOURCES, clean, read_rows, to_int
from .interim import docket_slug, fetch_json, oyez_detail, oyez_term_stubs, strip_html


def scdb_docket_map():
    """(term, normalized docket) -> caseId, from the modern case-centered file."""
    manifest = yaml.safe_load((SOURCES / "manifest.yaml").read_text())
    out = {}
    for row in read_rows(manifest["files"]["modern_case"]):
        cid = clean(row.get("caseId"))
        term = to_int(row.get("term"))
        docket = clean(row.get("docket"))
        if cid and term is not None and docket:
            out[(term, docket_slug(docket))] = cid
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1946)
    ap.add_argument("--end", type=int, default=None)
    args = ap.parse_args()

    scdb = scdb_docket_map()
    end = args.end or max(t for t, _ in scdb)

    questions = {}       # caseId -> question text
    per_decade = {}      # decade -> [matched_with_text, scdb_cases]
    fetch_errors = 0

    for term in range(args.start, end + 1):
        try:
            stubs = oyez_term_stubs(term, refresh=False)
        except (HTTPError, URLError, TimeoutError, ValueError):
            print(f"  term {term}: list fetch failed, skipping", flush=True)
            fetch_errors += 1
            continue
        matched = with_text = 0
        for stub in stubs:
            docket = stub["docket_number"].strip()
            cid = scdb.get((term, docket_slug(docket)))
            if cid is None:
                continue
            matched += 1
            try:
                detail = oyez_detail(term, stub, refresh=False)
            except (HTTPError, URLError, TimeoutError, ValueError):
                fetch_errors += 1
                continue
            q = strip_html(detail.get("question"))
            if q and len(q) > 40:  # empty/stub questions carry no signal
                questions[cid] = q
                with_text += 1
        decade = term // 10 * 10
        d = per_decade.setdefault(decade, [0, 0])
        d[0] += with_text
        d[1] += sum(1 for (t, _) in scdb if t == term)
        print(f"  term {term}: {len(stubs)} oyez cases, {matched} matched to SCDB, "
              f"{with_text} with usable question", flush=True)

    dest = DATA / "text"
    dest.mkdir(exist_ok=True)
    payload = {
        "generated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Oyez question presented (api.oyez.org), joined by term+docket; "
                  "cert-stage text, safe as a pre-decision feature",
        "coverage_by_decade": {
            f"{d}s": f"{v[0]}/{v[1]}" for d, v in sorted(per_decade.items())},
        "questions": dict(sorted(questions.items())),
    }
    with open(dest / "questions.yaml", "w", encoding="utf-8") as f:
        yaml.dump(payload, f, sort_keys=False, allow_unicode=True, width=110)
    print(f"\nwrote data/text/questions.yaml: {len(questions):,} questions "
          f"({fetch_errors} fetch errors)")
    for d, v in sorted(per_decade.items()):
        print(f"  {d}s: {v[0]}/{v[1]} SCDB cases covered")


if __name__ == "__main__":
    main()
