# k-skill — Neos 분석 문서

NomaDamas `k-skill` 리포지토리(`../k-skill`, MIT; 프록시 서버만 AGPL-3.0)는 한국 실생활·공공데이터용 Agent Skill 모음이다. Claude Code / Codex / OpenCode 등에 `npx skills add NomaDamas/k-skill --all -g`로 설치되고, 런타임은 `@nomadamas/k-skill` CLI + 선택적 `k-skill-proxy`다.

이 디렉터리는 원본이 무엇을 하는지, Neos에 무엇을 옮기는지를 고정한다.

구현 계약은 [`spec/K_SKILL_NEOS_MIGRATION_SPEC.md`](./spec/K_SKILL_NEOS_MIGRATION_SPEC.md). 스킬 팩 착륙은 [`spec/02-skills.md`](./spec/02-skills.md). 코드 기준 순서는 [`spec/MIGRATION_PROCESS.md`](./spec/MIGRATION_PROCESS.md).

## 읽는 순서

| 문서 | 내용 |
|---|---|
| [00-overview.md](./00-overview.md) | 원본 구조, 127 스킬, CLI/프록시 런타임, 이식 범위 |
| [spec/K_SKILL_NEOS_MIGRATION_SPEC.md](./spec/K_SKILL_NEOS_MIGRATION_SPEC.md) | Neos 착륙 설계와 잠긴 결정 |
| [spec/02-skills.md](./spec/02-skills.md) | 팩 트리, 카탈로그, 코딩 `load_skill.v1` 폴백 |
| [spec/MIGRATION_PROCESS.md](./spec/MIGRATION_PROCESS.md) | TDD 착륙 순서 |

## 한 줄 요약

- **127** 원본 스킬 (`skill.json` + `instruction.md`). Neos v0는 메타 2개(`k-skill-setup`, `k-skill-cleaner`)를 빼고 **125**개를 `skills/k-skill/<name>/`에 벤더한다.
- Univer와 같은 **한 단계 팩 카탈로그** (`k_skill_catalog()`). `ParentKind`·kebab leaf·MCP 허브·프록시 서버는 v0 밖이다.
- 코딩 에이전트 `## Skills`에는 인덱스 스킬 `k-skill` 한 줄만 올린다. 본문 로드는 `default_catalog` miss 뒤 `k_skill_catalog()` 폴백이다.
