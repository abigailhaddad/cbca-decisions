---
license: other
license_name: us-government-public-domain
pretty_name: CBCA decisions
language:
- en
tags:
- government
- legal
- federal-contracting
- board-of-contract-appeals
size_categories:
- 1K<n<10K
configs:
- config_name: default
  data_files: data/decisions.parquet
---

# CBCA decisions

Every decision on the eight decision listings of the Civilian Board of Contract Appeals (https://www.cbca.gov/decisions/), with the text of each decision. One file, `data/decisions.parquet`: 6,354 rows. Not affiliated with CBCA and not an official record. Code and checks: https://github.com/abigailhaddad/cbca-decisions

## As of

The listing pages were read on 2026-11-15 at 05:22 UTC. The newest decision on them is dated 2026-10-27. The PDFs were downloaded between 05:23 and 13:42 UTC the same day. A daily job adds new entries after that (see the repo; it needs a token before it can upload).

## What a row is

One entry on a listing page: decision date, case number, the party (appellant, claimant, applicant or petitioner), the judge, and the link to the decision. The Contract Disputes Act page also gives a type (Decision, Dismissal, Order) for decisions since 2015; the other pages have no type.

| Listing page | Rows |
|---|---|
| Contract Disputes Act | 3,651 |
| Relocation | 1,159 |
| Travel | 534 |
| ISDA (Indian Self-Determination Act) | 498 |
| FEMA arbitration | 359 |
| FCIC (crop insurance) | 59 |
| Debt | 54 |
| Rate | 40 |

Dates run from 2002-04-25 to 2026-10-27. The six rows before 2007, when CBCA was created, are debt cases with GSBCA docket numbers on the Debt page.

A decision with several dockets is one row; `dockets` splits the case number ("CBCA 8250; CBCA 8251") and `docket_count` counts them. A PDF linked from two pages is a row on each, and `also_listed_on` names the other page. That's 8 rows (4 PDFs): two travel or relocation claims also listed on the Contract Disputes Act page, one decision covering a travel and a relocation docket, and CBCA 924-TRAV, whose travel-page link opens the CBCA 396 decision.

## Columns

`id` (stable key: listing page + link + case number + date), `board` (always CBCA), `case_type` (the listing page), `case_number`, `dockets`, `docket_count`, `party`, `party_role`, `judge`, `decision_type`, `decision_type_raw`, `decision_date`, `agency`, `agency_source`, `decision_url`, `file_format`, `listing_page`, `also_listed_on`, `pdf_pages`, `text_chars`, `text_status`, `date_in_text`, `docket_in_text`, `docket_in_file_name`, `text`, `fetched_at`.

Everything up to `decision_url` except `agency` comes from the listing as printed, with two fixes: the misspellings "Decison" (9 rows) and "Decsion" (1) become "Decision" in `decision_type` (the original is in `decision_type_raw`), and a case number without a board prefix gets "CBCA". Judge names are as listed, misspellings included (Kullburg, Vergillo, Zischaku, Sten, one row with "Dismissal" in the judge column).

`agency` is not on the listing. It is read from the decision text: the Respondent in the caption (4,116 rows), or else the first "appearing for ..." or "counsel for ..." that names a federal body (2,159 rows, mostly travel, relocation and FEMA cases). It is uppercased and otherwise as written, so a typo in a decision ("FEDERAL CROUP INSURANCE CORPORATION") stays. 79 rows have no agency.

`text` is extracted from the PDF with pypdf. No OCR.

## What was left out, and why

- 7 rows that repeat another row on the same page exactly (same link, case number and date).
- 1 row inside an HTML comment on the Contract Disputes Act page. It isn't shown on the live page, and it repeats a live row (CBCA 7767).
- 4 placeholder rows reading "No Decision" (1 on FCIC, 3 on Rate) for years with nothing listed.
- The predecessor boards (GSBCA and others) that CBCA links to but doesn't host, the 2000–2006 travel and relocation text files on the topic index, and anything not on the eight listing pages.
- The Armed Services Board of Contract Appeals. asbca.mil answered every request, robots.txt included, with an Akamai "Access Denied" page on 2026-11-15.

## Text status

| text_status | Rows |
|---|---|
| ok | 6,330 |
| little or no text (likely scanned) | 18 |
| partial (a page has no text, likely scanned) | 3 |
| HTTP 404 | 2 |
| no link on listing | 1 |

The two 404s are typos in the board's links. The working files are at https://www.cbca.gov/files/decisions/2022/VERGILIO_04-12-22_7322__JOSE_GARCIA%20(Dismissal).pdf (CBCA 7322, listed with a missing parenthesis) and https://www.cbca.gov/files/decisions/2020/VERGILIO_12-30-19_6531__FMS_INVESTMENT_CORPORATION.pdf (CBCA 6531, listed with a wrong relative path). The table keeps the listed link. CBCA 126-FCIC (June 11, 2008) has no link on the listing. One early decision (CBCA 2, June 1, 2007) is an HTML page, not a PDF; its text is the page's text.

## Checks

**Rows against the listing HTML.** A separate regex count of date cells in the live HTML gives 6,361, the same as the parser's rows before removing the 7 repeats. Per page the counts match after the repeats. The listing HTML is hand-edited: 5 places where a missing `<tr>` ran two rows together were split back into 10 rows, and missing `</td>` tags are handled. No row failed to parse.

**Listing against the decision text (all 6,334 rows with text).** The listed date is the first date in the decision for 6,268; it differs for 60 and no date was found in 6. The judge's surname appears in the decision for 6,319. A docket number from the listing appears in the decision for 6,316. Most disagreements are errors on the listing: a link to another case's decision, two rows with dates and case numbers crossed (CBCA 8241-RELO and 8402-RELO), a year or month typed wrong. Three flags let you find these rows: `date_in_text` (false for 62), `docket_in_text` (false for 18) and `docket_in_file_name` (false for 335, mostly older files named differently). The table keeps what the listing says.

**Text extraction.** For 60 random PDFs, downloaded again and read page by page with pdftotext, the text length agreed with pypdf's within 1% for every one. One of the 60 had a page with no text layer, and it is one of the 3 marked partial. A scanned page in the middle of a decision that otherwise has text can't be detected from the stored text, so a few "ok" rows may be missing a page.

**Counts against the board's annual reports.** The FY2024 and FY2025 reports (https://www.cbca.gov/board/AnnualReport.html) give cases resolved by type. Counting distinct dockets in this table by decision date in each fiscal year:

| Type | FY2024 table | FY2024 report | FY2025 table | FY2025 report |
|---|---|---|---|---|
| FEMA | 51 | 51 | 56 | 56 |
| Relocation | 18 | 18 | 46 | 47 |
| Travel | 14 | 14 | 13 | 13 |
| ISDA | 6 | 6 | 9 | 9 |
| EAJA | 4 | 4 | 2 | 2 |
| Rate | 1 | 1 | 0 | 0 |
| Debt | 9 | 14 | 5 | 9 |
| CDA appeals | 204 | 180 + 23 interlocutory | 195 | 165 + 16 interlocutory |

Debt: the report's resolved count includes voluntary dismissals (4 in each year), which the Debt page doesn't list; FY2025's 5 equals the report's 5 decisions on the merits. Relocation FY2025 is one short, and the report doesn't list dockets, so the missing one can't be named. CDA appeals don't line up one to one: the report counts cases resolved plus interlocutory decisions, while the listing has a row per posted decision, reconsiderations and remands carry their own docket numbers (14 such dockets in FY2024, 5 in FY2025), and the FY2024 report later had 4 appeals corrected (see the FY2025 report's footnote). The report's ADR, FMCSA, "Other" and Petition cases have no listing page. Page images of both report tables are in the repo's `checks/` folder.

**Live sample.** 25 random rows plus 18 edge cases (oldest, newest, most dockets, a 404, the HTML decision, a scanned PDF, a crossed listing entry and others). Each listing page was fetched again and the row found by its link; each PDF was downloaded again. All 184 listing fields matched the live page; 189 of 192 PDF checks passed, and the 3 that didn't are the edge cases chosen for those problems. The file with links is `checks/sample_2026-11-15.md` in the repo.

## Caveats

- No outcome field. Read the decision.
- `agency` is read from the text, not given by the board; it is blank for 79 rows and can't be better than the caption.
- Travel, relocation and debt rows name individual federal employees, as the board's listings do (recent ones by first name and initial).
- A corrected listing entry comes in as a new row on the next refresh, and the old row stays until a full rebuild.
