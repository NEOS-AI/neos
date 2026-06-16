# Harness Eval Calibration

## Purpose

This document records how runtime harness thresholds are compared against offline `neos_evals` graders.

## Candidate Sets

| Set | Purpose | Expected failing checks |
| --- | --- | --- |
| high_citation_wrong | Many citations but unsupported claims | factuality |
| source_light | Too few independent sources | source_count, source_diversity |
| single_perspective | One-sided framing | bias_perspective |
| expensive_correct | Correct but over budget | performance_budget |

## Decision Rules

- Keep model checks optional when disagreement exceeds 20% on calibration fixtures.
- Promote `factuality` to required only for `mission_strict` after two calibration runs agree with offline factual graders at 85% or higher.
- Keep `bias_perspective` advisory until reviewer samples show fewer than 10% false-positive blocks.

## Running Calibration

Prepare candidate reports as JSONL, one case per line:

```json
{"case_id":"case-001","query":"research question","report":"final report text","sources":[{"id":1,"title":"source","url":"https://example.com"}],"metadata":{"harness_profile":"mission_strict"},"offline_graders":[{"grader_id":"factual_accuracy","score":0.4,"passed":false,"feedback":"unsupported claims","details":{}}]}
```

Run:

```bash
python scripts/harness_calibration.py \
  --input tmp/harness_candidates.jsonl \
  --output tmp/harness_calibration_report.jsonl \
  --profile mission_strict
```

The output JSONL includes runtime score, runtime verdict, failed runtime checks, offline grader scores, failed offline graders, and an agreement label:

- `agree_pass`
- `agree_fail`
- `runtime_stricter`
- `offline_stricter`
- `mixed`

## Latest Run

Record the command, commit, model judge, fixture count, agreement rate, recommended threshold changes, and reviewer notes here after each calibration pass.
