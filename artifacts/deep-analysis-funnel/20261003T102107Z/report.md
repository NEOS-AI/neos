# Deep-analysis claim funnel sample

| Case ID | Profile | Status | Elapsed seconds | Tokens | Proposed | Graded | Verified | Rejected | Unverified |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fact-eu-ai-act | dev | completed | 624.9989004579838 | 80786 | 18 | 18 | 17 | 1 | 0 |
| fact-aspartame | dev | completed | 1088.4929770829622 | 70604 | 22 | 22 | 19 | 3 | 0 |
| tech-hybrid-search | dev | completed | 558.3792293749284 | 71886 | 11 | 11 | 11 | 0 | 0 |
| tech-free-threading | dev | completed | 784.8436863329262 | 65033 | 16 | 16 | 12 | 4 | 0 |
| policy-london-ulez | dev | completed | 688.083271499956 | 48136 | 13 | 13 | 7 | 6 | 0 |
| tech-free-threading | default | completed | 842.6258894170169 | 170563 | 26 | 26 | 16 | 10 | 0 |

- Dominant loss stage: `agentic_loss` — 14 (17.5%)
- Quote buckets: {"above_threshold": 0, "exact": 80, "low": 0, "near_miss": 0, "unavailable": 0}
- Evidence missing rate: 0.0%
- Source dead rate: 0.0%
- Default minus dev deltas: proposed=10, graded=10, verified=4, rejected=6, unverified=0

## Failures

- None

The stages overlap, and no policy was changed.
