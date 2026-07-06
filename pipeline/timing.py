"""Cert-grant dates from the Oyez case-detail cache -> data/timing/<term>.yaml.

SCDB records argument and decision dates but not cert-grant dates. The
oral-argument harvest (pipeline.oral_args) already caches the full Oyez case
detail — timeline included — for every argued case it touches, so grant
dates come from disk, no network. Coverage is honest about the source:
Oyez's "Granted" timeline event is dependable from the mid-2000s onward and
sparse before (~7% pre-2000); the site's timeline renders whatever exists.

Output: data/timing/<term>.yaml — {case_id: 'YYYY-MM-DD'} for cases whose
own record lacks dates.granted (provisional records already carry it).

  python3 -m pipeline.timing            # all cached terms
"""

import datetime
import gzip
import json
from zoneinfo import ZoneInfo

import yaml

from .build import DATA, SOURCES, dump_yaml
from .interim import docket_slug

CACHE = SOURCES / "oral-args"
ET = ZoneInfo("America/New_York")


def granted_date(detail):
    for e in detail.get("timeline") or []:
        if e and e.get("event") == "Granted":
            ts = (e.get("dates") or [None])[0]
            if ts:
                return datetime.datetime.fromtimestamp(
                    int(ts), tz=ET).date().isoformat()
    return None


def main():
    if not CACHE.exists():
        raise SystemExit("no sources/oral-args cache — run pipeline.oral_args first")
    out_root = DATA / "timing"
    out_root.mkdir(exist_ok=True)
    terms_written = entries = 0
    by_term = {}
    for f in sorted(CACHE.glob("case-*.json.gz")):
        stem = f.name[len("case-"):-len(".json.gz")]
        term, dslug = stem.split("-", 1)
        by_term.setdefault(int(term), []).append((dslug, f))
    for term, files in sorted(by_term.items()):
        tdir = DATA / "cases" / str(term)
        if not tdir.exists():
            continue
        ours = {}
        for cf in tdir.glob("*.yaml"):
            case = yaml.safe_load(cf.read_text(encoding="utf-8"))
            if case.get("docket") and not (case.get("dates") or {}).get("granted"):
                ours[docket_slug(str(case["docket"]))] = case["id"]
        grants = {}
        for dslug, f in files:
            cid = ours.get(dslug)
            if not cid:
                continue
            try:
                detail = json.load(gzip.open(f, "rt", encoding="utf-8"))
            except Exception:
                continue
            g = granted_date(detail)
            if g:
                grants[cid] = g
        if grants:
            dump_yaml(dict(sorted(grants.items())), out_root / f"{term}.yaml")
            terms_written += 1
            entries += len(grants)
    print(f"wrote {entries:,} grant dates across {terms_written} terms -> data/timing/")


if __name__ == "__main__":
    main()
