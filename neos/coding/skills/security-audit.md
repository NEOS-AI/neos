---
name: security-audit
description: Security guidance and vulnerability review. Load the pack with load_skill.v1.
---

# security-audit

## When to Use

Use for security questions, focused reviews, vulnerability research, security audits, or pen tests. Call `load_skill.v1` with name `security-audit` for the workflow body, then `reference=<companion>` for phase files (`RECONNAISSANCE.md`, `HUNTING.md`, …). Do not invent companion names. Do not dump companion leaves into this prompt.

On a full audit, spawn `spawn_agent.v1` with spec `security-audit-research` (recon, critic, Phase 5) or `security-audit-general` (hunter, Phase 3). The pack body's `research` and `general` workers are those kebab specs.

## Boundaries

Do not run the six-phase full audit or write audit artifacts unless the user explicitly asks to audit or pen-test a codebase, or requests report artifacts. Do not spawn `research`, `general`, `analyze`, `compose`, `explore`, or `implement` for this skill. Do not probe live or shared systems. Do not modify target source. Pack body lives under `skills/security-audit/security-audit/SKILL.md`. Validators are `.cjs` files next to that SKILL.md, not catalog names.
