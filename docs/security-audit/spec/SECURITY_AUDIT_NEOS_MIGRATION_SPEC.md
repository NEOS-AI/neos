# security-audit — Neos Skill Pack Migration Spec

| Field | Value |
|---|---|
| Date | 2026-09-26 |
| Status | Spec (security-audit-skill → Neos) — IMPLEMENTATION CONTRACT |
| Product | Cloudflare security-audit (one Agent Skill, MIT) as a **markdown pack** plus two RO subagent leaves on the coding parent |
| Inventory | [../00-overview.md](../00-overview.md) |
| Child spec | [02-skills.md](./02-skills.md) |
| Process | [MIGRATION_PROCESS.md](./MIGRATION_PROCESS.md) |
| Source | `../security-audit-skill` (sibling clone). Does not replace that repo. Pin `c1c8a8c1471069fb0e188eeaff69b8e8db6564a8`. |

The skill is not an agent loop and not a `ParentKind`. The agent loop already exists as the coding harness. This spec attaches the pack the way k-skill attached `skills/k-skill/`: one catalog root, one-level scan, one coding-prompt line. It also registers two fail-closed kebab specs so hunters and verifiers are read-only leaves (`can_spawn=False`), which `explore` is not.

## Goals

1. Vendor **one** skill under `skills/security-audit/security-audit/` with companions, validators, and schema.
2. Index it with `security_audit_catalog()` (Univer-shaped, `SkillSource="repo"`).
3. Put **one** coding-catalog skill named `security-audit` on the coding `## Skills` list.
4. Let coding `load_skill.v1` return the **pack** body for `security-audit` (index is prompt-only). Resolve `reference=` from `references/`.
5. Register `security-audit-research` and `security-audit-general` on `SubagentRuntime`. Coding spawn **allows** them. Stepper must not fall through to the FSI prompt.

## Non-Goals (v0 hard)

- `ParentKind.SECURITY_AUDIT`. Tickets stay `ParentKind.CODING`.
- HTTP `/api/v1/security-audit` or a web skill picker.
- Wrapping as `BaseSkill` / `skill.py`.
- Dumping companion files as coding-catalog names or top-level `skills/<companion>/`.
- Child `execute.v1`, write tools, `WORKTREE`, scratch-jail, or artifact-promotion kernel.
- Python rewrite of the Node validators.
- Merging into `fsi_catalog()`, `univer_catalog()`, or `k_skill_catalog()`.
- Putting the pack folder on `default_skill_roots()` or `research_skill_roots()`.
- Live / shared-environment probing.

## Decisions locked

| # | Decision |
|---|---|
| D1 | Canonical tree is `skills/security-audit/security-audit/SKILL.md`. Pack root has no `SKILL.md`. Directory name = YAML `name` = catalog key. |
| D2 | Scanner stays one-level. Root is `skills/security-audit` once. |
| D3 | Pack is research markdown. Missing `## When to Use` / `## Boundaries` on the Cloudflare body is warn-only. Never add the pack folder to `default_skill_roots()`. Never wrap as `BaseSkill`. |
| D4 | `research_skill_roots()` does **not** gain the pack folder. |
| D5 | Vendor copies upstream `SKILL.md` as-is (already composed). Also copies companion `.md` into `references/` so `load_markdown(..., reference=)` works. Keep `.cjs` / schema beside `SKILL.md`. Do not rewrite the Cloudflare body. |
| D6 | Coding catalog lists exactly one new name: `security-audit` (`neos/coding/skills/security-audit.md`) with exact ATX `## When to Use` / `## Boundaries`. |
| D7 | `load_skill.v1`: `default_catalog` then `k_skill_catalog` then `security_audit_catalog`. Exception: if default hits the coding **index** `security-audit` and the pack also has that name, use the pack for the body and `reference=`. FSI/Univer/pdf/meta names stay `unknown_skill`. Companion filenames are not catalog names. |
| D8 | `SOURCE.md` records sibling `../security-audit-skill` plus git commit pin. Never a machine-local absolute path. |
| D9 | CI path-resolves. No runtime `copytree` from GitHub. |
| D10 | `neos.subagent` must not import a `neos.security_audit` package. Catalog constructors live in `neos/skills/markdown_catalog.py`. Specs live in `neos/subagent/catalog.py`. |
| D11 | Two kebab specs only: `security-audit-research` (recon, critic, Phase 5) and `security-audit-general` (hunter, Phase 3). Both `PARENT_RO`, `can_spawn=False`, `one_shot=True`, `can_approve=False`, no project instructions, **no** `execute.v1` / write tools. |
| D12 | Coding spawn **allows** those two kebabs. Still prefix-denies `fsi-*` and `univer-*`. Still fail-closed on unknown spec. Do not spawn DA `research`/`analyze`/`compose` or `implement` for this skill. |
| D13 | Stepper: `security-audit-*` gets a short JSON-report system prompt. Must not fall through to FSI. Parent copies selected blocks into the spawn brief. Child final text is exactly one JSON object. Parent `json.loads` the fold. Truncation or prose = malformed, reassign. |
| D14 | Parent (coding agent) is the only writer of shared run files. Local PoC without a real OS sandbox stays `needs_validation`. Missing Node validators stays `needs_validation` / incomplete. |
| D15 | `ParentKind.SECURITY_AUDIT` is out of v0. Metrics `_SPECS` add the two kebabs; `_PARENTS` unchanged. |
| D16 | Guidance mode remains the skill default. Full audit only on an explicit audit/pen-test/report request, and only when spawn is visible (implement phase) and `coding_model.subagent_enabled`. |

## Architecture

```
../security-audit-skill/skills/security-audit/{SKILL.md, companions, *.cjs}
        │  vendor copy
        ▼
skills/security-audit/security-audit/SKILL.md      security_audit_catalog()
skills/security-audit/security-audit/references/   load_markdown(..., reference=)
neos/coding/skills/security-audit.md               default_catalog()  (index only)

Coding agent prompt  ## Skills
  - security-audit: Security guidance and vulnerability review. Load the pack with load_skill.v1.

load_skill.v1 name=security-audit
  default_catalog hits index → prefer security_audit_catalog → Cloudflare SKILL.md

spawn_agent.v1 spec=security-audit-research | security-audit-general
  ParentKind.CODING, RO CodingToolPort, fold JSON → parent writes ledgers
```

## License

Retain MIT copyright from `../security-audit-skill/LICENSE` in `skills/security-audit/LICENSE`.
