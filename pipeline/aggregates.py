"""Emit data/aggregates/terms.yaml — per-term rollups for the site.

Streams the case-centered SCDB CSVs (same sources as pipeline.build), so it must
be re-run alongside build when sources change: one entry per term with case count,
decision-direction split, reversal share, unanimity, and the vote-split histogram.
"""

import datetime
from collections import defaultdict
from pathlib import Path

import yaml

from .build import DATA, SOURCES, clean, read_rows, to_int

# caseDisposition codes where the petitioner disturbed the judgment below
REVERSING = {3, 4, 5, 6, 7, 8}


def main():
    manifest = yaml.safe_load((SOURCES / "manifest.yaml").read_text())
    files = manifest["files"]

    terms = defaultdict(lambda: {
        "cases": 0, "liberal": 0, "conservative": 0, "unspecifiable": 0,
        "reversed": 0, "dispositions": 0, "unanimous": 0, "with_votes": 0,
        "splits": defaultdict(int),
    })

    for fn in (files["modern_case"], files["legacy_case"]):
        for row in read_rows(fn):
            term = to_int(row.get("term"))
            if term is None or not clean(row.get("caseId")):
                continue
            t = terms[term]
            t["cases"] += 1
            direction = to_int(row.get("decisionDirection"))
            if direction == 1:
                t["conservative"] += 1
            elif direction == 2:
                t["liberal"] += 1
            elif direction == 3:
                t["unspecifiable"] += 1
            dispo = to_int(row.get("caseDisposition"))
            if dispo is not None:
                t["dispositions"] += 1
                if dispo in REVERSING:
                    t["reversed"] += 1
            maj, mnr = to_int(row.get("majVotes")), to_int(row.get("minVotes"))
            if maj is not None and mnr is not None:
                t["with_votes"] += 1
                t["splits"][f"{maj}-{mnr}"] += 1
                if mnr == 0:
                    t["unanimous"] += 1

    out = []
    for term in sorted(terms):
        t = terms[term]
        directional = t["liberal"] + t["conservative"]
        entry = {
            "term": term,
            "cases": t["cases"],
            "liberal": t["liberal"],
            "conservative": t["conservative"],
            "unspecifiable": t["unspecifiable"],
            "unanimous": t["unanimous"],
            "splits": dict(sorted(t["splits"].items(),
                                  key=lambda kv: -int(kv[0].split("-")[0]))),
        }
        if directional:
            entry["liberal_share"] = round(t["liberal"] / directional, 3)
        if t["dispositions"]:
            entry["reversal_share"] = round(t["reversed"] / t["dispositions"], 3)
        out.append(entry)

    # provisional terms ingested by pipeline.interim (beyond SCDB coverage):
    # only vote-count facts are computable — no direction/reversal coding.
    csv_max = max(terms) if terms else 0
    for tdir in sorted((DATA / "cases").iterdir()):
        if not tdir.name.isdigit() or int(tdir.name) <= csv_max:
            continue
        t = {"cases": 0, "unanimous": 0, "splits": defaultdict(int)}
        for f in sorted(tdir.glob("*.yaml")):
            c = yaml.safe_load(f.read_text(encoding="utf-8"))
            t["cases"] += 1
            dec = c.get("decision") or {}
            maj, mnr = dec.get("majority_votes"), dec.get("minority_votes")
            if isinstance(maj, int) and isinstance(mnr, int):
                t["splits"][f"{maj}-{mnr}"] += 1
                if mnr == 0:
                    t["unanimous"] += 1
        if t["cases"]:
            out.append({
                "term": int(tdir.name),
                "provisional": True,
                "cases": t["cases"],
                "liberal": 0, "conservative": 0, "unspecifiable": 0,
                "unanimous": t["unanimous"],
                "splits": dict(sorted(t["splits"].items(),
                                      key=lambda kv: -int(kv[0].split("-")[0]))),
            })

    dest = DATA / "aggregates"
    dest.mkdir(exist_ok=True)
    payload = {
        "generated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "terms": out,
    }
    with open(dest / "terms.yaml", "w", encoding="utf-8") as f:
        yaml.dump(payload, f, sort_keys=False, allow_unicode=True, width=110)
    print(f"wrote data/aggregates/terms.yaml ({len(out)} terms)")


if __name__ == "__main__":
    main()
