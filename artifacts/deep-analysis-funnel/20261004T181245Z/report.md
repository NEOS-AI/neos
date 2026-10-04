# Deep-analysis claim funnel sample

| Case ID | Profile | Status | Elapsed seconds | Tokens | Proposed | Graded | Verified | Rejected | Unverified |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fact-eu-ai-act | dev | completed | 835.4110696669668 | 72265 | 11 | 11 | 9 | 2 | 0 |
| fact-aspartame | dev | completed | 857.5493742080871 | 77840 | 23 | 23 | 23 | 0 | 0 |
| tech-hybrid-search | dev | completed | 927.1223585410044 | 68267 | 21 | 21 | 19 | 2 | 0 |
| tech-free-threading | dev | completed | 892.2386822919361 | 75561 | 12 | 12 | 10 | 2 | 0 |
| policy-london-ulez | dev | completed | 884.1975692079868 | 72554 | 10 | 10 | 8 | 2 | 0 |
| tech-free-threading | default | completed | 773.0084360840265 | 163510 | 24 | 24 | 14 | 10 | 0 |

- Dominant loss stage: `agentic_loss` — 8 (10.4%)
- Quote buckets: {"above_threshold": 0, "exact": 77, "low": 0, "near_miss": 0, "unavailable": 0}
- Evidence missing rate: 0.0%
- Source dead rate: 0.0%
- Default minus dev deltas: proposed=12, graded=12, verified=4, rejected=8, unverified=0

## Failures

- None

The stages overlap, and no policy was changed.
