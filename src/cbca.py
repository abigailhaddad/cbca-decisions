"""Parse the Civilian Board of Contract Appeals decision listings (https://www.cbca.gov/decisions/).

The board publishes one HTML page per kind of case. Each page has a table per year; each table row is
one decision: date, case number(s), the party's name linked to the PDF, the judge, and (on the
Contract Disputes Act page since 2015) a type such as Decision or Dismissal.

Nothing is dropped silently. A row that doesn't parse comes back in `problems`. Rows inside HTML
comments are not on the live page and are counted separately (`commented_out`), never parsed.
"""
import html as htmllib
import re
from datetime import datetime
from urllib.parse import quote, urljoin

BASE = "https://www.cbca.gov/decisions/"

# page file -> (case_type label, the heading the page uses for the party column)
PAGES = {
    "cda-cases": "Contract Disputes Act",
    "fcic": "FCIC (crop insurance)",
    "Debt": "Debt",
    "fema": "FEMA arbitration",
    "isda": "ISDA (Indian Self-Determination Act)",
    "rate": "Rate",
    "relocation": "Relocation",
    "travel": "Travel",
}

COMMENT = re.compile(r"<!--.*?-->", re.S)
TABLE = re.compile(r"<table[^>]*>(.*?)</table>", re.S | re.I)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)  # only for counting rows inside comments
ROW_START = re.compile(r"<tr\b[^>]*>", re.I)
CELL_START = re.compile(r"<t([dh])\b[^>]*>", re.I)
CELL_END = re.compile(r"</t[dh]\s*>|</tr\s*>|</tbody\s*>|</thead\s*>", re.I)
HREF = re.compile(r'<a[^>]*href\s*=\s*"([^"]+)"', re.S | re.I)
YEAR = re.compile(r'<h2[^>]*id="(\d{4})"', re.I)


def text(fragment):
    t = htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def iso_date(s):
    s = s.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def dockets(case_number):
    """'CBCA 8250, 8251' -> ['CBCA 8250', 'CBCA 8251']; keeps suffixes like -DBT, -FEMA, -RELO, -R.
    A number with no board prefix gets 'CBCA'. Another prefix as listed (GSBCA, the predecessor board, or
    the listing's one 'CCBCA') is kept as is, not corrected."""
    s = re.sub(r"\s+", " ", case_number).strip()
    if not s:
        return []
    m = re.match(r"^([A-Za-z]+)\s+(?=\d)", s)
    prefix = m.group(1).upper() if m else "CBCA"
    s = s[m.end():] if m else s
    parts = split_outside_parens(s)
    out = []
    for p in parts:
        p = re.sub(r"^[A-Za-z]+\s+(?=\d)", "", p.strip()).strip()
        if p:
            out.append(prefix + " " + p)
    return out


def split_outside_parens(s):
    """Split on , ; & and 'and', but not inside parentheses: 'CBCA 8268-C(7213, 7393)' is one docket."""
    parts, depth, cur, i = [], 0, "", 0
    while i < len(s):
        ch = s[i]
        depth += ch == "("
        depth -= ch == ")" and depth > 0
        if depth == 0:
            m = re.match(r"\s*(?:,|;|&|\band\b)\s*", s[i:])
            if m and m.end() > 0 and (s[i] in ",;&" or m.group(0).strip() == "and"):
                parts.append(cur)
                cur, i = "", i + m.end()
                continue
        cur += ch
        i += 1
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def decision_url(href):
    """Absolute, percent-encoded URL. The site's hrefs contain raw spaces and parentheses."""
    absu = urljoin(BASE, htmllib.unescape(href.strip()))
    return quote(absu, safe=":/%()_-.~,'&+=")


def parse_page(page_html, page):
    """Return (rows, problems, skipped). skipped counts rows inside HTML comments and lists placeholder
    rows ("No Decision") that the site uses for an empty year."""
    commented = sum(len(ROW.findall(c)) for c in COMMENT.findall(page_html) if "<td" in c.lower())
    live = COMMENT.sub("", page_html)
    # remember which year heading precedes each table
    rows, problems, placeholders, merged = [], [], [], []
    pos_years = [(m.start(), m.group(1)) for m in YEAR.finditer(live)]
    for tm in TABLE.finditer(live):
        heading = None
        for p, y in pos_years:
            if p < tm.start():
                heading = y
        header = None
        for cells in split_rows(tm.group(1)):
            if not cells:
                continue
            if all(k.lower() == "h" for k, _ in cells):
                header = [text(c) for _, c in cells]
                continue
            vals = [c for _, c in cells]
            if not any(text(v) for v in vals[:2]) and "no decision" in " ".join(text(v) for v in vals).lower():
                placeholders.append({"page": page, "year_heading": heading, "text": " | ".join(text(v) for v in vals)})
                continue
            # A missing <tr> runs two rows together. Split only when the cell count is an exact multiple of
            # the header width and every chunk starts with a date.
            w = len(header) if header else 0
            chunks = [vals]
            if w and len(vals) > w and len(vals) % w == 0:
                cand = [vals[i:i + w] for i in range(0, len(vals), w)]
                if all(iso_date(text(c[0])) for c in cand):
                    chunks = cand
                    merged.append({"page": page, "year_heading": heading, "rows": len(cand),
                                   "case_numbers": [text(c[1]) for c in cand]})
            for vals in chunks:
                rec = parse_row(vals, header, page, heading)
                if rec is None:
                    problems.append({"page": page, "year_heading": heading, "why": "unexpected cells",
                                     "text": " | ".join(text(v) for v in vals)[:300]})
                    continue
                for why in rec.pop("_problems"):
                    problems.append({"page": page, "year_heading": heading, "why": why,
                                     "case_number": rec["case_number"], "decision_url": rec["decision_url"]})
                rows.append(rec)
    return rows, problems, {"commented_out_rows": commented, "placeholders": placeholders, "merged_rows_split": merged}


def split_rows(table_html):
    """Rows as lists of (kind, cell_html). Tolerates the site's missing </td> and </tr> tags: a row runs to
    the next <tr>, a cell to the next <td>/<th> or closing tag."""
    out = []
    starts = [m.end() for m in ROW_START.finditer(table_html)]
    for i, st in enumerate(starts):
        seg = table_html[st: (starts[i + 1] if i + 1 < len(starts) else len(table_html))]
        seg = re.split(r"</table", seg, flags=re.I)[0]
        cms = list(CELL_START.finditer(seg))
        cells = []
        for j, cm in enumerate(cms):
            body = seg[cm.end(): (cms[j + 1].start() if j + 1 < len(cms) else len(seg))]
            body = CELL_END.split(body)[0]
            cells.append((cm.group(1), body))
        out.append(cells)
    return out


def parse_row(vals, header, page, heading):
    if len(vals) < 4 or len(vals) > 5:
        return None
    hrefs = HREF.findall(vals[2])
    probs = []
    if len(hrefs) != 1:
        # some rows put the link on the case number instead
        alt = [h for v in vals for h in HREF.findall(v)]
        hrefs = alt
        if len(hrefs) != 1:
            probs.append(f"{len(hrefs)} links in row")
    date_raw = text(vals[0])
    rec = {
        "board": "CBCA",
        "case_type": PAGES.get(page, page),
        "listing_page": BASE + page + ".html",
        "year_heading": heading,
        "decision_date_raw": date_raw,
        "decision_date": iso_date(date_raw),
        "case_number": text(vals[1]),
        "party": text(vals[2]),
        "party_role": (header[2] if header and len(header) > 2 else None),
        "judge": text(vals[3]) or None,
        "decision_type": (text(vals[4]) or None) if len(vals) == 5 else None,
        "decision_url": decision_url(hrefs[0]) if hrefs else None,
        "_problems": probs,
    }
    rec["dockets"] = dockets(rec["case_number"])
    rec["docket_count"] = len(rec["dockets"])
    if rec["decision_date"] is None:
        probs.append("unparsed date")
    if not rec["case_number"]:
        probs.append("blank case number")
    return rec


def html_text(page_html):
    """Plain text of an HTML decision page, paragraph breaks kept."""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page_html)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</tr>", "\n", s)
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    return "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in s.splitlines() if ln.strip())


# ---- facts from the decision text -------------------------------------------------------------

def respondent_agency(txt):
    """The respondent named in the caption, e.g. 'DEPARTMENT OF VETERANS AFFAIRS'. Only for cases with a
    respondent (CDA, ISDA, FCIC); travel/relocation claims and FEMA arbitrations have a different caption.
    Returns None when the caption doesn't match; never guesses."""
    head = re.sub(r"[ \t]+", " ", txt[:6000])
    m = re.search(r"\bv\.\s*\n?\s*(.{3,200}?),?\s*\n?\s*Respondents?\b", head, re.S)
    if not m:
        return None
    a = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
    if len(a) > 160 or not re.search(r"[A-Z]{3}", a):
        return None
    return a


def agency_appearing_for(txt):
    """Cases with no respondent in the caption (travel, relocation, FEMA arbitrations) list the government's
    representative as '..., appearing for Department of the Navy.' or '..., counsel for Federal Emergency
    Management Agency.' Returns the first such name that reads as a federal body, or None."""
    head = re.sub(r"\s+", " ", txt[:5000])
    for m in re.finditer(r"\b(?:appearing|counsel) for (?:the )?(.{3,120}?)[.;](?:\s|$)", head):
        a = clean_agency(m.group(1))
        if a:
            return a
    return None


GOV_WORDS = re.compile(r"\b(DEPARTMENT|ADMINISTRATION|AGENCY|COMMISSION|SERVICE|BOARD|OFFICE|CORPORATION|INSTITUTION|"
                       r"BUREAU|AUTHORITY|CORPS|LIBRARY|GALLERY|CENTER|ENDOWMENT|COUNCIL|ARMY|NAVY|AIR FORCE|INSTITUTE|"
                       r"SMITHSONIAN|EXECUTIVE OFFICE|CONGRESS|COURT)\b")
NOT_AGENCY = re.compile(r"\b(LLC|L\.L\.C|INC|LTD|CO\.|COMPANY|TRIBE|APPLICANT|GRANTEE|CLAIMANTS?|APPELLANTS?|PETITIONER)\b|;")


def clean_agency(a):
    """Uppercase, trim a judge's name or footnote marker run onto the end, and return None for anything that
    doesn't read as a federal body (a bare 'Agency', a party name, a fragment of the caption)."""
    if not a:
        return None
    a = re.sub(r"\s+", " ", a).upper().strip()
    a = re.sub(r"\.?\d*\s+[A-Z'’\-]+,\s*(?:CHIEF\s+|VICE CHAIR\s+)?BOARD JUDGE.*$", "", a)
    a = a.strip(" .,")
    if a in ("AGENCY", "THE AGENCY", "RESPONDENT") or NOT_AGENCY.search(a) or not GOV_WORDS.search(a):
        return None
    return a
