"""Same-day votes from the primary source: slip-opinion syllabi.

Oyez's structured vote coding lags decisions by days-to-weeks; the Court's own
slip opinions are public within minutes and their syllabi end with a canonical
lineup paragraph ("ALITO, J., delivered the opinion of the Court, in which
ROBERTS, C. J., and THOMAS ... JJ., joined. ..."). This module:

1. parses the term's slip-opinion index (docket, decision date, case name,
   majority-author initials, U.S. Reports citation, PDF link),
2. extracts each syllabus's lineup paragraph via pdftotext and derives
   per-justice votes (majority / concurrences / dissents / non-participation),
3. VALIDATES itself against every provisional case that already has
   Oyez-coded votes, and only if the parser clears the accuracy gate does it
   write votes into vote-less provisional records (flagged
   vote_source: slip-opinion-syllabus).

SCDB coding supersedes all of this at the annual release, as usual.

  python3 -m pipeline.syllabus --term 2025            # validate + fill
  python3 -m pipeline.syllabus --term 2025 --dry-run  # report only
"""

import argparse
import re
import shutil
import subprocess
import urllib.request

import yaml

from .build import DATA, SOURCES, dump_yaml, put
from .interim import BROWSER_UA, docket_slug

CACHE = SOURCES / "interim"

SURNAME_MNEMONIC = {
    "ROBERTS": "JGRoberts", "THOMAS": "CThomas", "ALITO": "SAAlito",
    "SOTOMAYOR": "SSotomayor", "KAGAN": "EKagan", "GORSUCH": "NMGorsuch",
    "KAVANAUGH": "BMKavanaugh", "BARRETT": "ACBarrett", "JACKSON": "KBJackson",
}
# slip opinions print surnames ALL-CAPS; preliminary-print U.S. Reports
# proofs (which replace slips on the index) use title case — match both
SURNAMES = "|".join(list(SURNAME_MNEMONIC) +
                    [s.title() for s in SURNAME_MNEMONIC])

AUTHOR_INITIALS = {
    "R": "JGRoberts", "T": "CThomas", "A": "SAAlito", "SS": "SSotomayor",
    "K": "EKagan", "G": "NMGorsuch", "BK": "BMKavanaugh", "ACB": "ACBarrett",
    "KJ": "KBJackson", "JJ": "KBJackson",
}

VALIDATION_GATE = 0.90  # exact-lineup agreement with Oyez required to write

# consolidated decisions carry a first-page syllabus footnote — "*Together
# with No. 24–38, Little et al. v. Hecox et al., on certiorari to ..." — one
# "No. <docket>" (or "and <docket>") per companion resolved by the opinion
TOGETHER_WITH_RE = re.compile(r"Together with No", re.I)
COMPANION_DOCKET_RE = re.compile(r"(?:Nos?\.|and|&)\s*\b(\d{1,2}\s*[-–—]\s*\d{1,6})\b")


def consolidated_companions(text, lead_docket):
    """Companion docket numbers decided by this opinion (empty if none).

    Only the slip index's lead docket gets a row; Oyez likewise keeps
    companion dockets 'pending' indefinitely, so this footnote is the one
    same-day source tying a companion to the deciding record."""
    m = TOGETHER_WITH_RE.search(text)
    if not m:
        return []
    window = text[m.start():m.start() + 600]
    window = window.split("\f", 1)[0]  # footnote ends with page 1
    lead = docket_slug(lead_docket)
    out = []
    for tok in COMPANION_DOCKET_RE.findall(window):
        d = re.sub(r"\s+", "", tok).replace("–", "-").replace("—", "-")
        if docket_slug(d) != lead and d not in out:
            out.append(d)
    return out


def fetch(url, cache_name, binary=False):
    path = CACHE / cache_name
    if path.exists():
        return path.read_bytes() if binary else path.read_text(encoding="utf-8",
                                                               errors="replace")
    import time
    from urllib.error import HTTPError, URLError
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    for attempt, backoff in enumerate((2, 5, 10), start=1):  # transient-flake retry
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = resp.read()
            break
        except (HTTPError, URLError, TimeoutError) as e:
            if (isinstance(e, HTTPError) and e.code == 404) or attempt == 3:
                raise
            time.sleep(backoff)
    path.write_bytes(payload)
    time.sleep(0.4)
    return payload if binary else payload.decode("utf-8", errors="replace")


def slip_index(term_code):
    """Rows of the slip-opinion index for a term (e.g. term_code '25')."""
    html = fetch(f"https://www.supremecourt.gov/opinions/slipopinion/{term_code}",
                 f"slip-index-{term_code}.html")
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        m = re.search(
            r"nowrap;?\">\s*([\dA-Za-z ,.-]+?)\s*</td>\s*"
            r"<td>\s*<a href='(/opinions/\d+pdf/[^']+)'[^>]*>(.*?)</a>.*?</td>.*?"
            r"center;\">\s*([A-Z]{1,3}|PC|D)\s*</td>",
            tr, re.S)
        if not m:
            continue
        docket, pdf, name, author = m.groups()
        date_m = re.search(r"center;\">(\d{1,2}/\d{1,2}/\d{2})</td>", tr)
        cite_m = re.search(r"(\d+ U\. ?S\. [\d_]+)", tr)
        rows.append({
            "docket": docket.strip(),
            "pdf": "https://www.supremecourt.gov" + pdf,
            "name": re.sub(r"<[^>]+>", "", name).strip(),
            "author_initials": author.strip(),
            "date": date_m.group(1) if date_m else None,
            "us_cite": cite_m.group(1).replace("U. S.", "U.S.") if cite_m else None,
        })
    return rows


def syllabus_text(row):
    pdf_bytes = fetch(row["pdf"], f"slip-{docket_slug(row['docket'])}.pdf", binary=True)
    tmp = CACHE / f"slip-{docket_slug(row['docket'])}.pdf"
    out = subprocess.run(["pdftotext", "-l", "8", str(tmp), "-"],
                         capture_output=True, text=True, timeout=60)
    return out.stdout


def parse_lineup(text):
    """Syllabus lineup paragraph -> {mnemonic: vote entry}, author mnemonic."""
    # isolate from the first 'delivered/announced' sentence to the end marker
    start = re.search(
        r"([A-Z][A-Za-z]+),\s*(?:C\.?\s*J\.?|J\.?)\s*,?\s*(delivered the opinion "
        r"(?:of the Court|for a unanimous Court)"
        r"|announced the judgment of the Court)", text)
    per_curiam = re.search(r"per curiam", text, re.I) and not start
    votes, author = {}, None

    def entry(mn):
        return votes.setdefault(mn, {"justice": mn})

    if start:
        author = SURNAME_MNEMONIC.get(start.group(1).upper())
        if author:
            e = entry(author)
            e["vote"] = ("majority" if "delivered" in start.group(2)
                         else "judgment-of-the-court")
            e["opinion"] = "wrote"
            e["in_majority"] = True
        # unanimous phrasings carry no joiner list — everyone joins
        head = text[start.start():start.start() + 300]
        if "unanimous Court" in start.group(2) or "unanimous Court" in head \
                or "all other Members joined" in head:
            for mn in SURNAME_MNEMONIC.values():
                if mn != author:
                    e2 = entry(mn)
                    e2.setdefault("vote", "majority")
                    e2["in_majority"] = True
                    if author:
                        e2.setdefault("joined", [author])

    # sentence-level classification over the whole lineup region. The syllabus
    # is saturated with "C. J.", "J.,", "JJ." title abbreviations whose periods
    # shred naive sentence-splitting mid-lineup — strip those periods first so
    # only real sentence boundaries remain.
    # bound the region to the lineup paragraph itself (< ~800 chars) so party
    # names and counsel listings further down can't masquerade as justices
    region = text[start.start():start.start() + 1400] if start else text[:4000]
    region = region.replace("\n", " ")
    # preliminary prints use an fi ligature that pdftotext mangles: "filed" -> "fled"
    region = re.sub(r"\bfled (a|an)\b", r"filed \1", region)
    # strip ONLY justice-title periods (J. / JJ. / C. J.) — a blanket
    # single-capital rule also eats "Part I." and merges lineup sentences
    region = re.sub(r"\bC\.\s*J\.(?=[,\s])", "CJ", region)
    region = re.sub(r"\bJJ\.(?=[,\s])", "JJ", region)
    region = re.sub(r"\bJ\.(?=[,\s])", "J", region)
    # preliminary prints chain the whole lineup with semicolons — treat them
    # as clause boundaries so dissents don't get absorbed by the first clause
    sentences = re.split(r"(?<=[.;])\s+(?=[A-Z])", region)
    for s in sentences[:40]:
        names = [SURNAME_MNEMONIC[n.upper()] for n in re.findall(SURNAMES, s)]
        if not names:
            continue
        low = s.lower()
        if "took no part" in low:
            for mn in names:
                votes[mn] = {"justice": mn, "participated": False}
        elif "delivered the opinion" in low or "announced the judgment" in low:
            joiners = names[1:] if author and names and names[0] == author else names
            for mn in joiners:
                if mn == author:
                    continue
                e = entry(mn)
                e.setdefault("vote", "majority")
                e["in_majority"] = True
                if author:
                    e.setdefault("joined", [author])
        elif "concurring in the judgment" in low and "dissenting in part" in low:
            # hybrid vote: concurs in the judgment -> majority side for outcome
            filer = names[0]
            e = entry(filer)
            e["vote"] = "special-concurrence"
            e["opinion"] = "wrote"
            e["in_majority"] = True
        elif "dissenting" in low and "filed" in low:
            filer = names[0]
            e = entry(filer)
            e["vote"] = "dissent"
            e["opinion"] = "co-wrote" if e.get("opinion") else "wrote"
            e["in_majority"] = False
            for mn in names[1:]:
                e2 = entry(mn)
                e2["vote"] = "dissent"
                e2["in_majority"] = False
                e2.setdefault("joined", []).append(filer)
        elif "concurring in the judgment" in low and "filed" in low:
            filer = names[0]
            e = entry(filer)
            if e.get("vote") != "dissent":
                e["vote"] = "special-concurrence"
                e["opinion"] = "wrote"
                e["in_majority"] = True
            for mn in names[1:]:
                e2 = entry(mn)
                if e2.get("vote") != "dissent":
                    e2.setdefault("vote", "special-concurrence")
                    e2["in_majority"] = True
                    e2.setdefault("joined", []).append(filer)
        elif "concurring opinion" in low and "filed" in low:
            filer = names[0]
            e = entry(filer)
            if e.get("in_majority") is not False:
                e["vote"] = "regular-concurrence"
                e["opinion"] = "wrote"
                e["in_majority"] = True
    return votes, author, bool(per_curiam)


def complete_votes(votes, author, pc):
    """Unlisted sitting justices joined the majority silently (authored
    opinions list dissents/concurrences explicitly; per curiams list only
    the exceptions)."""
    out = {k: dict(v) for k, v in votes.items()}
    if pc or author:
        for mn in SURNAME_MNEMONIC.values():
            if mn not in out:
                out[mn] = {"justice": mn, "vote": "majority", "in_majority": True}
    return out


def load_provisional(term):
    tdir = DATA / "cases" / str(term)
    out = {}
    for f in sorted(tdir.glob("*.yaml")):
        c = yaml.safe_load(f.read_text(encoding="utf-8"))
        if c.get("provisional"):
            out[docket_slug(c.get("docket") or "")] = (f, c)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--term", type=int, default=None,
                    help="defaults to the first term beyond SCDB coverage")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # A missing binary is an environment error, not a validation disagreement.
    # Failing here (loudly, nonzero) aborts the calling workflow BEFORE its
    # commit step, so an upstream interim/build rebuild cannot ship voteless
    # records. (2026-07-06: refresh ran without poppler-utils — every parse
    # crashed FileNotFoundError, validation read 0/0, the gate refused to
    # write, and the wipe was committed anyway.)
    if shutil.which("pdftotext") is None:
        raise SystemExit("pipeline.syllabus: pdftotext not found — install "
                         "poppler-utils; refusing to run against a wiped tree")
    if args.term is None:
        meta = yaml.safe_load((DATA / "meta.yaml").read_text())
        args.term = meta["counts"]["last_term"] + 1
    term_code = str(args.term)[-2:]

    rows = slip_index(term_code)
    print(f"slip index OT{term_code}: {len(rows)} decisions")
    provisional = load_provisional(args.term)

    # ---- validation against Oyez-coded cases --------------------------------
    checked = agree = author_agree = 0
    disagreements = []
    parsed_cache = {}
    for row in rows:
        key = docket_slug(row["docket"])
        if key not in provisional:
            continue
        _, case = provisional[key]
        try:
            votes, author, pc = parse_lineup(syllabus_text(row))
        except Exception as e:
            disagreements.append((row["docket"], f"parse-crash {type(e).__name__}"))
            continue
        parsed_cache[key] = (votes, author, pc, row)
        if str(case.get("vote_source", "")).startswith("slip-opinion"):
            continue  # never validate the parser against its own prior output
        oyez_votes = {v["justice"]: v for v in case.get("votes") or []
                      if "in_majority" in v}
        if not oyez_votes:
            continue
        checked += 1
        ours = {j: v.get("in_majority")
                for j, v in complete_votes(votes, author, pc).items()
                if "in_majority" in v}
        theirs = {j: v["in_majority"] for j, v in oyez_votes.items()}
        common = set(ours) & set(theirs)
        if common and all(ours[j] == theirs[j] for j in common) \
                and len(common) >= len(theirs) - 1:
            agree += 1
        else:
            diff = {j: (ours.get(j), theirs.get(j))
                    for j in set(ours) | set(theirs)
                    if ours.get(j) != theirs.get(j)}
            disagreements.append((row["docket"], f"lineup {diff}"))
        oyez_author = (case.get("opinions") or {}).get("majority_author")
        idx_author = AUTHOR_INITIALS.get(row["author_initials"])
        if oyez_author and idx_author:
            author_agree += oyez_author == idx_author

    rate = agree / checked if checked else 0.0
    print(f"validation vs Oyez: lineup {agree}/{checked} ({rate:.0%}), "
          f"author-initials {author_agree}/{checked}")
    for d, why in disagreements[:6]:
        print(f"  disagreement {d}: {why[:130]}")

    if rate < VALIDATION_GATE:
        print(f"below gate ({VALIDATION_GATE:.0%}) — not writing votes")
        return

    # ---- fill vote-less provisional cases -----------------------------------
    filled = 0
    term_map = {}  # companion docket slug -> deciding case id
    for row in rows:
        key = docket_slug(row["docket"])
        if key not in provisional:
            continue
        path, case = provisional[key]
        try:
            companions = consolidated_companions(syllabus_text(row), row["docket"])
        except Exception:
            companions = []
        dirty = False
        if companions:
            term_map.update({docket_slug(c): case["id"] for c in companions})
            if case.get("consolidated_dockets") != companions:
                case["consolidated_dockets"] = companions
                dirty = True
        own_fill = str(case.get("vote_source", "")).startswith("slip-opinion")
        if case.get("votes") and not own_fill:
            # Oyez-coded votes stay authoritative; still take the citation upgrade
            if row["us_cite"] and not (case.get("citation") or {}).get("us"):
                case.setdefault("citation", {})["us"] = row["us_cite"]
                dirty = True
            if dirty and not args.dry_run:
                dump_yaml(case, path)
            continue
        if own_fill:  # re-parse: parser fixes overwrite the parser's own output
            case.pop("votes", None)
            for k in ("majority_votes", "minority_votes"):
                (case.get("decision") or {}).pop(k, None)
        if key not in parsed_cache:
            try:
                parsed_cache[key] = (*parse_lineup(syllabus_text(row)), row)
            except Exception:
                if dirty and not args.dry_run:
                    dump_yaml(case, path)
                continue
        votes, author, pc, _ = parsed_cache[key]
        author = author or AUTHOR_INITIALS.get(row["author_initials"])
        if not votes and not pc:
            if dirty and not args.dry_run:
                dump_yaml(case, path)
            continue
        vote_list = list(complete_votes(votes, author, pc).values())
        maj = sum(1 for v in vote_list if v.get("in_majority") is True)
        mnr = sum(1 for v in vote_list if v.get("in_majority") is False)
        case["votes"] = vote_list
        case["vote_source"] = "slip-opinion-syllabus (parsed; SCDB supersedes)"
        if author:
            case.setdefault("opinions", {})["majority_author"] = author
        dec = case.setdefault("decision", {})
        dec.setdefault("majority_votes", maj)
        dec.setdefault("minority_votes", mnr)
        if pc:
            dec.setdefault("type", "per-curiam-no-argument"
                           if not (case.get("dates") or {}).get("argued")
                           else "per-curiam-argued")
        if row["us_cite"]:
            case.setdefault("citation", {}).setdefault("us", row["us_cite"])
        if "supremecourt.gov" not in case.get("sources", []):
            case.setdefault("sources", []).append("supremecourt.gov")
        filled += 1
        if not args.dry_run:
            dump_yaml(case, path)
        print(f"  filled {case['id']}: {maj}-{mnr}"
              f"{' per curiam' if pc else ''} "
              f"(author {author or '—'}) {case['name'][:40]}")

    # persist companion resolution: pipeline.interim prunes these dockets from
    # the pending list; models.score resolves their forecasts to the deciding
    # record. Lives outside data/cases/ so build/interim rebuilds keep it.
    if term_map:
        cpath = DATA / "consolidations.yaml"
        cmap = (yaml.safe_load(cpath.read_text(encoding="utf-8")) or {}
                if cpath.exists() else {})
        merged = {**(cmap.get(args.term) or {}), **term_map}
        if merged != cmap.get(args.term):
            cmap[args.term] = dict(sorted(merged.items()))
            if not args.dry_run:
                cpath.write_text(
                    "# Companion dockets resolved by a consolidated opinion,\n"
                    "# per term: <companion docket slug>: <deciding case id>.\n"
                    "# Written by pipeline.syllabus (syllabus 'Together with'\n"
                    "# footnotes); read by pipeline.interim and models.score.\n"
                    + yaml.safe_dump(cmap, sort_keys=True, width=100),
                    encoding="utf-8")
        for d, lead in sorted(term_map.items()):
            print(f"  consolidated: {d} decided under {lead}")

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}filled {filled} cases")


if __name__ == "__main__":
    main()
