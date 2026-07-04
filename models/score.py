"""Score issued forecasts against decided outcomes.

Forecast files under data/forecasts/ are immutable once issued (the git history
is the preregistration record); this module compares them with decided case
records and writes data/forecasts/scorecard.yaml.

Outcome resolution, strictest source first:
- canonical SCDB record: disposition token in the reverse family vs "affirmed"
- provisional record: decision.winning_party == petitioner as a reversal proxy
  (flagged `basis: winning-party-proxy`); records with neither are unscoreable

Per-justice scoring uses the decided record's in_majority flags: a justice
voted to reverse iff (in majority) == (case reversed).

  .venv/bin/python -m models.score            # score + write scorecard
  .venv/bin/python -m models.score --selftest # exercise the scoring logic
"""

import argparse
import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FORECASTS = ROOT / "data" / "forecasts"
CASES = ROOT / "data" / "cases"

REVERSE_TOKENS = {
    "reversed", "reversed-and-remanded", "vacated-and-remanded", "vacated",
    "affirmed-and-reversed-in-part", "affirmed-and-reversed-in-part-and-remanded",
}
AFFIRM_TOKENS = {"affirmed"}


def outcome_of(case):
    """(reversed: bool, basis: str) or (None, reason)."""
    dec = case.get("decision") or {}
    dispo = dec.get("disposition")
    if isinstance(dispo, str):
        if dispo in REVERSE_TOKENS:
            return True, "scdb-disposition" if not case.get("provisional") else "provisional-disposition"
        if dispo in AFFIRM_TOKENS:
            return False, "scdb-disposition" if not case.get("provisional") else "provisional-disposition"
    winner = dec.get("winning_party")
    if winner == "petitioner":
        return True, "winning-party-proxy"
    if winner == "respondent":
        return False, "winning-party-proxy"
    return None, "no scoreable outcome"


def score_justices(forecast, case, case_reversed):
    """Brier + hits over justices with a decided in_majority flag."""
    actual = {}
    for v in case.get("votes") or []:
        if isinstance(v.get("in_majority"), bool):
            actual[v["justice"]] = v["in_majority"] == case_reversed
    rows, hits, brier = [], 0, 0.0
    for v in forecast.get("votes") or []:
        jn = v["justice"]
        if jn not in actual:
            continue
        y = 1.0 if actual[jn] else 0.0
        p = float(v["p_reverse"])
        rows.append({"justice": jn, "p_reverse": p, "voted_reverse": actual[jn],
                     "hit": (p >= 0.5) == actual[jn]})
        hits += (p >= 0.5) == actual[jn]
        brier += (p - y) ** 2
    if not rows:
        return None
    return {"n": len(rows), "hits": int(hits),
            "brier": round(brier / len(rows), 4), "votes": rows}


def collect():
    scored, unscoreable, pending = [], [], 0
    for tdir in sorted(FORECASTS.iterdir()):
        if not tdir.is_dir():
            continue
        for f in sorted(tdir.glob("*.yaml")):
            fc = yaml.safe_load(f.read_text(encoding="utf-8"))
            decided_path = CASES / str(fc["term"]) / f"{fc['id']}.yaml"
            if not decided_path.exists():
                pending += 1
                continue
            case = yaml.safe_load(decided_path.read_text(encoding="utf-8"))
            reversed_, basis = outcome_of(case)
            if reversed_ is None:
                unscoreable.append({"id": fc["id"], "name": fc["name"], "reason": basis})
                continue
            p = float(fc["prediction"]["p_reverse"])
            y = 1.0 if reversed_ else 0.0
            entry = {
                "id": fc["id"],
                "name": fc["name"],
                "term": fc["term"],
                "forecast_generated": fc.get("generated"),
                "decided": (case.get("dates") or {}).get("decided"),
                "p_reverse": p,
                "outcome": "reversed" if reversed_ else "affirmed",
                "basis": basis,
                "hit": (p >= 0.5) == reversed_,
                "brier": round((p - y) ** 2, 4),
            }
            js = score_justices(fc, case, reversed_)
            if js:
                entry["justice_votes"] = js
            scored.append(entry)
    return scored, unscoreable, pending


def write_scorecard(scored, unscoreable, pending):
    summary = None
    if scored:
        n = len(scored)
        jn = sum(s["justice_votes"]["n"] for s in scored if "justice_votes" in s)
        jh = sum(s["justice_votes"]["hits"] for s in scored if "justice_votes" in s)
        summary = {
            "cases_scored": n,
            "case_accuracy": round(sum(s["hit"] for s in scored) / n, 4),
            "case_brier": round(sum(s["brier"] for s in scored) / n, 4),
            "mean_p_reverse": round(sum(s["p_reverse"] for s in scored) / n, 4),
            "share_reversed": round(
                sum(s["outcome"] == "reversed" for s in scored) / n, 4),
            "justice_votes_scored": jn,
            "justice_vote_accuracy": round(jh / jn, 4) if jn else None,
        }
    payload = {
        "generated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": summary,
        "scored": scored,
        "unscoreable": unscoreable,
        "awaiting_decision": pending,
    }
    with open(FORECASTS / "scorecard.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, width=100)
    return payload


def selftest():
    forecast = {"id": "x", "name": "T v. U", "term": 2025, "generated": "t0",
                "prediction": {"p_reverse": 0.8},
                "votes": [{"justice": "A", "p_reverse": 0.9},
                          {"justice": "B", "p_reverse": 0.3}]}
    decided = {"provisional": True,
               "decision": {"winning_party": "petitioner"},
               "dates": {"decided": "2026-01-01"},
               "votes": [{"justice": "A", "in_majority": True},
                         {"justice": "B", "in_majority": False}]}
    rev, basis = outcome_of(decided)
    assert rev is True and basis == "winning-party-proxy", (rev, basis)
    js = score_justices(forecast, decided, rev)
    # A: in majority of a reversal -> voted reverse, p=.9 hit; B: dissent -> affirm, p=.3 hit
    assert js["n"] == 2 and js["hits"] == 2, js
    canonical = {"decision": {"disposition": "affirmed"}}
    assert outcome_of(canonical) == (False, "scdb-disposition")
    canonical2 = {"decision": {"disposition": "vacated-and-remanded"}}
    assert outcome_of(canonical2) == (True, "scdb-disposition")
    dig = {"decision": {"winning_party_name": "dismissal"}}
    assert outcome_of(dig)[0] is None
    print("selftest: PASS (outcome resolution, proxy basis, per-justice scoring)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    scored, unscoreable, pending = collect()
    payload = write_scorecard(scored, unscoreable, pending)
    if payload["summary"]:
        s = payload["summary"]
        print(f"scored {s['cases_scored']} cases: accuracy {s['case_accuracy']}, "
              f"Brier {s['case_brier']}; justice votes {s['justice_votes_scored']} "
              f"at {s['justice_vote_accuracy']}")
    else:
        print(f"no decided forecasts yet ({pending} awaiting decision, "
              f"{len(unscoreable)} unscoreable); scorecard written")


if __name__ == "__main__":
    main()
