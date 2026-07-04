"""Enrich legacy justices from the FJC Biographical Directory of Federal Judges.

The 76 pre-1946 justices currently carry mechanically-derived names ("J.
McLean"). The Federal Judicial Center's judges export has the authoritative
record: full names, appointing president + party, commission and termination
dates, birth/death. This module matches our SCDB mnemonics to FJC people
(surname + initials + service-era overlap; multi-appointment people like
John Rutledge and both Hughes stints handled explicitly) and generates
pipeline/curated/justices-fjc.yaml — a FALLBACK merged by pipeline.build
wherever the hand-curated modern file has no entry.

  python3 -m pipeline.fjc      # requires sources/fjc-judges.csv (see README)
"""

import csv
import datetime
import re

import yaml

from .build import DATA, SOURCES, clean

FJC_CSV = SOURCES / "fjc-judges.csv"
OUT = SOURCES.parent / "pipeline" / "curated" / "justices-fjc.yaml"

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}

END_REASONS = {
    "death": "died", "retirement": "retired", "resignation": "resigned",
}


def iso(month, day, year):
    try:
        m = MONTHS.get(clean(month)) or int(month)
        return f"{int(year):04d}-{int(m):02d}-{int(day):02d}"
    except (TypeError, ValueError):
        try:
            return f"{int(year):04d}"
        except (TypeError, ValueError):
            return None


def date_iso(v):
    v = clean(v)
    if not v:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def fjc_scotus_appointments():
    """One record per (person, SCOTUS appointment)."""
    out = []
    with open(FJC_CSV, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            for n in range(1, 7):
                if clean(row.get(f"Court Name ({n})")) != "Supreme Court of the United States":
                    continue
                title = clean(row.get(f"Appointment Title ({n})")) or ""
                start = date_iso(row.get(f"Commission Date ({n})")) \
                    or date_iso(row.get(f"Recess Appointment Date ({n})"))
                # Retired justices keep the Article III office, so FJC's
                # Termination Date is their death; the retirement itself is
                # the Senior Status Date. Prefer it as the end of service.
                senior = date_iso(row.get(f"Senior Status Date ({n})"))
                termination = date_iso(row.get(f"Termination Date ({n})"))
                if senior:
                    end, reason = senior, "retirement"
                else:
                    end = termination
                    reason = (clean(row.get(f"Termination ({n})")) or "").lower()
                name_parts = [clean(row.get(k)) for k in
                              ("First Name", "Middle Name", "Last Name", "Suffix")]
                full = " ".join(p for p in name_parts if p)
                out.append({
                    "surname": re.sub(r"[^a-z]", "",
                                      (clean(row.get("Last Name")) or "").lower()),
                    "initials": "".join((clean(row.get(k)) or " ")[0]
                                        for k in ("First Name", "Middle Name")).strip().upper(),
                    "name": full,
                    "position": "chief" if "chief" in title.lower() else "associate",
                    "appointed_by": clean(row.get(f"Appointing President ({n})")),
                    "party": clean(row.get(f"Party of Appointing President ({n})")),
                    "oath": start,
                    "ended": end,
                    "end_reason": END_REASONS.get(reason, reason or None),
                    "born": iso(row.get("Birth Month"), row.get("Birth Day"),
                                row.get("Birth Year")),
                    "died": iso(row.get("Death Month"), row.get("Death Day"),
                                row.get("Death Year")),
                    "start_year": int(start[:4]) if start else None,
                    "end_year": int(end[:4]) if end else 9999,
                })
    return out


def mechanical_parts(mnemonic):
    m = re.match(r"^([A-Z]+)([A-Z][A-Za-z']+?)(\d*)$", mnemonic)
    if not m:
        return mnemonic.upper(), mnemonic.lower(), ""
    initials, surname, sfx = m.groups()
    return initials, surname.lower(), sfx


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    if not FJC_CSV.exists():
        raise SystemExit("sources/fjc-judges.csv missing — download from "
                         "https://www.fjc.gov/sites/default/files/history/judges.csv")
    appointments = fjc_scotus_appointments()
    print(f"FJC SCOTUS appointments: {len(appointments)} "
          f"({len({a['name'] for a in appointments})} people)")

    index = yaml.safe_load((DATA / "justices" / "index.yaml").read_text())
    targets = [j for j in index if "appointed_by" not in j]
    print(f"justices needing enrichment: {len(targets)}")

    curated, unmatched = {}, []
    for j in targets:
        initials, surname, sfx = mechanical_parts(j["scdb_name"])
        first, last = j.get("first_term"), j.get("last_term")
        cands = [a for a in appointments if a["surname"] == surname]
        if len(cands) > 1:
            # initials prefix, then service-era overlap (SCDB terms vs FJC years)
            by_init = [a for a in cands if a["initials"].startswith(initials[0])]
            if by_init:
                cands = by_init
            if len(cands) > 1 and first is not None:
                cands = [a for a in cands
                         if a["start_year"] and a["start_year"] - 2 <= last
                         and a["end_year"] + 2 >= first]
        elevated = None
        if len(cands) > 1 and len({a["name"] for a in cands}) == 1:
            # one person, multiple SCOTUS appointments (associate -> chief):
            # merge into a single service record with an elevation block
            cands = sorted(cands, key=lambda a: a["start_year"] or 0)
            first_a, last_a = cands[0], cands[-1]
            merged = dict(first_a)
            merged["ended"] = last_a["ended"]
            merged["end_reason"] = last_a["end_reason"]
            merged["end_year"] = last_a["end_year"]
            if last_a["position"] == "chief" and first_a["position"] != "chief":
                elevated = {"position": "chief"}
                if last_a["oath"]:
                    elevated["oath"] = last_a["oath"]
                if last_a["appointed_by"]:
                    elevated["appointed_by"] = last_a["appointed_by"]
            cands = [merged]
        if len(cands) != 1:
            unmatched.append({"scdb": j["scdb_name"], "surname": surname,
                              "candidates": len(cands)})
            continue
        a = cands[0]
        entry = {"name": a["name"], "slug": slugify(a["name"]),
                 "position": a["position"], "source": "fjc"}
        for k in ("appointed_by", "party", "oath", "ended", "end_reason",
                  "born", "died"):
            if a.get(k):
                entry[k] = a[k]
        if elevated:
            entry["elevated"] = elevated
        curated[j["scdb_name"]] = entry

    header = ("# GENERATED by pipeline/fjc.py from the FJC Biographical Directory "
              "of Article III Federal Judges\n# (https://www.fjc.gov/history/judges). "
              "Fallback biographies for justices without\n# hand-curated entries; "
              "pipeline/curated/justices.yaml always takes precedence.\n"
              f"# Generated {datetime.date.today().isoformat()}; "
              f"{len(curated)} matched, {len(unmatched)} unmatched.\n\n")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(curated, f, sort_keys=True, allow_unicode=True, width=100)
    print(f"wrote {OUT.relative_to(SOURCES.parent)}: {len(curated)} entries")
    if unmatched:
        print("UNMATCHED (manual review):")
        for u in unmatched:
            print(f"  {u['scdb']} ({u['surname']}): {u['candidates']} candidates")


if __name__ == "__main__":
    main()
