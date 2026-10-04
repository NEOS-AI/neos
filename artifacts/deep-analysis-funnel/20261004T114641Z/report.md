# Deep-analysis claim funnel sample

| Case ID | Profile | Status | Elapsed seconds | Tokens | Proposed | Graded | Verified | Rejected | Unverified |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fact-eu-ai-act | dev | completed | 687.6016941249836 | 66180 | 12 | 12 | 8 | 4 | 0 |
| fact-aspartame | dev | completed | 824.2487830829341 | 78994 | 22 | 22 | 16 | 6 | 0 |
| tech-hybrid-search | dev | completed | 852.6062350419816 | 59290 | 11 | 11 | 11 | 0 | 0 |
| tech-free-threading | dev | completed | 772.3581609169487 | 80397 | 17 | 17 | 11 | 6 | 0 |
| policy-london-ulez | dev | completed | 793.8417549168225 | 73265 | 14 | 14 | 11 | 3 | 0 |
| policy-london-ulez | default | completed | 973.3514526670333 | 180347 | 22 | 22 | 20 | 2 | 0 |

- Dominant loss stage: `agentic_loss` — 19 (25.0%)
- Quote buckets: {"above_threshold": 0, "exact": 76, "low": 0, "near_miss": 0, "unavailable": 0}
- Evidence missing rate: 0.0%
- Source dead rate: 0.0%
- Default minus dev deltas: proposed=8, graded=8, verified=9, rejected=-1, unverified=0

## Failures

- None

The stages overlap, and no policy was changed.
