# Deep-analysis claim funnel sample

| Case ID | Profile | Status | Elapsed seconds | Tokens | Proposed | Graded | Verified | Rejected | Unverified |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fact-eu-ai-act | dev | completed | 807.0716964998282 | 69543 | 12 | 12 | 12 | 0 | 0 |
| fact-aspartame | dev | completed | 723.4718738750089 | 68369 | 12 | 12 | 9 | 3 | 0 |
| tech-hybrid-search | dev | completed | 619.9641425828449 | 71673 | 19 | 19 | 17 | 2 | 0 |
| tech-free-threading | dev | failed | - | - | 0 | 0 | 0 | 0 | 0 |
| policy-london-ulez | dev | failed | - | - | 0 | 0 | 0 | 0 | 0 |
| fact-aspartame | default | failed | - | - | 0 | 0 | 0 | 0 | 0 |

- Dominant loss stage: `agentic_loss` — 5 (11.6%)
- Quote buckets: {"above_threshold": 0, "exact": 43, "low": 0, "near_miss": 0, "unavailable": 0}
- Evidence missing rate: 0.0%
- Source dead rate: 0.0%
- Default minus dev deltas: proposed=-12, graded=-12, verified=-9, rejected=-3, unverified=0

## Failures

- tech-free-threading/dev: LLMProviderError at execution
- policy-london-ulez/dev: LLMProviderError at execution
- fact-aspartame/default: LLMProviderError at execution

The stages overlap, and no policy was changed.
