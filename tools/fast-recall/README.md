# FAST RECALL — bounded context from connected Notion

## Purpose
Recover **high-information, source-addressed context** while minimizing text entering the assistant's context window. This is retrieval orchestration, not a new source of truth.

## Live connector execution
Open `live_connector_recipe.js`, replace `QUERY`, and run it in the ChatGPT Code Mode `functions.exec` runtime with connected Notion tools. It searches pages, reorders entity/current-source pages above long logs, fetches one relevant page, and emits only source IDs plus bounded evidence snippets.

The *backend still fetches the whole selected page.* Only the model-facing result is compacted. Need exact quotations or conflicting interpretations? Escalate to targeted primary-source read; keep FACT / INFERENCE / OPEN / CANON separate.

## Persistent deployment caveat
A Notion Skill can stay available across conversations and guide future tool calls, but this source file is **not** automatically executed by ChatGPT at every turn. A local SQLite cache requires a separate host and authorized `NOTION_TOKEN` and has not been deployed by this pull request. No scheduled task is enabled.

## Workflow
1. Use current conversation first.
2. For older cross-chat projects, do at least one narrow state lookup.
3. Search 1–3 precise queries in parallel; only fetch relevant authoritative pages.
4. Preserve source page ID, branch, current version, contradictions and rejected models.
5. Deep-read only for exact citations, major canon changes or unresolved conflicts.
6. Save substantive deltas to the existing canonical project and compact capsule; keep full text in its original archive.

## Scope and security
This repository contains **generic retrieval code only**, no private Notion page identifiers, tokens, exports, user history, or research corpus. The connected Skill and white paper are managed in the owner's Notion workspace.

## Validation
One-shot connected Notion tests on 2026-11-12 compared three large historical boot pages (1,321,481 returned characters; 6,704 ms) with five targeted searches (4,549 returned characters; 1,284 ms). This is *not an equal-workload latency benchmark* or an exact token count. Five-topic focused evidence extraction was additionally tested, but percentiles and persistent runtime benchmarks remain open.
