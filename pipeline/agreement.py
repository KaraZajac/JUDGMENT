"""Justice-pair agreement per natural court -> data/aggregates/agreement.yaml.

Agreement = share of cases both justices participated in (majority coded)
where they landed on the same side (both in the majority or both in dissent).
Computed by streaming the justice-centered SCDB files, one case at a time.
"""

import datetime
from collections import defaultdict
from itertools import combinations

import yaml

from .build import DATA, SOURCES, clean, read_rows, to_int


def main():
    manifest = yaml.safe_load((SOURCES / "manifest.yaml").read_text())
    files = manifest["files"]

    pair = defaultdict(lambda: [0, 0])  # (nc, j1, j2) -> [agreements, both]
    members = defaultdict(set)          # nc -> justice mnemonics
    jid = {}                            # mnemonic -> scdb id (for stable ordering)

    def flush(nc, rows):
        if nc is None or len(rows) < 2:
            return
        for (a, ma), (b, mb) in combinations(sorted(rows), 2):
            cell = pair[(nc, a, b)]
            cell[1] += 1
            cell[0] += ma == mb

    for fn in (files["modern_justice"], files["legacy_justice"]):
        current_case, current_nc, rows = None, None, []
        for row in read_rows(fn):
            cid = clean(row.get("caseId"))
            if not cid:
                continue
            if to_int(row.get("justice")) == -99:
                continue
            if cid != current_case:
                flush(current_nc, rows)
                current_case, rows = cid, []
                current_nc = to_int(row.get("naturalCourt"))
            jname = clean(row.get("justiceName"))
            maj = to_int(row.get("majority"))
            if jname is None or maj not in (1, 2):
                continue
            members[current_nc].add(jname)
            j = to_int(row.get("justice"))
            if j is not None:
                jid[jname] = j
            rows.append((jname, maj))
        flush(current_nc, rows)

    courts = {}
    for nc in sorted(members):
        js = sorted(members[nc], key=lambda m: jid.get(m, 10 ** 6))
        pairs = {}
        for a, b in combinations(sorted(js), 2):
            agree, both = pair.get((nc, a, b), (0, 0))
            if both >= 5:  # too little co-participation is noise, not signal
                pairs[f"{a}|{b}"] = {"rate": round(agree / both, 3), "n": both}
        if pairs:
            courts[nc] = {"justices": js, "pairs": pairs}

    dest = DATA / "aggregates"
    dest.mkdir(exist_ok=True)
    payload = {
        "generated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "definition": "share of co-heard cases (majority coded for both) where the "
                      "pair landed on the same side; pairs with n < 5 omitted",
        "courts": courts,
    }
    with open(dest / "agreement.yaml", "w", encoding="utf-8") as f:
        yaml.dump(payload, f, sort_keys=False, width=110)
    n_pairs = sum(len(c["pairs"]) for c in courts.values())
    print(f"wrote data/aggregates/agreement.yaml "
          f"({len(courts)} natural courts, {n_pairs:,} justice pairs)")


if __name__ == "__main__":
    main()
