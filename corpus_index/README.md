# GLOBAL CORPUS INDEX v1

Canonical execution-side design for the research corpus index.

## Principle

Raw corpora are immutable. Every index is a rebuildable derivative and every hit must round-trip to the original source locator.

## Layers

- **L0 HOLDINGS** — what exists, where it lives, archive/completeness state.
- **L1 LOCATOR** — corpus → shard/file → row/page/paragraph locator.
- **L2 LEXICAL** — exact text retrieval. Chinese text is indexed as character-position tokens so 2-character names such as `蚩尤` and `共工` can be queried as exact FTS phrases.
- **L3 ENTITY_ALIAS** — canonical entity + aliases + holder split. Alias never implies identity.
- **L4 PROVENANCE** — base witness / commentary / OCR / modern derivative / project claim lineage.
- **L5 SEMANTIC** — optional fuzzy retrieval only after exact retrieval exists.

## Large-corpus strategy

The 508GB secondary corpus remains in Drive as 1788 immutable Parquet shards. Do **not** redownload it merely because Drive search misses.

1. Build a shard manifest and schema probe.
2. Stream each shard in batches.
3. Emit document/row locators and a contentless lexical index derivative.
4. Emit exact occurrences for the project entity registry with context and raw locator.
5. Validate row counts and a deterministic sample against raw bytes.
6. Persist index derivatives separately from raw shards.

The first pilot uses the public 26 Histories corpus (~36.9M characters) to validate the index engine before scaling to the 1788 Parquet shards.

## Query contract

A lexical result is not evidence by itself. A valid result must contain:

`corpus_id / source_file / unit_or_row / raw_locator / matched_term / context_or_refetch_instruction`.

## Files

- `entity_registry.tsv` — incremental exact-term / alias registry.
- `tools/global_corpus_index.py` — index builder/query engine.
- `.github/workflows/build-global-corpus-index.yml` — reproducible pilot build.
