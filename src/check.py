"""Second checks on out/decisions.parquet, done a different way from the parser.

    python src/check.py                 # writes out/check.json and checks/sample_<today>.md

1. Row reconciliation per listing page: an independent regex count of decision dates and PDF links in the
   live (uncommented) HTML, against the parsed rows.
2. Whole-table agreement between the listing and the decision PDF: is the listed date the first date in
   the PDF, is the judge's surname in the PDF, is a docket number in the PDF.
3. Counts by fiscal year against the "Resolved" row of the board's own annual reports (FY2024, FY2025).
4. A live sample: 25 random rows plus edge cases. For each, the listing page is fetched again and the row
   holding that PDF link is found by string search, and the PDF is downloaded again. Every field is
   compared and written to checks/sample_<date>.md with links.
"""
import html as htmllib
import json, os, random, re, sys, time
from datetime import date, datetime

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(__file__))
import cbca, crawl

ROOT = os.path.join(os.path.dirname(__file__), "..")
RAW, OUT, CHECKS = f"{ROOT}/raw", f"{ROOT}/out", f"{ROOT}/checks"
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE = re.compile(rf"\b({MONTHS})\s+(\d{{1,2}})\s*,\s*(\d{{4}})")

# Hand-copied from the "Resolved" row of the statistics table in each annual report (page images saved
# in checks/). Columns are the report's case types. https://www.cbca.gov/board/AnnualReport.html
ANNUAL_RESOLVED = {
    "FY2024": {"source": "https://www.cbca.gov/files/2024-CBCA-Annual-Report.pdf (PDF page 7)",
               "ADR": 73, "Appeal": 180, "Debt": 14, "EAJA": 4, "FCIC": 0, "FEMA": 51, "FMCSA": 6, "ISDA": 6,
               "Other": 8, "Petition": 0, "Rate": 1, "RELO": 18, "TRAV": 14, "Total": 375,
               "decision_on_merits": 132, "dismissed_by_decision": 17, "dismissed_voluntary": 153, "interlocutory": 23},
    "FY2025": {"source": "https://www.cbca.gov/files/2025-CBCA-Annual-Report.pdf (PDF page 4)",
               "ADR": 45, "Appeal": 165, "Debt": 9, "EAJA": 2, "FCIC": 0, "FEMA": 56, "FMCSA": 8, "ISDA": 9,
               "Other": 13, "Petition": 1, "Rate": 0, "RELO": 47, "TRAV": 13, "Total": 368,
               "decision_on_merits": 141, "dismissed_by_decision": 19, "dismissed_voluntary": 156, "interlocutory": 16},
}


def docket_kind(d):
    """Map a docket like 'CBCA 8461-RELO' or 'CBCA 7767-R' to the annual report's case type."""
    u = d.upper()
    if re.search(r"\d-?C\s*\(|\d+C$", u):  # EAJA applications: 8268-C(7213), 63C
        return "EAJA"
    for suf, k in (("FEMA", "FEMA"), ("ISDA", "ISDA"), ("RELO", "RELO"), ("TRAV", "TRAV"), ("DBT", "Debt"),
                   ("FCIC", "FCIC"), ("RATE", "Rate"), ("FMCSA", "FMCSA")):
        if suf in u:
            return k
    return "Appeal"


def reconcile_pages(df):
    out = {}
    for page in cbca.PAGES:
        raw = open(f"{RAW}/listings/{page}.html", encoding="utf-8", errors="replace").read()
        live = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
        # a decision date alone in a cell, however the cell is closed
        dates = re.findall(r"<td[^>]*>\s*\d{1,2}/\d{1,2}/\d{2,4}\s*(?=<)", live, flags=re.I)
        pdfs = re.findall(r'href\s*=\s*"[^"]*\.pdf"', live, flags=re.I)
        url = cbca.BASE + page + ".html"
        mine = df[df.listing_page == url]
        out[page] = {"date_cells_in_html": len(dates), "pdf_links_in_html": len(pdfs),
                     "rows_in_table": len(mine), "rows_with_pdf": int(mine.decision_url.notna().sum())}
    return out


def pdf_agreement(df):
    t = df[df.text.notna()].copy()

    def first_date(s):
        m = DATE_RE.search(re.sub(r"\s+", " ", s[:1500]))
        if not m:
            return None
        try:
            return datetime.strptime(" ".join(m.groups()), "%B %d %Y").date().isoformat()
        except ValueError:
            return None

    t["pdf_first_date"] = t.text.map(first_date)
    t["date_match"] = t.pdf_first_date == t.decision_date
    jn = t.judge.fillna("").map(lambda j: re.sub(r"[’']", "'", j).split(",")[0].split()[-1].upper() if j.strip() else "")
    t["judge_in_text"] = [bool(j) and j in re.sub(r"[’']", "'", x).upper() for j, x in zip(jn, t.text)]
    res = {
        "rows_with_text": len(t),
        "listed_date_equals_first_date_in_pdf": int(t.date_match.sum()),
        "no_date_found_in_pdf": int(t.pdf_first_date.isna().sum()),
        "date_differs": int((~t.date_match & t.pdf_first_date.notna()).sum()),
        "judge_surname_in_pdf": int(t.judge_in_text.sum()),
        "judge_blank": int((jn == "").sum()),
        "docket_number_in_pdf": int((t.docket_in_text == True).sum()),
        "date_differs_rows": t[~t.date_match & t.pdf_first_date.notna()][["case_number", "decision_date", "pdf_first_date", "decision_url"]].to_dict("records"),
        "judge_not_in_pdf_rows": t[~t.judge_in_text & (jn != "")][["case_number", "judge", "decision_url"]].to_dict("records"),
        "docket_not_in_pdf_rows": t[t.docket_in_text == False][["case_number", "decision_url"]].to_dict("records"),
    }
    return res


def fiscal_year(d):
    y, m = int(d[:4]), int(d[5:7])
    return y + 1 if m >= 10 else y


def annual(df):
    out = {}
    d = df[df.decision_date.notna()].copy()
    d["fy"] = d.decision_date.map(fiscal_year)
    # count each docket once per fiscal year, whichever page lists it
    d = d.assign(docket=d.dockets.str.split("; ")).explode("docket")
    for fy, ref in ANNUAL_RESOLVED.items():
        y = int(fy[2:])
        g = d[d.fy == y]
        ours = g.drop_duplicates("docket").docket.map(docket_kind).value_counts().to_dict()
        out[fy] = {"listing_rows": int(df[df.decision_date.map(lambda x: bool(x) and fiscal_year(x) == y)].shape[0]),
                   "listing_distinct_dockets": int(g.docket.nunique()),
                   "listing_dockets_by_type": ours, "annual_report_resolved": ref}
    return out


def live_row(page_html, decision_url):
    """Find the <tr> on the live page that links to decision_url, by plain string search on the href."""
    fname = requests.utils.unquote(decision_url.rsplit("/", 1)[-1])
    live = re.sub(r"<!--.*?-->", "", page_html, flags=re.S)
    hits = [m.start() for m in re.finditer(re.escape(fname), live)]
    if not hits:
        hits = [m.start() for m in re.finditer(re.escape(htmllib.escape(fname, quote=False)), live)]
    rows = []
    for i in hits:
        a = live.rfind("<tr", 0, i)
        b = live.find("<tr", i)
        b = len(live) if b < 0 else b
        rows.append(re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " | ", live[a:b]))).replace("\xa0", " "))
    return rows


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[’']", "'", s or "")).strip().lower()


def pick_sample(df, n=25, seed=20261115):
    rnd = df.sample(n=n, random_state=seed)
    seen = set(rnd.id)
    edges = []

    def edge(why, sub, order=None, last=False):
        if order:
            sub = sub.sort_values(order)
        sub = sub[~sub.id.isin(seen)]
        if len(sub):
            r = sub.iloc[-1] if last else sub.iloc[0]
            seen.add(r.id)
            edges.append((why, r))

    dated = df[df.decision_date.notna()]
    edge("oldest", dated, "decision_date")
    edge("newest", dated, "decision_date", last=True)
    edge("most dockets", df, "docket_count", last=True)
    edge("two dockets", df[df.docket_count == 2])
    edge("EAJA docket with a comma inside parentheses", df[df.dockets.str.contains(r"C\(\d+, ", regex=True)])
    edge("predecessor-board (GSBCA) docket", df[df.case_number.str.startswith("GSBCA")])
    edge("no link on listing", df[df.decision_url.isna()])
    edge("link returns 404", df[df.text_status == "HTTP 404"])
    edge("HTML decision, not PDF", df[df.file_format == "html"])
    edge("listed on two pages", df[df.also_listed_on.notna()])
    edge("little or no text (likely scanned)", df[df.text_status == "little or no text (likely scanned)"])
    edge("docket number not in PDF", df[df.docket_in_text == False])
    edge("listed date not in PDF", df[df.date_in_text == False])
    edge("docket number not in file name", df[(df.docket_in_file_name == False) & (df.docket_in_text == True)])
    edge("misspelled type on listing", df[df.decision_type_raw.notna() & (df.decision_type_raw != df.decision_type)])
    edge("no agency found", df[df.agency.isna() & df.text.notna()])
    edge("FEMA arbitration", df[df.case_type == "FEMA arbitration"])
    edge("Rate case", df[df.case_type == "Rate"])
    return [("random", r) for _, r in rnd.iterrows()] + edges


def sample_md(df, sample):
    s = requests.Session()
    pages = {}
    lines, tally = [], {"rows": 0, "listing_fields_ok": 0, "listing_fields": 0, "pdf_checks_ok": 0, "pdf_checks": 0}
    for why, r in sample:
        lp = r.listing_page
        if lp not in pages:
            pages[lp] = crawl.get(lp, s).content.decode("utf-8", errors="replace")
        tally["rows"] += 1
        lines.append(f"### {r.case_number or '(blank)'} ({why})\n")
        lines.append(f"Listing: {lp} · PDF: {r.decision_url or 'none'}\n")
        if r.decision_url:
            found = live_row(pages[lp], r.decision_url)
        else:
            # no link to search by; find the row by case number text
            found = []
            live = re.sub(r"<!--.*?-->", "", pages[lp], flags=re.S)
            for part in live.split("<tr")[1:]:
                tx = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " | ", part)))
                if r.case_number and r.case_number in tx:
                    found.append(tx)
        row_txt = found[0] if found else ""
        lines.append(f"Live listing row ({len(found)} found): `{row_txt.strip(' |')[:400]}`\n")
        lines.append("| field | our value | on live listing row |\n|---|---|---|")
        listed_date = ""
        if r.decision_date:
            y, m, d = r.decision_date.split("-")
            listed_date = f"{int(m)}/{int(d)}/{y}"
        rt = norm(row_txt)
        rt_dates = {datetime.strptime(x, "%m/%d/%Y").date().isoformat() for x in re.findall(r"\d{1,2}/\d{1,2}/\d{4}", row_txt)}
        checks = [("decision_date", r.decision_date, (r.decision_date in rt_dates) if r.decision_date else None),
                  ("case_number", r.case_number, norm(r.case_number) in rt),
                  ("party", r.party, norm(r.party) in rt),
                  ("judge", r.judge, (norm(r.judge) in rt) if r.judge else None),
                  ("decision_type", r.decision_type_raw, (norm(r.decision_type_raw) in rt) if r.decision_type_raw else None)]
        for f, v, ok in checks:
            if ok is None:
                lines.append(f"| {f} | {v or '(blank)'} | n/a (blank) |")
                continue
            tally["listing_fields"] += 1
            tally["listing_fields_ok"] += bool(ok)
            lines.append(f"| {f} | {v} | {'yes' if ok else '**NO**'} |")
        lines.append("")
        if r.decision_url:
            d, t = crawl.fetch_pdf(r.decision_url, s)
            head = re.sub(r"\s+", " ", (t or "")[:700])
            lines.append(f"PDF fetched again: HTTP {d.get('status')}, {d.get('pages')} pages, {d.get('chars')} characters "
                         f"(table: {r.pdf_pages} pages, {r.text_chars} characters).\n")
            lines.append(f"PDF first 700 characters: `{head}`\n")
            pchecks = [("text length equals table", (d.get("chars") == r.text_chars) if r.text_chars is not None else None)]
            if t and t.strip():
                flat = norm(t)
                pchecks += [("a docket number in PDF", any(n in flat for n in re.findall(r"\d{1,5}", r.case_number or ""))),
                            ("judge surname in PDF", (norm(r.judge).split()[-1] in flat) if r.judge else None),
                            ("agency in PDF", (norm(r.agency) in flat) if r.agency else None),
                            ("listed date in PDF", (datetime.fromisoformat(r.decision_date).strftime("%B ") +
                                                    str(int(r.decision_date[8:])) + ", " + r.decision_date[:4]).lower() in flat
                             if r.decision_date else None)]
            lines.append("| PDF check | result |\n|---|---|")
            for f, ok in pchecks:
                if ok is None:
                    lines.append(f"| {f} | n/a |")
                    continue
                tally["pdf_checks"] += 1
                tally["pdf_checks_ok"] += bool(ok)
                lines.append(f"| {f} | {'yes' if ok else '**NO**'} |")
            lines.append(f"\nOur agency: {r.agency or '(none found)'} · text_status: {r.text_status}\n")
        lines.append("")
    return lines, tally


def main():
    df = pd.read_parquet(f"{OUT}/decisions.parquet")
    df["decision_date"] = [d.isoformat() if pd.notna(d) else None for d in df.decision_date]
    df = df.astype(object).where(df.notna(), None)
    rec = reconcile_pages(df)
    agr = pdf_agreement(df)
    ann = annual(df)
    json.dump({"pages": rec, "pdf_agreement": agr, "annual": ann}, open(f"{OUT}/check.json", "w"), indent=1, default=str)
    print(json.dumps(rec, indent=1))
    print({k: v for k, v in agr.items() if not k.endswith("_rows")})
    for fy, a in ann.items():
        print(fy, a["listing_rows"], a["listing_distinct_dockets"], a["listing_dockets_by_type"])
    if "--no-sample" in sys.argv:
        return
    sample = pick_sample(df)
    lines, tally = sample_md(df, sample)
    today = date.today().isoformat()
    head = [f"# Sample check, {today}\n",
            f"Rows checked: {tally['rows']} (25 random, seed 20261115, plus edge cases). Table built from listing pages "
            f"fetched {json.load(open(f'{RAW}/listings/fetched.json'))['cda-cases']['fetched_at']}. Each listing page was fetched "
            f"again for this check and each PDF downloaded again.\n",
            f"Listing fields matching the live row: {tally['listing_fields_ok']} of {tally['listing_fields']}. "
            f"PDF checks passing: {tally['pdf_checks_ok']} of {tally['pdf_checks']}.\n",
            "A **NO** is explained in the README or in the notes at the end of this file.\n"]
    os.makedirs(CHECKS, exist_ok=True)
    open(f"{CHECKS}/sample_{today}.md", "w").write("\n".join(head + lines))
    print(tally)


if __name__ == "__main__":
    main()
