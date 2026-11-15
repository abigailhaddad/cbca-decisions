import os, sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import build, cbca, refresh

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(n):
    return open(os.path.join(FX, n), encoding="utf-8").read()


def test_cda_2026_table():
    rows, problems, skipped = cbca.parse_page(load("cda_2026.html"), "cda-cases")
    assert len(rows) == 156 and problems == []
    r = rows[0]
    assert r["decision_date"] == "2026-10-26" and r["case_number"] == "CBCA 8722"
    assert r["party"] == "American Indian Health Service of Chicago" and r["judge"] == "Beardsley"
    assert r["decision_type"] == "Decision" and r["party_role"] == "Appellant"
    assert r["decision_url"] == ("https://www.cbca.gov/files/decisions/2026/BEARDSLEY_10-26-26_8722__"
                                 "AMERICAN_INDIAN_HEALTH_SERVICE_OF_CHICAGO%20(DECISION).pdf")


def test_multi_docket():
    rows, _, _ = cbca.parse_page(load("cda_2026.html"), "cda-cases")
    r = next(x for x in rows if x["case_number"] == "CBCA 8250, 8251")
    assert r["dockets"] == ["CBCA 8250", "CBCA 8251"] and r["docket_count"] == 2


def test_two_rows_run_together_are_split():
    rows, problems, skipped = cbca.parse_page(load("cda_2022.html"), "cda-cases")
    assert problems == [] and len(skipped["merged_rows_split"]) == 1
    a = next(x for x in rows if x["case_number"] == "CBCA 6802")
    b = next(x for x in rows if x["case_number"] == "CBCA 6400, 6401, 6700")
    assert (a["judge"], a["decision_type"]) == ("Sullivan", "Dismissal")
    assert (b["judge"], b["decision_type"], b["docket_count"]) == ("Chadwick", "Decision", 3)


def test_commented_out_row_is_counted_not_parsed():
    rows, _, skipped = cbca.parse_page(load("cda_2024.html"), "cda-cases")
    # the commented-out row repeats a live one, with "(Decision)" instead of "(DECISION)" in the file name
    assert skipped["commented_out_rows"] == 1
    hits = [x["decision_url"] for x in rows if x["decision_url"] and "7767__WOIRHAYE" in x["decision_url"]]
    assert len(hits) == 1 and hits[0].endswith("(DECISION).pdf")


def test_missing_close_td_keeps_judge():
    rows, problems, _ = cbca.parse_page(load("relocation_2020.html"), "relocation")
    r = next(x for x in rows if x["case_number"] == "CBCA 6671-RELO")
    assert r["party"] == "Christy A. Cox" and r["judge"] == "Goodman" and problems == []


def test_placeholder_and_unlinked_row():
    rows, problems, skipped = cbca.parse_page(load("fcic.html"), "fcic")
    assert len(skipped["placeholders"]) == 1
    r = next(x for x in rows if x["case_number"] == "CBCA 126-FCIC")
    assert r["decision_url"] is None and r["decision_date"] == "2008-06-11"
    assert [p["why"] for p in problems] == ["0 links in row"]


def test_dockets_and_dates():
    assert cbca.dockets("CBCA 8151-R, 8162-R, 8163-R") == ["CBCA 8151-R", "CBCA 8162-R", "CBCA 8163-R"]
    assert cbca.dockets("CBCA 5273-ISDA, 5274-ISDA") == ["CBCA 5273-ISDA", "CBCA 5274-ISDA"]
    assert cbca.dockets("") == []
    assert cbca.dockets("GSBCA 16526-DBT") == ["GSBCA 16526-DBT"]
    assert cbca.dockets("3894-ISDA") == ["CBCA 3894-ISDA"]
    assert cbca.dockets("CBCA 8268-C(7213, 7393)") == ["CBCA 8268-C(7213, 7393)"]
    assert cbca.dockets("CBCA 7386, 7387 and 7496") == ["CBCA 7386", "CBCA 7387", "CBCA 7496"]
    assert cbca.iso_date("6/11/2008") == "2008-06-11" and cbca.iso_date("garbage") is None


def test_respondent_from_caption():
    txt = ("DISMISSED WITH PREJUDICE: October 16, 2026\nCBCA 8250, 8251\nGREAT LAKES EDUCATIONAL LOAN SERVICES, INC.,\n"
           "Appellant in CBCA 8250,\nand\nNELNET SERVICING, LLC,\nAppellant in CBCA 8251,\nv.\nDEPARTMENT OF EDUCATION,\n"
           "Respondent.\nStuart W. Turner")
    assert cbca.respondent_agency(txt) == "DEPARTMENT OF EDUCATION"
    assert cbca.respondent_agency("In the Matter of JOHN DOE\nClaimant.") is None


def test_listing_frame_dedupes_exact_repeats_and_flags_text():
    html = load("cda_2026.html")
    df, rep = build.listing_frame({"cda-cases": html + html})
    # the 2026 table already lists one decision twice (CBCA 8821, 8829)
    assert rep["exact_repeats_removed"] == 157 and len(df) == 155
    d = {"status": 200, "is_pdf": True, "format": "pdf", "pages": 1, "fetched_at": "x", "extract_error": None}
    e = build.enrich_one("u", "CBCA 8250; CBCA 8251", d, "CBCA 8250, 8251 " * 20 + "v. DEPARTMENT OF EDUCATION, Respondent.")
    assert e["text_status"] == "ok" and e["docket_in_text"] is True and e["agency"] == "DEPARTMENT OF EDUCATION"
    e = build.enrich_one("u", "CBCA 1", d, "")
    assert e["text_status"] == "little or no text (likely scanned)" and e["text"] is None


def test_refresh_merge_never_drops_and_keeps_old_text():
    old = pd.DataFrame({"id": ["a", "b"], "text": ["old a", "old b"]})
    new = pd.DataFrame({"id": ["b", "c"], "text": ["new b", "new c"]})
    merged, added = refresh.merge(old, new)
    assert list(merged.id) == ["a", "b", "c"] and list(added.id) == ["c"]
    assert merged.set_index("id").text["b"] == "old b"
