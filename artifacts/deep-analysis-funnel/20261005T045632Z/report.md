# Deep-analysis claim funnel sample

| Case ID | Profile | Status | Elapsed seconds | Tokens | Proposed | Graded | Verified | Rejected | Unverified |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fact-eu-ai-act | dev | completed | 957.5351268749218 | 61842 | 23 | 23 | 20 | 3 | 0 |
| fact-aspartame | dev | completed | 722.9720845411066 | 72665 | 24 | 24 | 22 | 2 | 0 |
| tech-hybrid-search | dev | completed | 703.4659727909602 | 60796 | 16 | 16 | 16 | 0 | 0 |
| tech-free-threading | dev | failed | - | - | 0 | 0 | 0 | 0 | 0 |
| policy-london-ulez | dev | failed | - | - | 0 | 0 | 0 | 0 | 0 |
| fact-eu-ai-act | default | failed | - | - | 0 | 0 | 0 | 0 | 0 |

- Dominant loss stage: `agentic_loss` — 5 (7.9%)
- Quote buckets: {"above_threshold": 0, "exact": 63, "low": 0, "near_miss": 0, "unavailable": 0}
- Evidence missing rate: 0.0%
- Source dead rate: 0.0%
- Default minus dev deltas: proposed=-23, graded=-23, verified=-20, rejected=-3, unverified=0

## Failures

- tech-free-threading/dev: LLMProviderError at execution
- policy-london-ulez/dev: LLMProviderError at execution
- fact-eu-ai-act/default: LLMProviderError at execution

The stages overlap, and no policy was changed.
