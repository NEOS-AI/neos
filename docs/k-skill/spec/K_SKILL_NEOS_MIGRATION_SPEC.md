# k-skill — Neos Skill Pack Migration Spec

| Field | Value |
|---|---|
| Date | 2026-09-26 |
| Status | Spec (k-skill → Neos) — IMPLEMENTATION CONTRACT |
| Product | NomaDamas k-skill (127 Agent Skills, MIT) as a **markdown pack** on the existing coding/research catalogs |
| Inventory | [../00-overview.md](../00-overview.md) |
| Child spec | [02-skills.md](./02-skills.md) |
| Process | [MIGRATION_PROCESS.md](./MIGRATION_PROCESS.md) |
| Source | `../k-skill` (sibling clone). Does not replace that repo. |

k-skill is not an agent loop and not a `ParentKind`. It is a locale pack of independent `SKILL.md` tools. The agent loop already exists as the coding harness. This spec attaches the pack the way Univer attached `skills/univer/`: one catalog root, one-level scan, no coding-catalog dump of every name.

## Goals

1. Vendor **125** domain skills under `skills/k-skill/<name>/`.
2. Index them with `k_skill_catalog()` (Univer-shaped, `SkillSource="repo"`).
3. Put **one** coding-catalog skill named `k-skill` on the coding `## Skills` list so the coding agent can discover the pack.
4. Let coding `load_skill.v1` resolve pack names via `k_skill_catalog()` after `default_catalog()` misses. FSI and Univer names stay `unknown_skill` on that path.
5. Keep scripts/references next to each skill. Agents follow the markdown (curl to hosted proxy, local scripts, `npx` helpers). Neos does not reimplement the CLI assembler or the proxy.

## Non-Goals (v0 hard)

- `ParentKind.KSKILL` / kebab leaves / `SubagentRuntime` graphs.
- HTTP `/api/v1/k-skill` or a web skill picker.
- Porting `k-skill-proxy`, Dolshoi, CloakBrowser, `k-skill-browser-runtime`.
- Wrapping skills as `BaseSkill` / `skill.py`.
- Adding the 125 names as flat files under `neos/coding/skills/` or as top-level `skills/<name>/`.
- Vendoring `k-skill-setup` or `k-skill-cleaner`.
- Merging into `fsi_catalog()` or `univer_catalog()`.

## Decisions locked

| # | Decision |
|---|---|
| D1 | Canonical tree is `skills/k-skill/<skill>/SKILL.md`. One copy. Directory name = YAML `name` = catalog key. |
| D2 | Scanner stays one-level. Root is `skills/k-skill` once. Do not recurse. Do not flatten onto `skills/`. |
| D3 | Pack is research markdown. Missing `## When to Use` / `## Boundaries` is warn-only. Never add the pack folder to `default_skill_roots()`. Never wrap as `BaseSkill`. |
| D4 | `research_skill_roots()` does **not** gain the pack folder (same as FSI/Univer). Discovery for agents is `k_skill_catalog()` plus the coding index skill. |
| D5 | Neos `SKILL.md` body is `instruction.md`, not the generated CLI stub. Frontmatter comes from `skill.json.frontmatter` (keep `license` / `metadata`). |
| D6 | Copy `skill.json`, `instruction.md`, `scripts/`, `references/` or `reference/`, `templates/`, `tests/`, `LICENSE.upstream`, `NOTICE`, `requirements.txt` when present. Do not copy `packages/`, `infra/`, `.claude-plugin/`, or generated CLI stubs as the body. |
| D7 | Exclude `k-skill-setup` and `k-skill-cleaner`. Port set is **125**. |
| D8 | Coding catalog lists exactly one new name: `k-skill` (`neos/coding/skills/k-skill.md`) with exact ATX `## When to Use` / `## Boundaries`. It teaches `load_skill.v1` with pack names. |
| D9 | Coding `SandboxToolExecutor._load_skill` uses `default_catalog()` first, then `k_skill_catalog()`. It does **not** consult `fsi_catalog()` or `univer_catalog()`. |
| D10 | Hosted proxy URLs in `instruction.md` stay. Neos does not vendor AGPL proxy code. BYOK skills keep their env var names. |
| D11 | Irreversible side effects stay in the markdown (`clarify` before pay/send/submit). Neos adds no extra parent binding denylist in v0. |
| D12 | CI path-resolves. No `copytree` into agent profiles. No `sync-agent-skills.py`. |
| D13 | `neos.subagent` does not import a k-skill package. Catalog constructors live in `neos/skills/markdown_catalog.py` only. No `neos.kskill` package in v0. |
| D14 | Draft-phase `consumer-price-safety-search` is included (it is a real directory). Do not rewrite its body. |

## Architecture

```
../k-skill/<name>/{skill.json,instruction.md,scripts/,references/}
        │  vendor compose
        ▼
skills/k-skill/<name>/SKILL.md     k_skill_catalog()
neos/coding/skills/k-skill.md      default_catalog()  (index only)

Coding agent prompt  ## Skills
  - k-skill: 한국 실생활·공공데이터 스킬 팩. load_skill.v1 이름으로 본문을 연다.

load_skill.v1 name=korea-weather
  default_catalog miss → k_skill_catalog hit → instruction body
```

## Background

FSI and Univer packs are parent-gated: coding `load_skill.v1` must not see `xlsx-author`. k-skill is a general Korean locale pack for the same coding agent that already lists `web-search` and `plan`. Dumping 125 lines into every coding prompt is the wrong shape. One index skill plus a catalog fallback is the attach.

## License

Retain MIT copyright from `../k-skill/LICENSE` in `skills/k-skill/LICENSE`. Keep Apache-2.0 `LICENSE.upstream` / `NOTICE` on the two wrapper skills.
