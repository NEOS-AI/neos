# Deep-analysis claim funnel sample

| Case ID | Profile | Status | Elapsed seconds | Tokens | Proposed | Graded | Verified | Rejected | Unverified |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fact-eu-ai-act | dev | completed | 720.6568459998816 | 65715 | 22 | 22 | 12 | 10 | 0 |
| fact-aspartame | dev | completed | 729.4342020419426 | 70791 | 29 | 29 | 28 | 1 | 0 |
| tech-hybrid-search | dev | completed | 825.6746965420898 | 71810 | 24 | 24 | 19 | 5 | 0 |
| tech-free-threading | dev | completed | 852.5733368750662 | 69358 | 18 | 18 | 13 | 5 | 0 |
| policy-london-ulez | dev | completed | 950.1429013749585 | 63036 | 18 | 18 | 12 | 6 | 0 |
| fact-eu-ai-act | default | completed | 813.6567763341591 | 156467 | 42 | 42 | 35 | 7 | 0 |

- Dominant loss stage: `agentic_loss` — 27 (24.3%)
- Quote buckets: {"above_threshold": 0, "exact": 111, "low": 0, "near_miss": 0, "unavailable": 0}
- Evidence missing rate: 0.0%
- Source dead rate: 0.0%
- Default minus dev deltas: proposed=20, graded=20, verified=23, rejected=-3, unverified=0

## Failures

- None

The stages overlap, and no policy was changed.
