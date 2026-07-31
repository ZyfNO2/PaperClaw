# P0 blinded question and gold-label guide

This file is an authoring guide, not gold evidence. A human domain reviewer must
replace all `HUMAN_AUTHOR_REQUIRED` values in `questions.blinded.jsonl` and record
the resulting file hash in the frozen protocol before any run.

Each question must have one stable ID, one question type, one intended evidence
scope, and enough information for a second reviewer to replay the answer. Gold
labels are stored outside Git in `gold_labels.private.jsonl` and must contain:

- accepted answer(s), supporting paper/version, page and object/region locator;
- allowable inference and explicit overclaim boundary;
- abstention target and severe-error conditions;
- annotator, independent reviewer, timestamp, and disagreement resolution.

The annotator must use the canonical `academic.v1` `EvidenceLocator`. A locator
from a superseded paper version, a missing source hash, or an unresolvable object
blocks the question; it is never silently repaired.

The runner receives only `questions.blinded.jsonl`. Gold is loaded only after the
run has been sealed, and is never a prompt, few-shot example, query, or trace field.
