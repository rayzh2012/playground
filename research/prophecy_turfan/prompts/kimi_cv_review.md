# Kimi Code handoff — Prophecy × Turfan CV review

You are reviewing machine-triaged scans from the Prophecy / Future-Omen project.

## Goal

Do **not** try to prove supernatural prophecy. Identify contemporaneous or independently datable written material that contains divination, omen interpretation, calendar selection, foreknowledge, or concrete future propositions, and separate it from ordinary documents and later scholarly interpretation.

## Input

- `manifest.csv`
- `summary.json`
- `candidates/*.png`
- original PDFs remain local and are the authority

## Required output

Create `reviewed_candidates.csv` with:

`source_pdf,page,artifact_or_tomb_id,estimated_date,raw_ocr,corrected_reading,domain,signal_type,future_proposition,actionable,time_indexed,event_indexed,pre_event_witness,material_context,confidence,state,notes`

Allowed states:

`RAW_HIT, LEAD, CANDIDATE, EVIDENCE, NEGATIVE_CONTROL, FALSE_POSITIVE, SEARCH_MISS, STATUS_UNKNOWN`

## Review rules

1. Raw scan > OCR > modern scholarly transcription. Never overwrite the distinction.
2. If a character is uncertain, retain uncertainty such as `□`, `[?]`, or alternatives.
3. Do not infer "prophecy" from isolated 吉/凶/瑞/灾. Require an actual predictive or decision-oriented structure.
4. Distinguish future information from remote-present information.
5. Separate calendrical/择吉 practice from event prediction.
6. Search miss is not absence.
7. Keep denominator pages: ordinary documents remain `BASELINE_PAGE` outside this reviewed candidate table and are counted in `summary.json`.
8. Flag high-bandwidth cases when a page combines a specific future event/result with a time index or named target.
9. For every high-bandwidth case, record what establishes the manuscript's date and whether that date precedes the predicted event.
10. Produce a short `review_notes.md` describing false-positive patterns and OCR failure modes.

## Research logic

Five Hu / Sixteen Kingdoms is the current historical test period. Histories preserve many claims of foreknowledge, but later recording creates postdiction risk. Turfan / Hexi excavated manuscripts are being used as independently datable contemporaneous controls and possible pre-event witnesses. The project is ultimately testing future-information density and chronology, not collecting colorful prophecy stories.
