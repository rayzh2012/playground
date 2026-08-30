#!/usr/bin/env python3
import argparse, csv, json, math, re, shutil, subprocess, sys
from pathlib import Path

TERMS = {
    "divination": ["占","卜","筮","谶","吉","凶","卦","兆"],
    "dream_omen": ["梦","祥","瑞","灾","异","符瑞","神人"],
    "future_index": ["当王","将亡","当灭","将灭","不出","明日","明旦","来岁","今年","后年"],
    "calendar": ["历","择日","择吉","日书","建除","干支"],
    "domains": ["出行","疾病","官事","婚姻","牢狱","生产","财物","天命"],
}


def have(cmd):
    return shutil.which(cmd) is not None


def ocr_image(img: Path, lang: str):
    if not have("tesseract"):
        return "", "tesseract-missing"
    p = subprocess.run(["tesseract", str(img), "stdout", "-l", lang, "--psm", "6"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
                weight = 4 if group == "future_index" else 3 if group == "divination" else 2 if group in ("calendar","dream_omen") else 1
                total += n * weight
        if group_hits:
            hits[group] = group_hits
    # high-bandwidth bonus: time/future indexing + divination/omen on same page
    if "future_index" in hits and ("divination" in hits or "dream_omen" in hits):
        total += 10
    return total, hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--dpi", type=int, default=180)
    ap.add_argument("--lang", default="chi_sim+chi_tra")
    ap.add_argument("--threshold", type=int, default=3)
    args = ap.parse_args()

    src = Path(args.input_dir).expanduser().resolve()
    out = Path(args.output_dir).resolve()
    pages = out / "pages"
    candidates = out / "candidates"
    pages.mkdir(parents=True, exist_ok=True)
    candidates.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(src.rglob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found under {src}", file=sys.stderr)
        sys.exit(2)

    try:
        import fitz
    except ImportError:
        print("PyMuPDF missing: pip install pymupdf", file=sys.stderr)
        sys.exit(3)

    rows = []
    for pdf in pdfs:
        doc = fitz.open(pdf)
        stem = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", pdf.stem)[:100]
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=args.dpi, alpha=False)
            img = pages / f"{stem}__p{i+1:04d}.png"
            pix.save(img)
            text, ocr_note = ocr_image(img, args.lang)
            s, hits = score(text)
            is_candidate = s >= args.threshold
            cand_path = ""
            if is_candidate:
                dst = candidates / img.name
                shutil.copy2(img, dst)
                cand_path = str(dst)
            rows.append({
                "source_pdf": str(pdf),
                "page": i + 1,
                "page_image": str(img),
                "candidate_image": cand_path,
                "score": s,
                "hits_json": json.dumps(hits, ensure_ascii=False),
                "ocr_text": text.replace("\x00", ""),
                "ocr_note": ocr_note,
                "state": "RAW_HIT" if is_candidate else "BASELINE_PAGE",
            })

    manifest = out / "manifest.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader(); w.writerows(rows)

    summary = {
        "pdfs": len(pdfs),
        "pages": len(rows),
        "candidates": sum(r["state"] == "RAW_HIT" for r in rows),
        "threshold": args.threshold,
        "terms": TERMS,
        "note": "OCR/CV hits are leads only. Verify against raw page images and archaeological context."
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
