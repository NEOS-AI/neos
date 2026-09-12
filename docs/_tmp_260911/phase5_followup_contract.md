# Phase 5 follow-up contract

No Claude prompt paste. No coordinator/team. No Discord auto-thread / Block Kit / pairing / WebFetch / ToolSearch / spawn_agent / stream-during-RO this slice.

## File ownership

| Owner | Files |
|---|---|
| Core | `neos/coding/instructions.py`, `neos/coding/phases.py`, `neos/coding/prompts/builder.py` (boundary only), `tests/coding/test_instructions.py`, `tests/coding/test_phases.py` |
| Tools | `neos/coding/tools/registry.py`, `executor.py`, `neos/coding/skills/{verify,commit}.md`, `observability.py` tool names, `domain/approvals.py` (USER_QUESTION), `tests/coding/tools/test_registry.py`, `test_executor.py` |
| Loop | `neos/coding/loop/anthropic.py` (bootstrap, phase filter, recovery, set_phase persist), `tests/coding/loop/test_anthropic_loop.py` |
| Model | `neos/coding/model/anthropic.py` (413 → prompt_too_long, cache_control split), `tests/coding/model/` or existing model tests |

## Instructions
Load `AGENTS.md` then `CLAUDE.md` from the sandbox (first existing file wins). Cap 16KiB. Wrap in an explicit fence. Inject as a **user** message on first model turn, never into `AnthropicLoopConfig.system`.

## Phases (same process)
`explore` | `implement` (default) | `verify`

Hidden tools:
- explore: `edit_file.v1`, `write_file.v1`, `execute.v1`
- verify: `edit_file.v1`, `write_file.v1`
- implement: none

`set_phase.v1` READ_ONLY. Persist `loop_state.phase`. Model request uses `definitions(phase=...)`. Hidden calls → `policy_phase_denied`.

## Tools
- `ask_user.v1`: questions list (1–4). Risk `USER_QUESTION` → require approval (not auto-allow).
- `load_skill.v1`: name `verify` or `commit` only. Returns bundled markdown. No hook skip. No `skill.py`.

## Recovery
- HTTP 413 / `prompt_too_long` → compact once, persist `prompt_compact_retries`, retryable failure so next delivery continues.
- `stop_reason=max_tokens` once → escalate `max_output_tokens` (×4, cap 64000), persist `output_token_escalations`, retryable. Second max_tokens stays `model_output_incomplete`.

## Cache
Builder inserts `<!-- neos:dynamic -->` after Actions. Anthropic request: static block + `cache_control: ephemeral`, then dynamic block.

## Out of scope
spawn_agent, WebFetch, ToolSearch, stream-during-RO, Discord/Slack UX extras.
