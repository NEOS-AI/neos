# Claude for Financial Services — Neos 분석 문서

Anthropic `financial-services` 리포지토리(`../financial-services`, Apache 2.0)를 전수 조사한 기록이다. 원본은 Cowork 플러그인과 Claude Managed Agents API(`POST /v1/agents`)를 **같은 시스템 프롬프트·같은 스킬**로 배포하는 FSI 에이전트 하네스다.

이 디렉터리는 마이그레이션 전에 원본이 무엇을 하는지, 어떤 안전장치를 쓰는지, Neos에 무엇을 옮겨야 하는지를 고정한다.

## 읽는 순서

| 문서 | 내용 |
|---|---|
| [00-overview.md](./00-overview.md) | 듀얼 서피스, 디렉터리 구조, 인벤토리, 원본 철학 |
| [01-architecture-harness.md](./01-architecture-harness.md) | 마켓플레이스, 배포 스크립트, CMA API, 핸드오프, CI |
| [02-named-agents.md](./02-named-agents.md) | 10개 named agent 시스템 프롬프트 전수 |
| [03-managed-agent-cookbooks.md](./03-managed-agent-cookbooks.md) | `agent.yaml` + 30 leaf worker + steering |
| [04-skills-financial-analysis.md](./04-skills-financial-analysis.md) | 코어 모델링 스킬·MCP 허브 |
| [05-skills-ib-er.md](./05-skills-ib-er.md) | IB / Equity Research 버티컬 |
| [06-skills-pe-fundadmin-ops.md](./06-skills-pe-fundadmin-ops.md) | PE / Fund Admin / KYC Operations |
| [07-partners.md](./07-partners.md) | LSEG · S&P Global 파트너 플러그인 |
| [08-ms365-and-safety.md](./08-ms365-and-safety.md) | Microsoft 365 add-in 설치 + 안전장치 |
| [08b-safety-hooks-ci.md](./08b-safety-hooks-ci.md) | 훅/CI/untrusted 격리 교차검증 |
| [09-neos-migration-map.md](./09-neos-migration-map.md) | Neos 대응 지점과 이식 순서 |

에이전트별 심층 노트는 [`agents/`](./agents/) (10개 slug 전부). 스킬 클러스터 노트는 [`skills/`](./skills/).

교차검증·전수 부록:

| 문서 | 내용 |
|---|---|
| [01b-harness-scripts-api-full.md](./01b-harness-scripts-api-full.md) | 스크립트/API 전수 (1차) |
| [02b-prompt-engineering.md](./02b-prompt-engineering.md) | 10 프롬프트 골격 비교 |
| [03b-cma-yaml-matrix.md](./03b-cma-yaml-matrix.md) | 40 YAML 키·Write·schema 매트릭스 |
| [04b-skill-bundling.md](./04b-skill-bundling.md) | 스킬×에이전트 번들, 해시 드리프트 |
| [05b-mcp-manifests.md](./05b-mcp-manifests.md) | `.mcp.json` / `plugin.json` 전수 |

## 한 줄 요약

- **10 named agents**, 각각 Cowork 플러그인 + CMA cookbook.
- **49 canonical 버티컬 스킬** + meeting-prep 전용 3개(버티컬 소스 없음) + 파트너 11개.
- **오케스트레이터는 Write를 갖지 않는다**(CMA). Write는 leaf 하나.
- **비신뢰 문서는 reader만** 열고, 길이·문자집합이 제한된 JSON으로만 올라온다.
- **원장은 게시하지 않고, KYC는 승인하지 않고, 리서치는 배포하지 않는다.** 산출물은 전부 사람 서명용 스테이징.
- **에이전트끼리 직접 호출하지 않는다.** `handoff_request`를 외부 오케스트레이터가 allowlist + 스키마로 라우팅한다.
- README가 가리키는 `claude-for-financial-advisors/`는 **이 클론에 없다.**

## 원본 위치

```
/Users/yeonwoosung/Desktop/financial-services
```

Marketplace 이름: `claude-for-financial-services`.
조사 기준일: 2026-09-25.
