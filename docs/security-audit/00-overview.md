# 00. security-audit — 개요

원본 README 한 줄:

> A coding-agent skill that turns your agent into a security auditor.

조사 기준: 로컬 클론 `/Users/yeonwoosung/Desktop/security-audit-skill`, HEAD `c1c8a8c1471069fb0e188eeaff69b8e8db6564a8` (`main`, 깨끗함). 라이선스 MIT, Copyright (c) 2025–2026 Cloudflare, Inc.

## 1. 원본이 하는 일

가이던스가 기본이다. 스킬을 연 것만으로 6페이즈나 산출물 디렉터리를 만들지 않는다. 사용자가 코드베이스 감사·펜테스트·전체 리뷰·리포트 산출물을 명시하면 **full audit**다.

여섯 페이즈:

| # | 페이즈 | 소유 파일 | 위임 |
|---|---|---|---|
| 1 | Reconnaissance | `RECONNAISSANCE.md` | 병렬 `research` 1a–1d. 파일에 쓰지 않음 |
| 2 | Coverage-led hunting | `HUNTING.md` + `ATTACK-CLASSES.md` + 선택된 companion | `general` 헌터, 이후 `research` critic |
| 3 | Candidate validation | `VALIDATION-AND-REPORTING.md` | 헌터가 아닌 새 `general` verifier |
| 4 | Structured output | 같은 파일 + `report-schema.json` | 부모만 `findings.json` 쓰고 검증기 실행 |
| 5 | Independent record verification | 같은 파일 | 새 `research` verifier. `quick`는 3+5 병합 |
| 6 | Target-neutral reporting | 같은 파일 | 부모만 `REPORT.md` / `FINDINGS-DETAIL.md` / `NEEDS-VALIDATION.md` |

부모만 공유 파일을 쓴다: `run-metadata.json`, `architecture.md`, `coverage-ledger.json`, `findings.json`, 리포트 셋. 자식은 `<output>/agents/<id>/scratch/`만 쓴다. 산출물 기본 경로는 타깃 밖 `~/security-audit-skill/<repo>/run-<N>`이다.

판정 셋: `confirmed`(소스 추적 + 유계 관측 결과), `needs_validation`(정확한 미해소 사실, severity 없음), `rejected`(반증된 후보).

## 2. 디렉터리

```
security-audit-skill/
  LICENSE
  README.md
  skills/security-audit/
    SKILL.md
    RECONNAISSANCE.md
    HUNTING.md
    VALIDATION-AND-REPORTING.md
    ATTACK-CLASSES.md
    AI-AND-LLM.md
    CLIENT-SIDE.md
    CLOUD-AND-DEPLOYMENT.md
    DATA-ISOLATION-AND-LIFECYCLE.md
    DESKTOP-MOBILE-AND-LOCAL-IPC.md
    MEMORY-SAFETY-AND-BINARY.md
    PROTOCOLS-RPC-AND-MESSAGING.md
    RESOURCE-EXHAUSTION-AND-AVAILABILITY.md
    SUPPLY-CHAIN-AND-RELEASE.md
    WEB-PROTOCOL-AND-AUTH.md
    report-schema.json
    validate-findings.cjs
    validate-coverage-ledger.cjs
    validate-*.test.cjs
```

소스 오브 트루스: `SKILL.md`와 형제 파일. `skill.json` / `instruction.md` / CLI 스텁이 없다. 검증기는 Node 표준 라이브러리만 쓴다. `package.json` 없음.

## 3. Companion 선택

`ATTACK-CLASSES.md`는 항상 있는 ordinary 클래스다 (Injection, Access control, …). 도메인 파일 10개는 reconnaissance가 그 파일의 `When to use this file` 경계를 소스에서 봤을 때만 고른다. 언어 이름만으로 고르지 않는다.

헌터 프롬프트는 선택된 블록을 그대로 복사한다. companion 이름은 카탈로그 키가 아니다.

## 4. 플랫폼 용어

- **Parent** — 런을 조율하고 공유 상태를 소유하는 에이전트.
- **Task tool** — 플랫폼의 위임 수단.
- **`research` agent** — 소스 탐색·사실 검증. 타깃 실행 없음.
- **`general` agent** — 조사 + OS 샌드박스 안 유계 로컬 실행.

`subagent_type: general`은 attack-class 헤딩에만 있다. research 역할은 본문에만 있다.

## 5. Neos에 이미 있는 것과의 관계

| Neos 목록 | 이 팩을 넣으면 |
|---|---|
| 코딩 마크다운 카탈로그 | 인덱스 한 줄 `security-audit`만. companion을 프롬프트에 나열하지 않음 |
| 팩 카탈로그 | k-skill/Univer와 같은 한 단계 루트 |
| `SubagentRuntime` | kebab 둘. `explore`는 `can_spawn=True`라 헌터로 쓰지 않음. `implement`는 타깃 worktree라 금지 |
| BaseSkill HTTP | 넣지 않음 |
| DA grader / `check_claims.v1` | 이 팩이 아님 |

이름 충돌: `skills/` 최상위와 코딩 카탈로그에 `security-audit`이 없다. 인덱스 이름과 팩 리프 이름이 같으므로 `load_skill.v1`은 코딩 인덱스를 맞아도 **팩 본문**을 돌려준다.

## 6. v0에 옮기지 않는 것

- `ParentKind.SECURITY_AUDIT`, HTTP API, 웹 피커, `BaseSkill`.
- 자식 `execute.v1` / scratch jail / fstat 승격 커널.
- 검증기의 Python 재작성.
- companion을 코딩 카탈로그 리프로 나열하는 일.
- 라이브 엔드포인트 프로브.
