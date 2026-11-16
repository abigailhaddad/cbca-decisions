# cbca-decisions

Every decision on the Civilian Board of Contract Appeals' eight decision listings (https://www.cbca.gov/decisions/), with the text of each decision, as one table on Hugging Face: https://huggingface.co/datasets/abigailhaddad/cbca-decisions. Browse it at https://cbca-decisions.pages.dev (once the explorer PR is merged). Not affiliated with CBCA.

A row is one entry on a listing page: date, case number(s), party, judge, the decision type where the board gives one, and a link to the PDF. The text is extracted from that PDF with pypdf, and the agency is read from the decision's caption. A GitHub Action runs every day and adds new decisions. The table never shrinks: an entry CBCA removes from its listings stays.

The Armed Services Board of Contract Appeals isn't here. asbca.mil answered every request, robots.txt included, with an Akamai "Access Denied" page, so it wasn't collected.

**Before the daily job can upload, add a repo secret `HF_TOKEN`** with write access to the dataset (Settings > Secrets and variables > Actions). Without it the job runs, says it skipped the upload, and exits cleanly.

## Run it

    pip install -r requirements-dev.txt
    python -m pytest tests
    python src/crawl.py listings      # the 8 listing pages -> raw/listings/
    python src/crawl.py pdfs          # every linked PDF, one request a second (about 1h45m); keeps the text, not the PDF
    python src/build.py               # raw/ -> out/decisions.parquet and out/report.json
    python src/check.py               # second checks, and a live sample written to checks/ (--no-sample skips it)
    python src/refresh.py --dry-run   # what the daily job does, without the upload

`src/cbca.py` reads the listing pages. The pages are hand-edited HTML with missing `</td>` and `</tr>` tags, rows run together, a commented-out row, and placeholder "No Decision" rows; the tests in `tests/` use real cuts of those pages.

## Checks

The dataset card (`hf/README.md`, also on Hugging Face) has the counts and how they reconcile. `checks/` holds the sample file (each sampled field compared to the live listing row and the re-downloaded PDF, with links) and the annual-report pages used for the fiscal-year comparison, and a pdftotext comparison of 60 PDFs.

## Data dictionary

[`docs/data_dictionary.md`](docs/data_dictionary.md) lists every column of the table with its type, a description, the share of rows that have a value, and an example. Types, counts and examples are read from the published parquet files; descriptions are in [`docs/tables.toml`](docs/tables.toml), written from the code that builds each column. Regenerate it with

    python src/data_docs.py fetch data   # download the current files from Hugging Face
    python src/data_docs.py write data   # write docs/data_dictionary.md

`write` also updates the same section in `hf/README.md`, the dataset card kept in this repo; the card is still uploaded to Hugging Face by hand. `src/data_docs.py` stops with an error if a parquet column has no description in `docs/tables.toml` or a described column is gone, and the daily workflow runs that check too.

## SQLite download

The daily workflow builds `cbca-decisions.sqlite` from the files on Hugging Face (table `decisions`, plus `_source`, which records the Hugging Face commit) and attaches it to the GitHub release [`latest-data`](https://github.com/abigailhaddad/cbca-decisions/releases/tag/latest-data). The release is replaced whenever the Hugging Face commit changes. To build it yourself:

    python src/build_sqlite.py data cbca-decisions.sqlite
