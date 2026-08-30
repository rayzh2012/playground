# Prophecy × Turfan CV Pipeline

Purpose: turn scanned Turfan / Hexi archaeological PDFs into a machine-triaged corpus for the Future-Omen / Prophecy project.

## Research logic lock

The goal is **not** to prove prophecy for its own sake. Prophecy is used as a probe for unusually strong future-information leakage and possible human–yaojie overlap periods.

Current priority chain:

1. Five Hu / Sixteen Kingdoms was selected as a high-priority period because official histories preserve unusually dense foreknowledge, prophecy, dream, omen and political-oracle narratives.
2. Those narratives have a critical weakness: a later history saying a prediction "came true" does not establish that the wording existed before the event.
3. Therefore the project searches for independently datable contemporaneous witnesses.
4. Turfan / Hexi is unusually valuable because excavated manuscripts can preserve sealed, dated, archaeological contexts outside later historiographical rewriting.
5. The corpus must include both omen/divination candidates and ordinary documents. Ordinary household registers, contracts, tax ledgers, administrative papers and funerary lists provide the denominator needed for density estimates.
6. Computer vision performs the high-volume scan. Human / model review is reserved for high-scoring candidates and final verification against raw images, tomb context and scholarly readings.

## Pipeline

`PDF -> page render -> deskew/contrast -> OCR -> keyword/domain scoring -> candidate crops -> model review -> witness verification -> registry`

Candidate terms include: 占, 卜, 筮, 谶, 梦, 吉, 凶, 历, 日, 择, 灾, 祥, 当王, 将亡, 出行, 疾病, 官事, 天命, 符瑞, 神人.

## Evidence discipline

For every candidate preserve:

`source_pdf | page | artifact/tomb id | date | raw image | OCR text | domain | candidate terms | score | modern reading | alternative reading | future proposition? | actionable? | time-indexed? | event-indexed? | pre-event witness? | state`

A search miss is not absence. OCR output is a lead, not evidence. The raw page image remains the primary witness.

## Execution modes

- GitHub-hosted: for public/direct-download PDFs or repo-local test files.
- Self-hosted macOS: preferred for private/local Google Drive synced PDFs. The workflow accepts a local source directory and can run without uploading the source PDFs to GitHub.
- Kimi Code review: optional second stage over the generated candidate manifest and crops. See `prompts/kimi_cv_review.md`.
