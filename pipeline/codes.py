"""SCDB code -> (token, label) tables.

Only closed, fully-enumerated SCDB code sets are decoded here ("complete decode"
fields in docs/data-model.md). Open-ended code sets (issue, parties, courts,
lawSupp) stay as raw numeric codes in the YAML.

Tokens are stable kebab-case identifiers used throughout data/; labels are the
SCDB codebook's prose. Source: http://scdb.wustl.edu/documentation.php
"""

DECISION_TYPE = {
    1: ("opinion-of-the-court", "opinion of the court (orally argued)"),
    2: ("per-curiam-no-argument", "per curiam (no oral argument)"),
    3: ("memorandum", "memorandum decision"),
    4: ("decree", "decree"),
    5: ("equally-divided", "equally divided vote"),
    6: ("per-curiam-argued", "per curiam (orally argued)"),
    7: ("judgment-of-the-court", "judgment of the Court"),
    8: ("seriatim", "seriatim opinions (each justice delivering an individual "
        "opinion; pre-Marshall era)"),
}

CASE_DISPOSITION = {
    1: ("granted", "stay, petition, or motion granted"),
    2: ("affirmed", "affirmed"),
    3: ("reversed", "reversed"),
    4: ("reversed-and-remanded", "reversed and remanded"),
    5: ("vacated-and-remanded", "vacated and remanded"),
    6: ("affirmed-and-reversed-in-part", "affirmed and reversed (or vacated) in part"),
    7: ("affirmed-and-reversed-in-part-and-remanded",
        "affirmed and reversed (or vacated) in part and remanded"),
    8: ("vacated", "vacated"),
    9: ("petition-denied", "petition denied or appeal dismissed"),
    10: ("certification", "certification to or from a lower court"),
    11: ("no-disposition", "no disposition"),
}

LC_DISPOSITION = {
    1: ("granted", "stay, petition, or motion granted"),
    2: ("affirmed", "affirmed"),
    3: ("reversed", "reversed"),
    4: ("reversed-and-remanded", "reversed and remanded"),
    5: ("vacated-and-remanded", "vacated and remanded"),
    6: ("affirmed-and-reversed-in-part", "affirmed and reversed (or vacated) in part"),
    7: ("affirmed-and-reversed-in-part-and-remanded",
        "affirmed and reversed (or vacated) in part and remanded"),
    8: ("vacated", "vacated"),
    9: ("petition-denied", "petition denied or appeal dismissed"),
    10: ("modified", "modified"),
    11: ("remanded", "remanded"),
    12: ("unusual-disposition", "unusual disposition"),
}

DECISION_DIRECTION = {
    1: ("conservative", "conservative"),
    2: ("liberal", "liberal"),
    3: ("unspecifiable", "unspecifiable"),
}

VOTE_DIRECTION = {
    1: ("conservative", "conservative"),
    2: ("liberal", "liberal"),
}

PARTY_WINNING = {
    0: ("respondent", "no favorable disposition for petitioning party apparent"),
    1: ("petitioner", "petitioning party received a favorable disposition"),
    2: ("unclear", "favorable disposition for petitioning party unclear"),
}

DECLARATION_UNCON = {
    1: ("none", "no unconstitutionality declared"),
    2: ("federal-statute", "act of Congress declared unconstitutional"),
    3: ("state-law", "state or territorial law, regulation, or constitutional "
        "provision declared unconstitutional"),
    4: ("local-ordinance", "municipal or other local ordinance declared unconstitutional"),
}

CERT_REASON = {
    1: ("not-cert", "case did not arise on cert or cert not granted"),
    2: ("federal-court-conflict", "federal court conflict"),
    3: ("federal-conflict-and-important-question",
        "federal court conflict and to resolve important or significant question"),
    4: ("putative-conflict", "putative conflict"),
    5: ("federal-state-conflict", "conflict between federal court and state court"),
    6: ("state-court-conflict", "state court conflict"),
    7: ("federal-court-confusion", "federal court confusion or uncertainty"),
    8: ("state-court-confusion", "state court confusion or uncertainty"),
    9: ("federal-and-state-confusion",
        "federal court and state court confusion or uncertainty"),
    10: ("to-resolve-important-question", "to resolve important or significant question"),
    11: ("to-resolve-question-presented", "to resolve question presented"),
    12: ("no-reason-given", "no reason given"),
    13: ("other-reason", "other reason"),
}

AUTHORITY = {
    1: ("judicial-review-national", "judicial review (national level)"),
    2: ("judicial-review-state", "judicial review (state level)"),
    3: ("supervisory", "Supreme Court supervision of lower federal or state courts "
        "or original jurisdiction"),
    4: ("statutory-construction", "statutory construction"),
    5: ("administrative-interpretation", "interpretation of administrative "
        "regulation or rule, or executive order"),
    6: ("diversity-jurisdiction", "diversity jurisdiction"),
    7: ("federal-common-law", "federal common law"),
}

LAW_TYPE = {
    1: ("constitution", "Constitution"),
    2: ("constitutional-amendment", "constitutional amendment"),
    3: ("federal-statute", "federal statute"),
    4: ("court-rules", "court rules"),
    5: ("other", "other"),
    6: ("infrequent-federal-statute", "infrequently litigated federal statute"),
    8: ("state-or-local-law", "state or local law or regulation"),
    9: ("no-legal-provision", "no legal provision"),
}

ISSUE_AREA = {
    1: ("criminal-procedure", "Criminal Procedure"),
    2: ("civil-rights", "Civil Rights"),
    3: ("first-amendment", "First Amendment"),
    4: ("due-process", "Due Process"),
    5: ("privacy", "Privacy"),
    6: ("attorneys", "Attorneys"),
    7: ("unions", "Unions"),
    8: ("economic-activity", "Economic Activity"),
    9: ("judicial-power", "Judicial Power"),
    10: ("federalism", "Federalism"),
    11: ("interstate-relations", "Interstate Relations"),
    12: ("federal-taxation", "Federal Taxation"),
    13: ("miscellaneous", "Miscellaneous"),
    14: ("private-action", "Private Action"),
}

VOTE = {
    1: ("majority", "voted with majority or plurality"),
    2: ("dissent", "dissent"),
    3: ("regular-concurrence", "regular concurrence (joins the majority opinion)"),
    4: ("special-concurrence", "special concurrence (concurs in result, not in the "
        "majority opinion)"),
    5: ("judgment-of-the-court", "judgment of the Court"),
    6: ("dissent-from-cert-denial", "dissent from the denial or dismissal of "
        "certiorari or appeal"),
    7: ("jurisdictional-dissent", "jurisdictional dissent"),
    8: ("equally-divided", "participation in an equally divided vote"),
}

OPINION = {
    1: ("none", "no opinion written"),
    2: ("wrote", "wrote an opinion"),
    3: ("co-wrote", "co-authored an opinion"),
}

MAJORITY = {
    1: ("dissent", "voted with the dissent"),
    2: ("majority", "voted with the majority"),
}

# Partial map: only the overwhelmingly common jurisdiction codes are labeled;
# other codes pass through raw (see data/codebook/README.md).
JURISDICTION_PARTIAL = {
    1: ("certiorari", "petition for a writ of certiorari"),
    2: ("appeal", "appeal"),
    4: ("certification", "certification"),
    9: ("original", "original jurisdiction"),
}

# Emitted to data/codebook/<name>.yaml by pipeline.build.
CODEBOOK_EXPORTS = {
    "decision-type": DECISION_TYPE,
    "case-disposition": CASE_DISPOSITION,
    "lower-court-disposition": LC_DISPOSITION,
    "decision-direction": DECISION_DIRECTION,
    "vote-direction": VOTE_DIRECTION,
    "party-winning": PARTY_WINNING,
    "declaration-unconstitutional": DECLARATION_UNCON,
    "cert-reason": CERT_REASON,
    "authority": AUTHORITY,
    "law-type": LAW_TYPE,
    "issue-area": ISSUE_AREA,
    "vote": VOTE,
    "opinion": OPINION,
    "majority": MAJORITY,
    "jurisdiction-partial": JURISDICTION_PARTIAL,
}


def token(table, code):
    """kebab-case token for a code, or None when unmapped/missing."""
    entry = table.get(code)
    return entry[0] if entry else None
