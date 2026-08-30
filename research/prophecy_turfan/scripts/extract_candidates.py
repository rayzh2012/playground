#!/usr/bin/env python3
import argparse, csv, hashlib, json, re, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

TERMS = {
    "divination": ["占","卜","筮","谶","讖","卦","兆","吉","凶","验","驗","候"],
    "dream_omen": ["梦","夢","祥","瑞","灾","災","异","異","符瑞","神人"],
    "future_index": ["当王","當王","将亡","將亡","当灭","當滅","将灭","將滅","不出","明日","明旦","来岁","來歲","今年","后年","後年"],
    "calendar": ["历","曆","历日","曆日","择日","擇日","择吉","擇吉","日书","日書","建除","月建","岁在","歲在","干支","宜","忌","利","不利"],
    "domains": ["出行","疾病","病","官事","官","婚姻","婚","牢狱","牢獄","生产","生產","财物","財物","失物","兵","王","亡","死","生","天命"],
}

WEIGHTS = {"future_index": 4, "divination": 3, "calendar": 2, "dream_omen": 2, "domains": 1}


def have(cmd):
    return shutil.which(cmd) is not None


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def available_tess_langs():
    if not have("tesseract"):
        return set()
    p = subprocess.run(["tesseract", "--list-langs"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return {x.strip() for x in p.stdout.splitlines() if x.strip() and not x.startswith("List of")}


def resolve_lang(requested: str):
    langs = available_tess_langs()
    if requested != "auto":
        return requested
    for pair in (("chi_sim", "chi_tra"), ("HanS", "HanT")):
        if all(x in langs for x in pair):
            return "+".join(pair)
    for one in ("chi_sim", "HanS", "chi_tra", "HanT", "eng"):
        if one in langs:
            return one
    return "eng"


def ocr_image(img: Path, lang: str, psm: int):
    if not have("tesseract"):
        return "", "tesseract-missing"
    p = subprocess.run(["tesseract", str(img), "stdout", "-l", lang, "--psm", str(psm)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.stdout, p.stderr.strip()


def score(text: str):
    hits = {}
    total = 0
    for group, words in TERMS.items():
        group_hits = []
        for w in words:
            n = text.count(w)
            if n:
                group_hits.append({"term": w, "count": n})
                total += n * WEIGHTS[group]
        if group_hits:
            hits[group] = group_hits
    if "future_index" in hits and ("divination" in hits or "dream_omen" in hits):
        total += 10
    return total, hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--dpi", type=int, default=140)
    ap.add_argument("--lang", default="auto")
    ap.add_argument("--psm", type=int, default=6)
    ap.add_argument("--threshold", type=int, default=3)
    ap.add_argument("--page-start", type=int, default=1, help="1-based inclusive; applied to each PDF")
    ap.add_argument("--page-end", type=int, default=0, help="1-based inclusive; 0 = end of PDF")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--keep-baseline-images", action="store_true")
    args = ap.parse_args()

    src = Path(args.input_dir).expanduser().resolve()
    out = Path(args.output_dir).resolve()
    pages = out / "pages"
    candidates = out / "candidates"
    per_page = out / "page_results"
    pages.mkdir(parents=True, exist_ok=True)
    candidates.mkdir(parents=True, exist_ok=True)
    per_page.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(src.rglob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found under {src}", file=sys.stderr)
        sys.exit(2)

    try:
        import fitz
    except ImportError:
        print("PyMuPDF missing: pip install pymupdf", file=sys.stderr)
        sys.exit(3)

    lang = resolve_lang(args.lang)
    jobs = []
    sources = []
    for pdf in pdfs:
        doc = fitz.open(pdf)
        start = max(1, args.page_start)
        end = len(doc) if args.page_end <= 0 else min(len(doc), args.page_end)
        if start > end:
            continue
        source_sha = sha256(pdf)
        sources.append({"source_pdf": str(pdf), "sha256": source_sha, "pages_total": len(doc), "selected_start": start, "selected_end": end})
        stem = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", pdf.stem)[:100]
        for page_no in range(start, end + 1):
            page = doc[page_no - 1]
            pix = page.get_pixmap(dpi=args.dpi, alpha=False)
            img = pages / f"{stem}__p{page_no:04d}.png"
            pix.save(img)
            jobs.append((pdf, source_sha, page_no, img))
        doc.close()

    def worker(job):
        pdf, source_sha, page_no, img = job
        text, ocr_note = ocr_image(img, lang, args.psm)
        s, hits = score(text)
        is_candidate = s >= args.threshold
        cand_path = ""
        if is_candidate:
            dst = candidates / img.name
            shutil.copy2(img, dst)
            cand_path = str(dst)
        if not args.keep_baseline_images and not is_candidate:
            img.unlink(missing_ok=True)
        row = {
            "source_pdf": str(pdf),
            "source_sha256": source_sha,
            "page": page_no,
            "candidate_image": cand_path,
            "score": s,
            "hits_json": json.dumps(hits, ensure_ascii=False),
            "ocr_text": text.replace("\x00", "").replace("\r", " ").replace("\n", " "),
            "ocr_note": ocr_note,
            "state": "RAW_HIT" if is_candidate else "BASELINE_PAGE",
        }
        (per_page / f"{source_sha[:12]}__p{page_no:04d}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        return row

    rows = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = [ex.submit(worker, j) for j in jobs]
        for fut in as_completed(futs):
            rows.append(fut.result())
    rows.sort(key=lambda r: (r["source_pdf"], r["page"]))

    manifest = out / "manifest.csv"
    fields = ["source_pdf","source_sha256","page","candidate_image","score","hits_json","ocr_text","ocr_note","state"]
    with manifest.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)

    summary = {
        "pdfs": len(pdfs),
        "sources": sources,
        "pages_selected": len(rows),
        "candidates": sum(r["state"] == "RAW_HIT" for r in rows),
        "threshold": args.threshold,
        "dpi": args.dpi,
        "workers": args.workers,
        "tesseract_lang": lang,
        "page_start": args.page_start,
        "page_end": args.page_end,
        "terms": TERMS,
        "note": "OCR/CV hits are leads only. Verify raw page images, archaeological context, manuscript date, and predicted-event date before promotion."
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
