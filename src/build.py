"""raw/ -> out/decisions.parquet and out/report.json.

    python src/build.py

One row per entry on the CBCA listing pages, after removing exact repeats (same page, PDF, case number and
date). The decision text comes from raw/text/, written by crawl.py. Every row the parser couldn't read,
every skipped row and every repeat is written to the report with its reason.

refresh.py uses the same functions (listing_frame, enrich, finish) on live pages.
"""
import hashlib, json, os, re, sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import cbca

ROOT = os.path.join(os.path.dirname(__file__), "..")
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")

COLUMNS = ["id", "board", "case_type", "case_number", "dockets", "docket_count", "party", "party_role", "judge",
           "decision_type", "decision_type_raw", "decision_date", "agency", "agency_source", "decision_url", "file_format",
           "listing_page", "also_listed_on", "pdf_pages", "text_chars", "text_status", "date_in_text", "docket_in_text", "docket_in_file_name",
           "text", "fetched_at"]
ENRICHED = ["file_format", "text", "text_status", "pdf_pages", "text_chars", "fetched_at", "agency", "agency_source", "date_in_text", "docket_in_text"]

TYPE_FIX = {"Decison": "Decision", "Decsion": "Decision"}


def row_id(r):
    k = "|".join([r["listing_page"], r["decision_url"] or "", r["case_number"], r["decision_date"] or ""])
    return hashlib.sha1(k.encode()).hexdigest()[:12]


def docket_numbers(dockets):
    """['CBCA 8250', 'CBCA 7767-R'] -> ['8250', '7767']: the bare numbers, for matching text and file names."""
    return [m.group(1) for d in dockets for m in [re.search(r"(\d{1,5})", d)] if m]


def has_number(nums, s):
    return bool(nums) and any(re.search(rf"(?<!\d){n}(?!\d)", s) for n in nums)


def listing_frame(pages_html):
    """{page: html} -> (DataFrame of listing rows, report pieces)."""
    rows, problems, skipped = [], [], {}
    for page, html in pages_html.items():
        r, p, s = cbca.parse_page(html, page)
        rows += r
        problems += p
        skipped[page] = {"rows_parsed": len(r), "commented_out_rows": s["commented_out_rows"],
                         "placeholders": s["placeholders"], "merged_rows_split": s["merged_rows_split"]}
    for r in rows:
        r["id"] = row_id(r)
        r["dockets"] = "; ".join(r["dockets"])
        nums = docket_numbers(r["dockets"].split("; "))
        r["docket_in_file_name"] = has_number(nums, r["decision_url"].rsplit("/", 1)[-1]) if r["decision_url"] else None
        r["decision_type_raw"] = r["decision_type"]
        r["decision_type"] = TYPE_FIX.get(r["decision_type"], r["decision_type"]) if r["decision_type"] else None
        del r["year_heading"]
    df = pd.DataFrame(rows)
    df = df.astype(object).where(df.notna(), None)
    rep = df[df.duplicated("id", keep="first")]
    repeats = rep[["listing_page", "case_number", "decision_date", "party", "decision_url"]].to_dict("records")
    df = df.drop_duplicates("id", keep="first").reset_index(drop=True)
    return df, {"rows_parsed": len(rows), "exact_repeats_removed": len(repeats), "repeats": repeats,
                "parse_problems": problems, "skipped": skipped}


def also_listed(df):
    pages_by_url = df[df.decision_url.notna()].groupby("decision_url")["listing_page"].agg(lambda s: sorted(set(s)))
    return ["; ".join(p for p in pages_by_url.get(u, []) if p != lp) or None if u else None
            for u, lp in zip(df.decision_url, df.listing_page)]


def enrich_one(decision_url, dockets, d, t, decision_date=None):
    """d: the fetch record for decision_url (crawl.fetch_pdf), t: its text. Returns the ENRICHED fields."""
    out = dict.fromkeys(ENRICHED)
    if not decision_url:
        out["text_status"] = "no link on listing"
        return out
    if not d:
        out["text_status"] = "not fetched"
        return out
    out["fetched_at"] = d.get("fetched_at")
    if d.get("status") != 200:
        out["text_status"] = f"HTTP {d.get('status')}"
        return out
    fmt = d.get("format") or ("pdf" if d.get("is_pdf") else "other")
    if fmt == "other":
        out["text_status"] = "not a PDF or HTML"
        return out
    t = t or ""
    out["pdf_pages"], out["text_chars"], out["file_format"] = d.get("pages"), len(t), fmt
    if d.get("extract_error") and not t.strip():
        out["text_status"] = "extract failed"
    elif len(t.strip()) < 200 and fmt == "pdf":
        out["text_status"] = "little or no text (likely scanned)"
    elif d.get("extract_error"):
        out["text_status"] = "partial (some pages failed)"
    elif d.get("empty_pages") or (d.get("empty_pages") is None and starts_on_later_page(t)):
        # empty_pages is recorded for PDFs fetched after 2026-11-15; for the first crawl, a text that opens
        # with a page-2 running header ("CBCA 8007-RELO 2") means page 1 had no text layer
        out["text_status"] = "partial (a page has no text, likely scanned)"
    else:
        out["text_status"] = "ok"
    out["text"] = t if t.strip() else None
    if t.strip():
        a = cbca.clean_agency(cbca.respondent_agency(t))
        out["agency"], out["agency_source"] = (a, "caption: Respondent") if a else (None, None)
        if not a:
            a = cbca.clean_agency(cbca.agency_appearing_for(t))
            out["agency"], out["agency_source"] = (a, "appearing for / counsel for") if a else (None, None)
    out["date_in_text"] = date_written(decision_date) in re.sub(r"\s+", " ", t[:3000]) if (t.strip() and decision_date) else None
    out["docket_in_text"] = has_number(docket_numbers(dockets.split("; ")), re.sub(r"\s+", " ", t)) if t.strip() else None
    return out


def date_written(iso):
    """'2026-10-16' -> 'October 16, 2026', the way the decisions write it."""
    y, m, d = (int(x) for x in str(iso).split("-"))
    return ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
            "November", "December"][m - 1] + f" {d}, {y}"


def starts_on_later_page(t):
    m = re.match(r"\s*(?:CBCA|GSBCA)\s+[0-9][^\n]{0,80}?\s(\d{1,3})\s*\n", t[:200])
    return bool(m) and m.group(1) != "1"


def enrich(df, lookup):
    """lookup(decision_url) -> (fetch record or None, text or None)."""
    recs = []
    for u, dk, dd in zip(df.decision_url, df.dockets, df.decision_date):
        d, t = lookup(u) if u else (None, None)
        recs.append(enrich_one(u, dk, d, t, dd))
    e = pd.DataFrame(recs, index=df.index)
    for c in ENRICHED:
        df[c] = e[c]
    return df


def finish(df):
    df = df.copy()
    df["also_listed_on"] = also_listed(df)
    for c in ("pdf_pages", "text_chars", "docket_count"):
        df[c] = pd.array(df[c].tolist(), dtype="Int64")
    for c in ("date_in_text", "docket_in_text", "docket_in_file_name"):
        df[c] = pd.array(df[c].tolist(), dtype="boolean")
    # stored as a date; strings and dates (from an earlier upload) both convert
    df["decision_date"] = pd.to_datetime(df["decision_date"].astype("string"), format="%Y-%m-%d", errors="raise").dt.date
    df = df[COLUMNS].sort_values(["decision_date", "case_number", "listing_page"], ascending=[False, True, True],
                                 na_position="last").reset_index(drop=True)
    assert df["id"].is_unique
    return df


def write(df, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_parquet(path, index=False, row_group_size=500)


def summary(df):
    return {
        "rows": len(df),
        "unique_decision_urls": int(df.decision_url.nunique()),
        "rows_by_case_type": df.case_type.value_counts().to_dict(),
        "text_status": df.text_status.value_counts().to_dict(),
        "decision_date_range": [str(df.decision_date.min()), str(df.decision_date.max())],
        "rows_with_agency": int(df.agency.notna().sum()),
        "date_not_in_text": int((df.date_in_text == False).sum()),
        "docket_not_in_text": int((df.docket_in_text == False).sum()),
        "docket_not_in_file_name": int((df.docket_in_file_name == False).sum()),
    }


def load_pdf_log():
    log = {}
    path = f"{RAW}/pdfs.jsonl"
    if os.path.exists(path):
        for line in open(path):
            d = json.loads(line)
            if d["url"] not in log or d.get("status") == 200:
                log[d["url"]] = d
    return log


def build():
    pages = {p: open(f"{RAW}/listings/{p}.html", encoding="utf-8", errors="replace").read() for p in cbca.PAGES}
    df, rep = listing_frame(pages)
    log = load_pdf_log()

    def lookup(u):
        d = log.get(u)
        if d and d.get("text_id") and os.path.exists(f"{RAW}/text/{d['text_id']}.txt"):
            return d, open(f"{RAW}/text/{d['text_id']}.txt", encoding="utf-8").read()
        return d, None

    df = finish(enrich(df, lookup))
    write(df, f"{OUT}/decisions.parquet")
    report = {"listings_fetched": json.load(open(f"{RAW}/listings/fetched.json")), **summary(df), **rep}
    json.dump(report, open(f"{OUT}/report.json", "w"), indent=1, default=str)
    print({k: v for k, v in report.items() if k not in ("parse_problems", "skipped", "repeats", "listings_fetched")})
    return df, report


if __name__ == "__main__":
    build()
