"""Structural validation of the generated dataset.

Hard errors (exit 1): unparseable YAML, id/filename mismatches, votes referencing
unknown justices, malformed vote tokens, index/file drift.

Soft findings (reported, non-fatal): vote tallies that disagree with SCDB's
majVotes/minVotes, decision dates far from the term year, majority authors not
among the recorded voters. Some disagreement is expected — SCDB itself carries
coding quirks — the point is to know the rates.
"""

import sys
from collections import Counter
from pathlib import Path

import yaml

from . import codes

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def main():
    hard = []
    soft = Counter()

    index = yaml.load((DATA / "justices" / "index.yaml").read_text(encoding="utf-8"),
                      Loader=Loader)
    known = {j["scdb_name"] for j in index}
    slugs = {j["slug"] for j in index}
    jfiles = {p.stem for p in (DATA / "justices").glob("*.yaml")} - {"index"}
    if jfiles != slugs:
        hard.append(f"justices index/files drift: {sorted(jfiles ^ slugs)[:10]}")

    vote_tokens = {t for t, _ in codes.VOTE.values()}
    files = sorted((DATA / "cases").glob("*/*.yaml"))
    print(f"validating {len(files):,} case files ...")
    n_votes = 0

    for i, path in enumerate(files, 1):
        case = yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)
        if case.get("id") != path.stem:
            hard.append(f"{path}: id != filename")
            continue
        if str(case.get("term")) != path.parent.name:
            hard.append(f"{path}: term {case.get('term')} != folder {path.parent.name}")
        if not case.get("name"):
            soft["case without a name"] += 1

        votes = case.get("votes") or []
        n_votes += len(votes)
        for v in votes:
            if v.get("justice") not in known:
                hard.append(f"{path}: unknown justice {v.get('justice')!r}")
            tok = v.get("vote")
            if tok is not None and tok not in vote_tokens and not isinstance(tok, int):
                hard.append(f"{path}: malformed vote token {tok!r}")
        if not votes:
            soft["case without vote records"] += 1

        dec = case.get("decision") or {}
        if votes and isinstance(dec.get("majority_votes"), int):
            maj = sum(1 for v in votes if v.get("in_majority") is True)
            mnr = sum(1 for v in votes if v.get("in_majority") is False)
            if maj != dec["majority_votes"]:
                soft["in_majority tally != majority_votes"] += 1
            if isinstance(dec.get("minority_votes"), int) and mnr != dec["minority_votes"]:
                soft["dissent tally != minority_votes"] += 1

        decided = (case.get("dates") or {}).get("decided")
        term = case.get("term")
        if decided and isinstance(term, int):
            year = int(decided[:4])
            if not (term - 1 <= year <= term + 2):
                soft["decided year far from term"] += 1

        author = (case.get("opinions") or {}).get("majority_author")
        if isinstance(author, str) and votes and \
                author not in {v.get("justice") for v in votes}:
            soft["majority author not among voters"] += 1

        if i % 5000 == 0:
            print(f"  ... {i:,}")
        if len(hard) > 50:
            print("  aborting: too many hard errors")
            break

    print(f"\ncases: {len(files):,}   vote records: {n_votes:,}   justices: {len(known)}")
    if soft:
        print("soft findings (informational):")
        for k, v in soft.most_common():
            print(f"  {k}: {v:,} ({v / len(files):.2%})")
    if hard:
        print(f"\nHARD ERRORS ({len(hard)}), first 20:")
        for h in hard[:20]:
            print(" ", h)
        sys.exit(1)
    print("no hard errors.")


if __name__ == "__main__":
    main()
