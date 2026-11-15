# Handoff

## What runs
`.github/workflows/refresh.yml`, daily 11:25 UTC. It fetches CBCA's 8 decision listing pages, downloads the PDF of each entry that isn't in the Hugging Face table yet (one request a second), extracts the text with pypdf, and uploads `data/decisions.parquet` only if rows were added. No LLM, no OCR.

## What you need
- A repo secret `HF_TOKEN` with write access to `abigailhaddad/cbca-decisions`. Until it is set, every run does the fetch and merge, prints a warning, and skips the upload.
- The explorer site is `configs/cbca.json` in the `dataset-explorer` repo, deployed to the Cloudflare Pages project `cbca-decisions`. It reads the parquet from Hugging Face when the page loads, so it never needs a refresh.

## What breaks
- **CBCA changes the listing markup.** The run stops if a listing row can't be read or a page parses to under 90% of the rows the table already holds for it. Nothing is uploaded; GitHub emails you.
- **More than 300 new PDFs in one run** stops the run. Rerun the full crawl (`src/crawl.py listings`, `src/crawl.py pdfs`, `src/build.py`) and upload by hand.
- **The board corrects a listing entry** (date, case number or link). Row ids are built from those fields, so the corrected entry comes in as a new row and the old one stays. A full rebuild clears these.
- **ASBCA** (asbca.mil) answered every request, including robots.txt, with an Akamai "Access Denied" page on 2026-11-15. If that changes, it could be added as a second board.

## What the data is not
Not an official record. No outcome field (read the decision). Agency comes from the decision text, not the listing. Nothing from the predecessor boards (GSBCA and others) that CBCA links to but doesn't host, and none of the 2000–2006 travel and relocation text files on the topic index.
