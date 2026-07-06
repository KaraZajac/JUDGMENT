"""Emit data/aggregates/terms.yaml — per-term rollups for the site.

Streams the case-centered SCDB CSVs (same sources as pipeline.build), so it must
be re-run alongside build when sources change: one entry per term with case count,
decision-direction split, reversal share, unanimity, the vote-split histogram, and
deliberation timing (median days argument→decision from SCDB dates for all eras;
median days grant→argument where grant dates exist — data/timing/, Oyez-derived,
dependable from the mid-2000s).
"""

import datetime
import statistics
from collections import defaultdict
from pathlib import Path

import yaml

from .build import DATA, SOURCES, clean, read_rows, to_int

# caseDisposition codes where the petitioner disturbed the judgment below
REVERSING = {3, 4, 5, 6, 7, 8}

MIN_TIMING_N = 10  # don't publish a median from fewer intervals


def parse_us_date(s):
    s = clean(s)
    if not s:
        return None
    try:
        return datetime.datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        return None


def grant_dates():
    """caseId -> granted date, from the Oyez-derived sidecar (pipeline.timing)."""
    out = {}
    tdir = DATA / "timing"
    if tdir.exists():
        for f in sorted(tdir.glob("*.yaml")):
            for cid, iso in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).items():
                try:
                    out[cid] = datetime.date.fromisoformat(str(iso))
                except ValueError:
                    pass
    return out


def timing_fields(entry, arg_to_dec, grant_to_arg):
    """Attach median-day fields where enough intervals exist."""
    if len(arg_to_dec) >= MIN_TIMING_N:
        entry["median_days_argument_to_decision"] = round(
            statistics.median(arg_to_dec))
        entry["timed_cases"] = len(arg_to_dec)
    if len(grant_to_arg) >= MIN_TIMING_N:
        entry["median_days_grant_to_argument"] = round(
            statistics.median(grant_to_arg))
        entry["granted_dated_cases"] = len(grant_to_arg)


def main():
    manifest = yaml.safe_load((SOURCES / "manifest.yaml").read_text())
    files = manifest["files"]

    terms = defaultdict(lambda: {
        "cases": 0, "liberal": 0, "conservative": 0, "unspecifiable": 0,
        "reversed": 0, "dispositions": 0, "unanimous": 0, "with_votes": 0,
        "splits": defaultdict(int), "arg_to_dec": [], "grant_to_arg": [],
    })
    granted = grant_dates()

    for fn in (files["modern_case"], files["legacy_case"]):
        for row in read_rows(fn):
            term = to_int(row.get("term"))
            if term is None or not clean(row.get("caseId")):
                continue
            t = terms[term]
            t["cases"] += 1
            arg = parse_us_date(row.get("dateArgument"))
            dec = parse_us_date(row.get("dateDecision"))
            if arg and dec and 0 <= (dec - arg).days <= 1500:
                t["arg_to_dec"].append((dec - arg).days)
            g = granted.get(clean(row.get("caseId")))
            if g and arg and 0 <= (arg - g).days <= 1500:
                t["grant_to_arg"].append((arg - g).days)
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
        timing_fields(entry, t["arg_to_dec"], t["grant_to_arg"])
        out.append(entry)

    # provisional terms ingested by pipeline.interim (beyond SCDB coverage):
    # only vote-count facts are computable — no direction/reversal coding.
    csv_max = max(terms) if terms else 0
    for tdir in sorted((DATA / "cases").iterdir()):
        if not tdir.name.isdigit() or int(tdir.name) <= csv_max:
            continue
        t = {"cases": 0, "unanimous": 0, "splits": defaultdict(int),
             "arg_to_dec": [], "grant_to_arg": []}
        for f in sorted(tdir.glob("*.yaml")):
            c = yaml.safe_load(f.read_text(encoding="utf-8"))
            t["cases"] += 1
            dec = c.get("decision") or {}
            maj, mnr = dec.get("majority_votes"), dec.get("minority_votes")
            if isinstance(maj, int) and isinstance(mnr, int):
                t["splits"][f"{maj}-{mnr}"] += 1
                if mnr == 0:
                    t["unanimous"] += 1
            dates = c.get("dates") or {}
            try:
                g, a, de = (datetime.date.fromisoformat(str(dates[k]))
                            if dates.get(k) else None
                            for k in ("granted", "argued", "decided"))
            except ValueError:
                g = a = de = None
            if a and de and 0 <= (de - a).days <= 1500:
                t["arg_to_dec"].append((de - a).days)
            if g and a and 0 <= (a - g).days <= 1500:
                t["grant_to_arg"].append((a - g).days)
        if t["cases"]:
            entry = {
                "term": int(tdir.name),
                "provisional": True,
                "cases": t["cases"],
                "liberal": 0, "conservative": 0, "unspecifiable": 0,
                "unanimous": t["unanimous"],
                "splits": dict(sorted(t["splits"].items(),
                                      key=lambda kv: -int(kv[0].split("-")[0]))),
            }
            timing_fields(entry, t["arg_to_dec"], t["grant_to_arg"])
            out.append(entry)

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
