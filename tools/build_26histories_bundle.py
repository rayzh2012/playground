#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a durable Twenty-Six Histories corpus bundle and frequency results."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
import csv
import hashlib
import json
import re
import shutil
import time
import zipfile

ROOT = Path("26histories_output")
CORPUS = ROOT / "corpus_26histories"
RESULTS = ROOT / "results"
ROOT.mkdir(exist_ok=True)
CORPUS.mkdir(exist_ok=True)
RESULTS.mkdir(exist_ok=True)

RAW_ROOT = "https://raw.githubusercontent.com/ahua/dataset/master/"
EXPECTED_TOTAL = 36_871_518

BOOKS = [
("01","史记","两汉史书层",640501),("02","汉书","两汉史书层",937972),("03","后汉书","两汉史书层",883521),
("04","三国志","魏晋南北朝",854325),("05","晋书","魏晋南北朝",1453803),("06","宋书","魏晋南北朝",1028274),
("07","南齐书","魏晋南北朝",385031),("08","梁书","魏晋南北朝",368183),("09","陈书","魏晋南北朝",202689),
("10","魏书","魏晋南北朝",1281297),("11","北齐书","魏晋南北朝",263571),("12","周书","魏晋南北朝",327629),
("13","隋书","隋唐",909341),("14","北史","魏晋南北朝",1382313),("15","南史","魏晋南北朝",846370),
("16","旧唐书","隋唐",2490424),("17","新唐书","隋唐",2110768),("18","旧五代史","五代两宋辽金",835200),
("19","新五代史","五代两宋辽金",364360),("20","宋史","五代两宋辽金",5001909),("21","辽史","五代两宋辽金",360832),
("22","金史","五代两宋辽金",1150243),("23","元史","元",1939733),("24","明史","明",3434258),
("附25","新元史","新元史扩展",2027142),("附26","清史稿","清史稿扩展",5391829),
]

REGISTRY = [
("蛇—ta系统","他",["他"]),("蛇—ta系统","她",["她"]),("蛇—ta系统","它",["它"]),
("蛇—ta系统","蛇",["蛇","虵"]),("蛇—ta系统","也",["也"]),("蛇—ta系统","佗",["佗"]),
("蛇—ta系统","牠",["牠"]),("蛇—ta系统","姐姊",["姐","姊"]),("蛇—ta系统","巳",["巳"]),
("蛇—ta系统","虺",["虺"]),("蛇—ta系统","螣蛇",["螣蛇","腾蛇","騰蛇"]),
("蛇—ta系统","巴蛇",["巴蛇"]),("蛇—ta系统","化蛇",["化蛇"]),("蛇—ta系统","鸣蛇",["鸣蛇","鳴蛇"]),
("娲—娃—蛙系统","娲",["娲","媧"]),("娲—娃—蛙系统","女娲",["女娲","女媧"]),
("娲—娃—蛙系统","娃",["娃"]),("娲—娃—蛙系统","女娃",["女娃"]),
("娲—娃—蛙系统","蛙",["蛙"]),("娲—娃—蛙系统","青蛙",["青蛙"]),
("娲—娃—蛙系统","黾",["黾","黽"]),("娲—娃—蛙系统","精卫",["精卫","精衛"]),
("鸟—凤—风系统","鸟",["鸟","鳥"]),("鸟—凤—风系统","凤",["凤","鳳"]),
("鸟—凤—风系统","凤凰",["凤凰","鳳凰","凤皇","鳳皇"]),("鸟—凤—风系统","玄鸟",["玄鸟","玄鳥"]),
("鸟—凤—风系统","朱鸟朱雀",["朱鸟","朱鳥","朱雀"]),("鸟—凤—风系统","精卫",["精卫","精衛"]),
("鸟—凤—风系统","风",["风","風"]),("鸟—凤—风系统","皇",["皇"]),
]

CONTEXT_TAGS = {
"神名祭祀":["神","帝","祀","祭","庙","廟","祠","祝","巫","天命","祥瑞"],
"动物自然":["兽","獸","虫","蟲","鱼","魚","山","水","泽","澤","鸣","鳴"],
"政治王权":["王","皇","帝","诏","詔","命","国","國","朝","官"],
"地名官名":["州","县","縣","郡","府","宫","宮","阁","閣","池","门","門"],
"灾异":["灾","災","异","異","旱","雨","水","洪","震","蝗"],
"战争":["兵","军","軍","战","戰","伐","攻","守","杀","殺"],
"海鸟转换":["海","溺","填","鸟","鳥","化","羽","飞","飛"],
}

def normalize(text: str) -> str:
    return text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def download(book_id: str, name: str) -> Path:
    filename = f"{book_id}{name}.txt"
    local = CORPUS / filename
    if local.exists() and local.stat().st_size > 1000:
        return local
    # Important fix: encode the entire Chinese path, including the 26史 directory.
    url = RAW_ROOT + quote(f"26史/{filename}")
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 26histories-corpus-builder"})
    last = None
    for attempt in range(5):
        try:
            with urlopen(req, timeout=180) as r:
                data = r.read()
            if len(data) < 1000:
                raise RuntimeError(f"download too small: {len(data)} bytes")
            local.write_bytes(data)
            return local
        except Exception as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"下载失败 {filename}: {last}")

def classify_context(ctx: str) -> str:
    tags = [tag for tag, kws in CONTEXT_TAGS.items() if any(k in ctx for k in kws)]
    return "|".join(tags) if tags else "未分类"

def matches(text: str, variants: list[str]):
    pats = sorted(set(variants), key=len, reverse=True)
    rx = re.compile("|".join(re.escape(x) for x in pats))
    return list(rx.finditer(text))

def write_csv(path: Path, header, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

def main():
    manifest_books = []
    by_book = []
    context_samples = []
    era_chars = defaultdict(int)
    era_counts = defaultdict(lambda: defaultdict(int))
    total_counts = defaultdict(int)

    for book_id, name, era, expected_chars in BOOKS:
        path = download(book_id, name)
        text = normalize(path.read_text(encoding="utf-8", errors="replace"))
        chars = len(text)
        era_chars[era] += chars
        manifest_books.append({
            "id": book_id, "name": name, "era": era, "filename": path.name,
            "bytes": path.stat().st_size, "chars": chars, "expected_chars": expected_chars,
            "char_match": chars == expected_chars, "sha256": sha256(path),
        })
        for system, term, variants in REGISTRY:
            ms = matches(text, variants)
            raw = sum(text.count(v) for v in variants)
            count = len(ms)
            total_counts[(system, term)] += count
            era_counts[era][(system, term)] += count
            by_book.append([book_id, name, era, chars, system, term, " / ".join(variants), raw, count, count / chars * 1_000_000])
            for m in ms[:50]:
                s = max(0, m.start() - 100)
                e = min(len(text), m.end() + 100)
                ctx = text[s:e].replace("\n", " ")
                context_samples.append([book_id, name, era, system, term, m.group(0), m.start(), classify_context(ctx), ctx])

    total_chars = sum(x["chars"] for x in manifest_books)
    by_era = []
    for era in ["两汉史书层","魏晋南北朝","隋唐","五代两宋辽金","元","明","新元史扩展","清史稿扩展"]:
        chars = era_chars[era]
        for system, term, _ in REGISTRY:
            count = era_counts[era][(system, term)]
            by_era.append([era, chars, system, term, count, count / chars * 1_000_000 if chars else 0])
    totals = []
    for system, term, variants in REGISTRY:
        count = total_counts[(system, term)]
        totals.append([system, term, " / ".join(variants), count, total_chars, count / total_chars * 1_000_000])

    write_csv(RESULTS / "by_book.csv", ["序号","书名","时代","字符数","系统","词项","变体","独立Raw次数","最长优先次数","每百万字"], by_book)
    write_csv(RESULTS / "by_era.csv", ["时代","字符数","系统","词项","次数","每百万字"], by_era)
    write_csv(RESULTS / "totals.csv", ["系统","词项","变体","次数","总字符数","每百万字"], totals)
    write_csv(RESULTS / "contexts_sample.csv", ["序号","书名","时代","系统","词项","命中","位置","自动标签","上下文±100字"], context_samples)

    manifest = {
        "source": "ahua/dataset/26史",
        "source_url": "https://github.com/ahua/dataset/tree/master/26史",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "book_count": len(manifest_books),
        "total_chars": total_chars,
        "expected_total_chars": EXPECTED_TOTAL,
        "total_char_match": total_chars == EXPECTED_TOTAL,
        "books": manifest_books,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    corpus_zip = ROOT / "26histories_corpus_v1.zip"
    with zipfile.ZipFile(corpus_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(CORPUS.glob("*.txt")):
            z.write(p, arcname=f"corpus_26histories/{p.name}")
        z.write(ROOT / "manifest.json", arcname="manifest.json")

    results_zip = ROOT / "26histories_symbol_results_v1.zip"
    with zipfile.ZipFile(results_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(RESULTS.glob("*.csv")):
            z.write(p, arcname=f"results/{p.name}")
        z.write(ROOT / "manifest.json", arcname="manifest.json")

    print(json.dumps({
        "book_count": len(manifest_books),
        "total_chars": total_chars,
        "expected_total_chars": EXPECTED_TOTAL,
        "match": total_chars == EXPECTED_TOTAL,
        "corpus_zip": str(corpus_zip),
        "results_zip": str(results_zip),
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
