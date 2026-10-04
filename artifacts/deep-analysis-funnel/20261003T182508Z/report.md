# Deep-analysis claim funnel sample

| Case ID | Profile | Status | Elapsed seconds | Tokens | Proposed | Graded | Verified | Rejected | Unverified |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fact-eu-ai-act | dev | completed | 642.777597208973 | 61166 | 9 | 9 | 6 | 3 | 0 |
| fact-aspartame | dev | completed | 789.1749347918667 | 78662 | 20 | 20 | 18 | 2 | 0 |
| tech-hybrid-search | dev | completed | 157.39902741718106 | 53010 | 14 | 14 | 13 | 1 | 0 |
| tech-free-threading | dev | failed | - | - | 0 | 0 | 0 | 0 | 0 |
| policy-london-ulez | dev | failed | - | - | 0 | 0 | 0 | 0 | 0 |
| tech-hybrid-search | default | failed | - | - | 0 | 0 | 0 | 0 | 0 |

- Dominant loss stage: `agentic_loss` — 6 (14.0%)
- Quote buckets: {"above_threshold": 0, "exact": 43, "low": 0, "near_miss": 0, "unavailable": 0}
- Evidence missing rate: 0.0%
- Source dead rate: 0.0%
- Default minus dev deltas: proposed=-14, graded=-14, verified=-13, rejected=-1, unverified=0

## Failures

- tech-free-threading/dev: LLMProviderError at execution
- policy-london-ulez/dev: LLMProviderError at execution
- tech-hybrid-search/default: LLMProviderError at execution

The stages overlap, and no policy was changed.
