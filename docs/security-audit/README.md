# security-audit — Neos 분석 문서

Cloudflare `security-audit-skill` 리포지토리(`../security-audit-skill`, MIT)는 코딩 에이전트를 방어적 소스 감사자로 바꾸는 **한 개의 멀티페이즈 스킬**이다. 설치는 `npx skills add https://github.com/cloudflare/security-audit-skill --skill security-audit`. 런타임 서버나 `skill.py`는 없다. 부모는 호스트 코딩 에이전트다.

이 디렉터리는 원본이 무엇을 하는지, Neos에 무엇을 옮기는지를 고정한다.

구현 계약은 [`spec/SECURITY_AUDIT_NEOS_MIGRATION_SPEC.md`](./spec/SECURITY_AUDIT_NEOS_MIGRATION_SPEC.md). 스킬 팩 착륙은 [`spec/02-skills.md`](./spec/02-skills.md). 코드 기준 순서는 [`spec/MIGRATION_PROCESS.md`](./spec/MIGRATION_PROCESS.md).

## 읽는 순서

| 문서 | 내용 |
|---|---|
| [00-overview.md](./00-overview.md) | 원본 구조, 6페이즈, companion, 검증기 |
| [spec/SECURITY_AUDIT_NEOS_MIGRATION_SPEC.md](./spec/SECURITY_AUDIT_NEOS_MIGRATION_SPEC.md) | Neos 착륙 설계와 잠긴 결정 |
| [spec/02-skills.md](./spec/02-skills.md) | 팩 트리, 카탈로그, 코딩 `load_skill.v1` 폴백 |
| [spec/MIGRATION_PROCESS.md](./spec/MIGRATION_PROCESS.md) | TDD 착륙 순서 |

## 한 줄 요약

- 원본은 스킬 **하나** (`security-audit`) + companion markdown 14개 + Node 검증기 둘 + `report-schema.json`.
- Univer/k-skill과 같은 **한 단계 팩 카탈로그** (`security_audit_catalog()`). `ParentKind`는 v0 밖이다.
- 코딩 `## Skills`에는 인덱스 스킬 `security-audit` 한 줄만 올린다. 본문은 팩 `SKILL.md`다.
- 멀티페이즈 자식은 kebab 스펙 둘: `security-audit-research`, `security-audit-general`. 둘 다 읽기 전용 잎이다.
