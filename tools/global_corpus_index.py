#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GLOBAL CORPUS INDEX v1.

Builds a rebuildable locator + lexical index without treating the index as the
source of truth. Raw corpus files remain immutable.

The lexical index is SQLite FTS5 with character-position tokens for CJK text.
For example, 蚩尤 is indexed as the phrase tokens `蚩 尤`, allowing exact
2-character queries without relying on modern word segmentation.

Large Parquet corpora are processed row-by-row/batch-by-batch; the SQLite index
stores tokens and locators, not a second copy of the raw source text.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional


@dataclass
class EntityAlias:
    canonical: str
    alias: str
    entity_type: str
    notes: str


@dataclass
class Unit:
    source_file: str
    unit_no: int
    locator_type: str
    text: str


def normalize_text(text: str) -> str:
    return text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")


def is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x3400 <= cp <= 0x4DBF
        or 0x4E00 <= cp <= 0x9FFF
        or 0xF900 <= cp <= 0xFAFF
        or 0x20000 <= cp <= 0x3134F
    )


def lexical_tokens(text: str) -> str:
    """Turn text into FTS tokens while preserving Chinese character positions.

    CJK characters become one token each, so a query for 共工 becomes the FTS
    phrase "共 工". Latin/digit sequences are kept as lowercase words.
    """
    out: list[str] = []
    ascii_buf: list[str] = []

    def flush_ascii() -> None:
        if ascii_buf:
            out.append("".join(ascii_buf).lower())
            ascii_buf.clear()

    for ch in text:
        if is_cjk(ch):
            flush_ascii()
            out.append(ch)
        elif ch.isascii() and (ch.isalnum() or ch == "_"):
            ascii_buf.append(ch)
        elif ch.isalpha() or ch.isdigit():
            flush_ascii()
            out.append(ch.lower())
        else:
            flush_ascii()
    flush_ascii()
    return " ".join(out)


def query_to_fts(query: str) -> str:
    toks = lexical_tokens(query).split()
    if not toks:
        raise ValueError("query has no indexable tokens")
    escaped = [t.replace('"', '""') for t in toks]
    if len(escaped) == 1:
        return escaped[0]
    return '"' + " ".join(escaped) + '"'


def load_registry(path: Optional[Path]) -> list[EntityAlias]:
    if not path:
        return []
    rows: list[EntityAlias] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            alias = (r.get("alias") or "").strip()
            if not alias:
                continue
            rows.append(
                EntityAlias(
                    canonical=(r.get("canonical_entity") or alias).strip(),
                    alias=alias,
                    entity_type=(r.get("entity_type") or "UNKNOWN").strip(),
                    notes=(r.get("notes") or "").strip(),
                )
            )
    return rows


def compile_alias_regex(registry: list[EntityAlias]):
    by_alias = {r.alias: r for r in registry}
    aliases = sorted(by_alias, key=len, reverse=True)
    if not aliases:
        return None, by_alias
    return re.compile("|".join(re.escape(a) for a in aliases)), by_alias


def iter_txt_units(path: Path, root: Path) -> Iterator[Unit]:
    rel = path.relative_to(root).as_posix()
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, start=1):
            text = normalize_text(line).strip()
            if text:
                yield Unit(rel, line_no, "line", text)


def choose_text_column(schema_names: list[str], preferred: Optional[str]) -> str:
    if preferred:
        if preferred not in schema_names:
            raise ValueError(f"text column {preferred!r} not found; columns={schema_names}")
        return preferred
    candidates = [
        "text", "content", "document", "body", "article", "raw_content",
        "正文", "内容", "文本",
    ]
    lower = {n.lower(): n for n in schema_names}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    raise ValueError(
        "Could not infer text column. Pass --text-column. "
        f"Available columns: {schema_names}"
    )


def iter_parquet_units(path: Path, root: Path, text_column: Optional[str]) -> Iterator[Unit]:
    try:
        import pyarrow.parquet as pq  # type: ignore
    except Exception as exc:
        raise RuntimeError("Parquet mode requires pyarrow") from exc

    rel = path.relative_to(root).as_posix()
    pf = pq.ParquetFile(path)
    col = choose_text_column(pf.schema.names, text_column)
    row_no = 0
    for batch in pf.iter_batches(columns=[col], batch_size=2048):
        arr = batch.column(0)
        for value in arr.to_pylist():
            row_no += 1
            if value is None:
                continue
            text = normalize_text(str(value)).strip()
            if text:
                yield Unit(rel, row_no, "parquet_row", text)


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()


def initialize_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS docs (
            rowid INTEGER PRIMARY KEY,
            corpus_id TEXT NOT NULL,
            source_file TEXT NOT NULL,
            unit_no INTEGER NOT NULL,
            locator_type TEXT NOT NULL,
            char_len INTEGER NOT NULL,
            sha1 TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS docs_source_unit ON docs(source_file, unit_no)"
    )
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(tokens, content='')")
    return conn


def build_index(
    input_root: Path,
    files: list[Path],
    corpus_id: str,
    out_dir: Path,
    mode: str,
    registry: list[EntityAlias],
    text_column: Optional[str] = None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "lexical_index.sqlite"
    if db_path.exists():
        db_path.unlink()
    conn = initialize_db(db_path)
    alias_rx, by_alias = compile_alias_regex(registry)

    occ_path = out_dir / "entity_occurrences.csv"
    shard_path = out_dir / "source_manifest.csv"
    occ_f = occ_path.open("w", encoding="utf-8-sig", newline="")
    occ_w = csv.writer(occ_f)
    occ_w.writerow([
        "corpus_id", "canonical_entity", "alias", "entity_type",
        "source_file", "unit_no", "locator_type", "match_start", "match_end",
        "context", "unit_sha1",
    ])

    total_units = 0
    total_chars = 0
    total_occ = 0
    rowid = 0
    source_rows: list[list[object]] = []
    started = time.time()

    docs_batch: list[tuple] = []
    fts_batch: list[tuple] = []

    def flush_batches() -> None:
        nonlocal docs_batch, fts_batch
        if not docs_batch:
            return
        conn.executemany(
            "INSERT INTO docs(rowid, corpus_id, source_file, unit_no, locator_type, char_len, sha1) "
            "VALUES(?,?,?,?,?,?,?)",
            docs_batch,
        )
        conn.executemany("INSERT INTO fts(rowid, tokens) VALUES(?,?)", fts_batch)
        conn.commit()
        docs_batch = []
        fts_batch = []

    for file_no, path in enumerate(files, start=1):
        file_units = 0
        file_chars = 0
        file_occ = 0
        if mode == "txt":
            units: Iterable[Unit] = iter_txt_units(path, input_root)
        elif mode == "parquet":
            units = iter_parquet_units(path, input_root, text_column)
        else:
            raise ValueError(f"unsupported build mode: {mode}")

        for unit in units:
            rowid += 1
            total_units += 1
            file_units += 1
            nchar = len(unit.text)
            total_chars += nchar
            file_chars += nchar
            digest = sha1_text(unit.text)
            docs_batch.append(
                (rowid, corpus_id, unit.source_file, unit.unit_no, unit.locator_type, nchar, digest)
            )
            fts_batch.append((rowid, lexical_tokens(unit.text)))

            if alias_rx:
                for m in alias_rx.finditer(unit.text):
                    alias = m.group(0)
                    ent = by_alias[alias]
                    s = max(0, m.start() - 80)
                    e = min(len(unit.text), m.end() + 80)
                    context = unit.text[s:e].replace("\n", " ")
                    occ_w.writerow([
                        corpus_id, ent.canonical, alias, ent.entity_type,
                        unit.source_file, unit.unit_no, unit.locator_type,
                        m.start(), m.end(), context, digest,
                    ])
                    total_occ += 1
                    file_occ += 1

            if len(docs_batch) >= 2000:
                flush_batches()

        flush_batches()
        source_rows.append([
            corpus_id,
            path.relative_to(input_root).as_posix(),
            path.stat().st_size,
            file_units,
            file_chars,
            file_occ,
        ])
        print(
            f"[{file_no}/{len(files)}] {path.name}: units={file_units} "
            f"chars={file_chars} entity_occ={file_occ}",
            flush=True,
        )

    occ_f.close()
    conn.execute("INSERT INTO fts(fts) VALUES('optimize')")
    conn.commit()
    conn.close()

    with shard_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["corpus_id", "source_file", "bytes", "units", "chars", "entity_occurrences"])
        w.writerows(source_rows)

    manifest = {
        "schema_version": "GCI-1.0",
        "corpus_id": corpus_id,
        "mode": mode,
        "input_root": str(input_root),
        "file_count": len(files),
        "unit_count": total_units,
        "character_count": total_chars,
        "entity_occurrence_count": total_occ,
        "registry_alias_count": len(registry),
        "lexical_strategy": "contentless SQLite FTS5 over CJK character-position tokens",
        "locator_contract": "source_file + unit_no + locator_type + sha1",
        "raw_corpus_mutated": False,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": round(time.time() - started, 3),
        "outputs": {
            "lexical_index": db_path.name,
            "source_manifest": shard_path.name,
            "entity_occurrences": occ_path.name,
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def query_index(db_path: Path, query: str, limit: int = 100) -> list[dict]:
    conn = sqlite3.connect(db_path)
    q = query_to_fts(query)
    rows = conn.execute(
        """
        SELECT d.rowid, d.corpus_id, d.source_file, d.unit_no,
               d.locator_type, d.char_len, d.sha1
        FROM fts
        JOIN docs d ON d.rowid = fts.rowid
        WHERE fts MATCH ?
        ORDER BY d.source_file, d.unit_no
        LIMIT ?
        """,
        (q, limit),
    ).fetchall()
    conn.close()
    return [
        {
            "rowid": r[0],
            "corpus_id": r[1],
            "source_file": r[2],
            "unit_no": r[3],
            "locator_type": r[4],
            "char_len": r[5],
            "sha1": r[6],
            "query": query,
            "fts_query": q,
        }
        for r in rows
    ]


def write_smoke_queries(out_dir: Path, queries: list[str], limit: int) -> None:
    db_path = out_dir / "lexical_index.sqlite"
    rows: list[dict] = []
    for query in queries:
        hits = query_index(db_path, query, limit=limit)
        if not hits:
            rows.append({
                "query": query, "hit_rank": 0, "corpus_id": "", "source_file": "",
                "unit_no": "", "locator_type": "", "sha1": "", "fts_query": query_to_fts(query),
            })
        for rank, hit in enumerate(hits, start=1):
            rows.append({
                "query": query,
                "hit_rank": rank,
                "corpus_id": hit["corpus_id"],
                "source_file": hit["source_file"],
                "unit_no": hit["unit_no"],
                "locator_type": hit["locator_type"],
                "sha1": hit["sha1"],
                "fts_query": hit["fts_query"],
            })
    with (out_dir / "query_smoke.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "query", "hit_rank", "corpus_id", "source_file", "unit_no",
            "locator_type", "sha1", "fts_query",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def discover_files(root: Path, mode: str, pattern: Optional[str]) -> list[Path]:
    if root.is_file():
        return [root]
    if mode == "txt":
        pat = pattern or "*.txt"
    else:
        pat = pattern or "*.parquet"
    return sorted(p for p in root.rglob(pat) if p.is_file())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["txt", "parquet", "query"], required=True)
    ap.add_argument("--input", help="input file/directory for build modes")
    ap.add_argument("--corpus-id", default="UNKNOWN")
    ap.add_argument("--out", required=True, help="output directory, or index directory in query mode")
    ap.add_argument("--registry", help="TSV entity registry")
    ap.add_argument("--pattern", help="recursive filename glob")
    ap.add_argument("--text-column", help="Parquet text column")
    ap.add_argument("--query", help="query string in query mode")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--pilot-queries", default="")
    args = ap.parse_args()

    out_dir = Path(args.out)
    if args.mode == "query":
        if not args.query:
            ap.error("--query is required in query mode")
        hits = query_index(out_dir / "lexical_index.sqlite", args.query, args.limit)
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return 0

    if not args.input:
        ap.error("--input is required in build modes")
    root = Path(args.input)
    files = discover_files(root, args.mode, args.pattern)
    if not files:
        raise SystemExit(f"No {args.mode} files found under {root}")
    registry = load_registry(Path(args.registry) if args.registry else None)
    manifest = build_index(
        input_root=root if root.is_dir() else root.parent,
        files=files,
        corpus_id=args.corpus_id,
        out_dir=out_dir,
        mode=args.mode,
        registry=registry,
        text_column=args.text_column,
    )
    pilot_queries = [q.strip() for q in args.pilot_queries.split(",") if q.strip()]
    if pilot_queries:
        write_smoke_queries(out_dir, pilot_queries, args.limit)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
