"""Daily refresh: read CBCA's 8 listing pages, fetch the PDFs of new entries, merge into the Hugging Face table.

    python src/refresh.py --dry-run   # fetch and merge, write out/decisions.parquet, upload nothing
    python src/refresh.py             # uploads if HF_TOKEN is set and something was added

Rows are keyed by `id` (listing page + PDF URL + case number + date). A row CBCA drops from its listings is
kept: the table never shrinks. The run stops without uploading if a page fails to load, a page parses to
far fewer rows than the table already holds for it, a row can't be read at all, or more than
MAX_NEW PDFs would have to be fetched (rerun the full crawl for that).
"""
import json, os, sys

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(__file__))
import build, cbca, crawl

REPO = "abigailhaddad/cbca-decisions"
FILE = "data/decisions.parquet"
MAX_NEW = 300
OUT = build.OUT


def fetch_pages(session):
    pages = {}
    for page in cbca.PAGES:
        r = crawl.get(cbca.BASE + page + ".html", session)
        if r.status_code != 200:
            sys.exit(f"STOP: HTTP {r.status_code} on {page}; nothing uploaded")
        pages[page] = r.content.decode("utf-8", errors="replace")
    return pages


def merge(old, new):
    """Old rows keep their text; new ids are added; nothing is removed."""
    added = new[~new["id"].isin(set(old["id"]))]
    return pd.concat([old, added], ignore_index=True), added


def main():
    dry = "--dry-run" in sys.argv
    s = requests.Session()
    # --old PATH tests against a local copy instead of the Hugging Face file
    src = sys.argv[sys.argv.index("--old") + 1] if "--old" in sys.argv else f"https://huggingface.co/datasets/{REPO}/resolve/main/{FILE}"
    old = pd.read_parquet(src)
    pages = fetch_pages(s)
    live, rep = build.listing_frame(pages)

    unread = [p for p in rep["parse_problems"] if p["why"] == "unexpected cells"]
    if unread:
        sys.exit(f"STOP: {len(unread)} listing rows could not be read, e.g. {unread[0]}; nothing uploaded")

    # a listing page that suddenly parses to much less than we hold for it means the markup changed
    held = old.groupby("listing_page").size()
    got = live.groupby("listing_page").size()
    for lp, n in held.items():
        if got.get(lp, 0) < 0.9 * n:
            sys.exit(f"STOP: {lp} parsed to {got.get(lp, 0)} rows, table holds {n}; nothing uploaded")

    new = live[~live["id"].isin(set(old["id"]))].copy()
    known_text = old[old.text_status.notna() & (old.text_status != "not fetched")].drop_duplicates("decision_url").set_index("decision_url")
    need = [u for u in new.decision_url.dropna().unique() if u not in known_text.index]
    print(f"live rows {len(live)}, held {len(old)}, new {len(new)}, PDFs to fetch {len(need)}")
    if len(need) > MAX_NEW:
        sys.exit(f"STOP: {len(need)} new PDFs (> {MAX_NEW}); run the full crawl instead. Nothing uploaded.")

    fetched = {}
    for u in need:
        fetched[u] = crawl.fetch_pdf(u, s)

    def lookup(u):
        if u in fetched:
            return fetched[u]
        k = known_text.loc[u]
        # reuse what the table already has for a PDF that is now listed on a second page
        return {"status": 200, "is_pdf": k.file_format == "pdf", "format": k.file_format, "pages": k.pdf_pages,
                "fetched_at": k.fetched_at,
                "extract_error": None if k.text_status in ("ok", "little or no text (likely scanned)") else "earlier"}, k.text

    if len(new):
        new = build.enrich(new, lookup)
    merged, added = merge(old, new)
    merged = build.finish(merged)
    if len(merged) < len(old):
        sys.exit("STOP: would shrink the table; nothing uploaded")

    os.makedirs(OUT, exist_ok=True)
    build.write(merged, f"{OUT}/decisions.parquet")
    summ = {"rows": len(merged), "added": len(added), "pdfs_fetched": len(fetched),
            "fetch_failures": sum(1 for d, _ in fetched.values() if d.get("status") != 200),
            "parse_problems": len(rep["parse_problems"]), "decision_date_max": merged.decision_date.max()}
    json.dump({**summ, "added_rows": added[["case_number", "decision_date", "party", "listing_page"]].to_dict("records"),
               "parse_problem_list": rep["parse_problems"]}, open(f"{OUT}/summary.json", "w"), indent=1, default=str)
    print(summ)

    if dry:
        print("dry run: nothing uploaded")
        return
    if not len(added):
        print("nothing new")
        return
    if not os.environ.get("HF_TOKEN"):
        print("HF_TOKEN is not set: skipping the upload. Add a repo secret HF_TOKEN with write access to "
              f"{REPO} (Settings > Secrets and variables > Actions).")
        return
    from huggingface_hub import HfApi
    HfApi().upload_file(path_or_fileobj=f"{OUT}/decisions.parquet", path_in_repo=FILE, repo_id=REPO,
                        repo_type="dataset", commit_message=f"Refresh: +{len(added)} rows")


if __name__ == "__main__":
    main()
