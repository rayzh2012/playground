# Global Corpus Index — Delta Registry Protocol

## Purpose

After the 34-alias 508GB baseline has passed its 1788-shard coverage gate, new research aliases must not force a rescan of already-indexed aliases. New aliases are compiled as an append-only delta and scanned once across the same immutable source-shard universe.

## Baseline immutability

The completed baseline is identified by:

- baseline registry snapshot / digest
- exact corpus IDs
- exact shard ordinal coverage
- per-shard source path + byte size + SHA256
- scanner version
- locator contract

Never rewrite baseline occurrence rows to incorporate a later interpretation. Identity/merge changes belong in registry metadata or graph layers, not in the lexical witness layer.

## Delta contract

Each delta gets a stable `DELTA_ID` and contains only aliases not present in any earlier successful baseline/delta registry snapshot.

Required fields:

- `delta_id`
- `canonical_entity`
- `alias`
- `entity_type`
- `notes`
- `precision_class`
- `hard_false_positive_substrings`
- `introduced_utc`
- `registry_source`

A delta scan must:

1. validate that no alias duplicates any successful prior baseline/delta alias;
2. freeze the delta registry before launching matrix jobs;
3. scan all 1788 immutable shards once with Aho–Corasick;
4. emit RAW occurrences with corpus/shard/row/character locators;
5. derive RESEARCH occurrences only through explicit precision policy;
6. validate exact Literature 1..233 and CWT 0..1554 coverage;
7. persist a delta manifest, term totals, by-alias partitions, and source-registry digest;
8. union query-time datasets logically; do not rewrite old Parquet merely to append a new alias.

## Query semantics

`ALL_OCCURRENCES(alias)` is the union of the one baseline/delta partition that owns that alias. Because aliases are unique across successful registry snapshots, an alias must have exactly one lexical owner.

Entity interpretation remains source-dependent. A lexical hit is not an identity proof.

## Quality semantics

- `RAW_OCCURRENCE`: every exact lexical match; immutable and auditable.
- `RESEARCH_OCCURRENCE`: RAW minus only deterministic hard-false-positive rules explicitly declared in policy.
- LOW/MEDIUM precision aliases are never silently deleted; they require context review.

Example: `共工` inside `公共工程` is retained in RAW and excluded from RESEARCH by an explicit rule. `黄帝` inside `黄帝内经` remains because it is not intrinsically false; it is a different context class.

## Promotion gate

A delta is query-visible only after:

- all batch jobs succeed;
- exact 1788-shard coverage succeeds;
- raw/research/hard-false-positive reconciliation succeeds;
- by-alias row totals reconcile to the delta raw total;
- the frozen delta registry digest is stored with the artifact.

Until then its status is `BUILDING`, not `INDEXED`.
