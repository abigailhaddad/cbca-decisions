"""Download CBCA's listing pages and every linked decision PDF, keep the extracted text, delete the PDF.

    python src/crawl.py listings        # 8 listing pages -> raw/listings/
    python src/crawl.py pdfs            # every PDF on them -> raw/text/<id>.txt, a line per PDF in raw/pdfs.jsonl

One request a second at most. Resumable: a URL already in raw/pdfs.jsonl with status 200 is skipped.
Stops after 5 straight 403/429/5xx answers.
"""
import hashlib, io, json, os, sys, time
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(__file__))
import cbca

UA = "cbca-decisions-collector/1.0 (public-records research)"
ROOT = os.path.join(os.path.dirname(__file__), "..")
RAW = os.path.join(ROOT, "raw")
PAUSE = 1.0
_last = [0.0]


def get(url, session):
    wait = PAUSE - (time.monotonic() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.monotonic()
    return session.get(url, headers={"User-Agent": UA}, timeout=120)


def text_id(url):
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def extract(pdf_bytes):
    """Text with pypdf. Returns (text, pages, error). A scanned PDF gives little or no text; no OCR here."""
    from pypdf import PdfReader
    try:
        r = PdfReader(io.BytesIO(pdf_bytes))
        parts, bad = [], []
        for i, p in enumerate(r.pages):
            try:
                parts.append(p.extract_text() or "")
            except Exception as e:  # one bad page shouldn't lose the rest; the page is named in the error
                parts.append("")
                bad.append(f"p{i + 1} {type(e).__name__}")
        extract.empty_pages = [i + 1 for i, t in enumerate(parts) if len(t.strip()) < 30]
        return "\n".join(parts), len(r.pages), ("page errors: " + ", ".join(bad))[:300] if bad else None
    except Exception as e:
        return "", None, f"{type(e).__name__}: {e}"[:300]


def fetch_pdf(url, session):
    """Download one decision and extract its text. Returns (record, text or None)."""
    t = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        r = get(url, session)
    except requests.RequestException as e:
        return {"url": url, "status": None, "error": f"{type(e).__name__}"[:200], "fetched_at": t}, None
    rec = {"url": url, "status": r.status_code, "fetched_at": t, "content_type": r.headers.get("content-type")}
    if r.status_code != 200:
        return rec, None
    return to_text(rec, r.content)


def to_text(rec, body):
    """Fill in the fetch record from the downloaded bytes and return (record, text). Pure: no network."""
    url = rec["url"]
    rec.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), is_pdf=body[:5] == b"%PDF-")
    is_html = not rec["is_pdf"] and ("html" in (rec["content_type"] or "") or url.lower().rsplit(".", 1)[-1] in ("htm", "html"))
    rec["format"] = "pdf" if rec["is_pdf"] else "html" if is_html else "other"
    if rec["is_pdf"]:
        extract.empty_pages = None
        txt, pages, err = extract(body)
        rec["empty_pages"] = extract.empty_pages
    elif is_html:  # a few early decisions are HTML pages
        txt, pages, err = cbca.html_text(body.decode("utf-8", errors="replace")), None, None
    else:
        txt, pages, err = "", None, "not a PDF or HTML"
    rec.update(pages=pages, chars=len(txt), extract_error=err, text_id=text_id(url))
    return rec, txt


def listings():
    os.makedirs(f"{RAW}/listings", exist_ok=True)
    s = requests.Session()
    meta = {}
    for page in cbca.PAGES:
        url = cbca.BASE + page + ".html"
        r = get(url, s)
        r.raise_for_status()
        open(f"{RAW}/listings/{page}.html", "wb").write(r.content)
        meta[page] = {"url": url, "bytes": len(r.content), "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "last_modified": r.headers.get("last-modified")}
        print(page, len(r.content))
    json.dump(meta, open(f"{RAW}/listings/fetched.json", "w"), indent=1)


def listed_urls():
    urls = []
    for page in cbca.PAGES:
        rows, _, _ = cbca.parse_page(open(f"{RAW}/listings/{page}.html", encoding="utf-8", errors="replace").read(), page)
        urls += [r["decision_url"] for r in rows if r["decision_url"]]
    return list(dict.fromkeys(urls))


def pdfs(limit=None):
    os.makedirs(f"{RAW}/text", exist_ok=True)
    log = f"{RAW}/pdfs.jsonl"
    done = set()
    if os.path.exists(log):
        for line in open(log):
            d = json.loads(line)
            if d.get("status") == 200:
                done.add(d["url"])
    todo = [u for u in listed_urls() if u not in done]
    if limit:
        todo = todo[:limit]
    print(f"{len(done)} done, {len(todo)} to fetch", flush=True)
    s = requests.Session()
    bad = 0
    # downloads stay one at a time (one a second); text extraction runs in other processes so a long PDF
    # doesn't slow the downloads
    from concurrent.futures import ProcessPoolExecutor
    pending = []

    def save(rec, txt, f):
        if txt is not None and rec.get("text_id"):
            open(f"{RAW}/text/{rec['text_id']}.txt", "w", encoding="utf-8").write(txt)
        f.write(json.dumps(rec) + "\n")
        f.flush()

    def drain(f, wait=False):
        for fut in list(pending):
            if wait or fut.done():
                save(*fut.result(), f)
                pending.remove(fut)

    with open(log, "a") as f, ProcessPoolExecutor(3) as pool:
        for i, u in enumerate(todo):
            t = datetime.now(timezone.utc).isoformat(timespec="seconds")
            try:
                r = get(u, s)
                rec = {"url": u, "status": r.status_code, "fetched_at": t, "content_type": r.headers.get("content-type")}
            except requests.RequestException as e:
                r, rec = None, {"url": u, "status": None, "error": f"{type(e).__name__}"[:200], "fetched_at": t}
            st = rec.get("status")
            if st == 200:
                pending.append(pool.submit(to_text, rec, r.content))
            else:
                save(rec, None, f)
            drain(f)
            bad = bad + 1 if (st in (403, 429) or st is None or (st or 0) >= 500) else 0
            if bad >= 5:
                drain(f, wait=True)
                sys.exit(f"STOP: 5 straight failures, last {st} on {u}")
            if i % 200 == 0:
                print(i, st, u[-70:], flush=True)
        drain(f, wait=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "listings":
        listings()
    elif cmd == "pdfs":
        pdfs(int(sys.argv[2]) if len(sys.argv) > 2 else None)
    else:
        sys.exit(__doc__)
