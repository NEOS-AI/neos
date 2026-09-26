# 01. 아키텍처와 하네스

원본은 애플리케이션 런타임이 아니라 **파일 기반 에이전트 정의 + 배포 변환기**다. 실행은 Cowork/Claude Code 또는 Claude Managed Agents API가 맡는다.

## 1. Marketplace

`.claude-plugin/marketplace.json`

- `name`: `claude-for-financial-services`
- `owner.name`: Matt Piccolella
- 등록 플러그인 19개: 6 vertical + 10 named agents + `lseg` + `sp-global` + `claude-for-msft-365-install`

각 엔트리: `{name, displayName, source, description}`. `source`는 상대 경로이고, `check.py`는 그 아래 `.claude-plugin/plugin.json` 존재를 확인한다.

`plugin.json`은 거의 전부 `{name, version, description, author}`. agents/skills/commands/hooks 배열은 **없다.** Cowork는 디렉터리 컨벤션으로 발견한다.

- `agents/*.md` → named agent
- `skills/*/SKILL.md` → 스킬
- `commands/*.md` → slash command
- `hooks/hooks.json` → 훅 (4개 전부 `{"hooks": {}}`)
- `.mcp.json` → MCP 서버

S&P만 `homepage`, `repository`, `license`, `keywords`를 추가로 갖는다. MS365 install은 author email이 `support@anthropic.com`.

버전 예: named agents `0.1.0`–`0.1.1`, IB `0.2.1`, MS365 `0.1.13`, LSEG `1.0.0`, S&P `1.0.1`.

## 2. Skill sync

`scripts/sync-agent-skills.py`

1. `vertical-plugins/*/skills/*`를 이름 → 경로 인덱스로 만든다.
2. `agent-plugins/*/skills/*` 각 디렉터리를 같은 이름의 vertical 소스로 `rmtree` + `copytree`.
3. vertical 소스가 없으면 WARN + exit 1.

에이전트별 번들 목록은 하드코딩되지 않는다. **디렉터리에 무엇이 있느냐가 매핑이다.**

해시 비교 결과(조사 시점): 번들 51개 중 48개가 vertical과 바이트 동일, drift 0. 고아 3개 = meeting-prep의 `client-report`, `client-review`, `investment-proposal`.

`check.py` §4b는 `filecmp.dircmp`로 같은 드리프트를 잡고, §4b2는 프롬프트 본문의 `` `kebab-case` `` 스킬 이름이 번들에 있는지 검사한다.

## 3. CMA deploy — `deploy-managed-agent.sh`

```
scripts/deploy-managed-agent.sh <slug> [--dry-run]
```

환경:

| 변수 | 역할 |
|---|---|
| `ANTHROPIC_API_KEY` | dry-run이 아니면 필수 |
| `ANTHROPIC_API_BASE` | 기본 `https://api.anthropic.com` |
| `REPO_SLUG` | git remote basename, cookbook 태그 |
| `SKILL_TITLE_PREFIX` | skill display_title 접두 |
| `DEPLOY_DEBUG` | name/callable_agents 덤프 |
| 에이전트별 MCP URL | `CAPIQ_MCP_URL`, `DALOOPA_MCP_URL`, `FACTSET_MCP_URL`, `CRM_MCP_URL`, `GL_MCP_URL`, `SUBLEDGER_MCP_URL`, `SCREENING_MCP_URL`, `PORTFOLIO_MCP_URL`, `NAV_MCP_URL` |

헤더:

```
x-api-key: $ANTHROPIC_API_KEY
anthropic-version: 2023-06-01
anthropic-beta: managed-agents-2026-04-01   # POST /v1/agents
anthropic-beta: skills-2025-10-02           # POST /v1/skills (multipart)
```

변환 순서:

1. `${ENV}` 치환. 값 charset `^[A-Za-z0-9._/:@-]*$`. 벗어나면 refuse.
2. `skills.from_plugin` → 해당 플러그인 `skills/*/` 전부 upload 목록. **구현은 `jq … | head -1`이라 `from_plugin`이 여러 개면 첫 항목만 팽창한다.** 현재 cookbook은 항목이 하나라 동작한다.
3. `system.file`이면 파일 전체 `cat` (YAML frontmatter 포함) + `\n\n` + `system.append`.
4. 각 스킬 디렉터리를 zip → `POST /v1/skills` → `{type: custom, skill_id, version: latest}`.
5. `callable_agents[].manifest`를 **재귀 `create_agent`** (leaf 먼저).
6. `del(.output_schema)`, `metadata.anthropic_cookbook = $REPO_SLUG/$ROLE`.
7. `POST /v1/agents`.

`--dry-run`은 POST 없이 resolved JSON bodies를 “subagents first, orchestrator last”로 출력한다.

헤더 주석의 “thin validation wrapper”는 스크립트에 구현되어 있지 않다. `output_schema`는 지워지고, 검증은 `validate.py`가 별도 CLI로 한다.

`callable_agents`는 research preview, **위임 1단**. leaf YAML은 전부 `callable_agents: []`. `test-cookbooks.sh`는 dry-run body에서 서브에이전트가 자식을 가지면 fail.

## 4. Manifest → API 필드

Cookbook YAML에 **실제로 있는** 키:

Orchestrator: `name`, `model`, `system.{file,append}`, `tools`, `mcp_servers`, `skills.from_plugin`, `callable_agents.manifest`

Leaf: `name`, `model`, `system.text`, `tools`, `mcp_servers`, `skills.path`, `callable_agents: []`, 선택적 `output_schema`

Cookbook에 **없는** 키: `permissions`, `effort`, `timeout`, `memory`. `metadata`는 deploy 스크립트가 주입.

도구 타입:

- `agent_toolset_20260401` — `default_config.enabled: false` (default-deny). 켜진 이름: `read`, `grep`, `glob`(오케스트레이터만), `write`, `edit`, `bash`(pitch-modeler, model-builder-builder만).
- `mcp_toolset` — `mcp_server_name` + `default_config.enabled: true`
- `mcp_servers[]` — `{type: url, name, url: "${ENV}"}`

## 5. 크로스 에이전트 핸드오프 — `orchestrate.py`

Named agents는 서로를 `callable_agents`로 부르지 않는다. 필요하면 출력에 JSON blob을 남긴다.

```
{"type": "handoff_request", "target_agent": "<slug>", "payload": {"event": "...", "context_ref": "..."}}
```

스크립트는 `message_delta` 텍스트에서 정규식으로 추출한다.

```
HANDOFF_RE = r'\{"type":\s*"handoff_request".*?\}'
```

완화:

1. `target_agent` hard allowlist — 10 named slugs만.
2. payload JSON Schema: `event` (string, max 2000), `context_ref` (optional, max 256, charset `^[A-Za-z0-9 ._/:#-]+$`), `additionalProperties: false`.

그다음 `client.beta.agents.sessions.steer(agent_id=target_id, input=payload.event)`.

`context_ref`는 스키마에 있지만 **steer 입력으로 전달되지 않는다.** 정규식은 첫 `}`까지라 nested JSON이면 잘린다.

위협 모델 (스크립트 헤더 원문 요지): handoff는 오케스트레이터 텍스트에 나타나고, 그 텍스트는 비신뢰 문서 reader의 다운스트림이다. 공격자가 문서에 `handoff_request` blob을 심으면 그대로 파싱될 수 있다. 프로덕션은 모델이 문서 텍스트를 인용해서 만들 수 없는 **typed tool call / SSE event**를 쓰라고 한다.

관측된 핸드오프 엣지 (cookbook README):

| From | To |
|---|---|
| pitch-agent, earnings-reviewer, market-researcher | model-builder |
| gl-reconciler | month-end-closer |
| valuation-reviewer | gl-reconciler |

이 스크립트는 “REFERENCE ONLY — replace with Temporal, Airflow, Guidewire event bus.”

세션 API: `client.beta.agents.sessions.stream(session_id=…)` — SDK 타입 스텁 미포함, `# type: ignore`.

## 6. `validate.py`

```
validate.py <output.json> <schema.json|schema.yaml>
```

jsonschema validate. CMA가 structured output을 강제하지 않기 때문에 reader와 오케스트레이터 사이에서 하네스가 돌린다. 스키마는 leaf YAML `output_schema:`에 있다. 문자열은 길이 캡 + 문자집합 제한으로 “injected instructions cannot survive intact.”

`output_schema`가 있는 leaf 10개: 비신뢰 reader 8 + 신뢰 MCP puller 2 (`pitch-researcher`, `model-data-puller`).

## 7. `check.py` 규칙

1. `managed-agent-cookbooks/**/*.yaml` parse
2. marketplace.json, 모든 plugin.json, steering-examples.json parse
3. `agent-plugins/*/agents/*.md` frontmatter `name` + `description`
4. `system.file`, `skills.path`, `skills.from_plugin`, `callable_agents.manifest` 경로 존재
4b. 번들 스킬 = vertical 소스 (dircmp)
4b2. 프롬프트가 언급한 kebab-case 스킬이 자기 번들에 존재
4c. marketplace `source` → plugin.json
5. cookbook마다 `agent.yaml`, `README.md`, `steering-examples.json`
6. `.ps1`은 BOM 없는 non-ASCII 금지 (PS 5.1 ANSI 디코드 → `"` 삽입 → parse 실패)

부수 효과: `git config core.hooksPath .githooks`를 best-effort로 설치.

`.mcp.json`은 검사하지 않는다. 그래서 financial-analysis MCP의 콤마 누락이 CI를 통과할 수 있다.

## 8. Version bump

플러그인 `version`이 이미 설치한 사용자에게 업데이트를 밀어주는 게이트다.

- `.githooks/pre-commit` → `version_bump.py --apply` : 스테이징된 플러그인을 base 대비 패치 +1, 이미 앞서 있으면 그대로. 브랜치당 한 번.
- GH Action `version-bump.yml` → `--check` 백스톱.
- Bypass: `git commit --no-verify`.

## 9. CI

| Workflow | 하는 일 |
|---|---|
| `plugin-validate.yml` | Claude CLI 2.1.143 `claude plugin validate` marketplace + `plugins/**/plugin.json`. **MS365 install은 제외.** |
| `version-bump.yml` | PR에서 플러그인 버전 검사 |
| `secret-scan.yml` | gitleaks v8.28.0 (tarball SHA pin) + `.ant.dev` / `antspace.dev` / `anthropic-internal` / `go/` 스크럽 |

`PII` 스캐너는 없다. `check.py`와 `test-cookbooks.sh`는 **CI 워크플로에 없다** (로컬/`pre-commit` 관례). `check.py` 독스트링은 옛 경로 `managed-agents/`를 가리킨다. README가 말하는 `mcp-categories.json`은 디스크에 없다.

## 10. Steering 이벤트

`steering-examples.json`은 `[{event, description}]` 배열뿐이다. 키가 그 둘뿐이다. 총 29 이벤트 (9개 에이전트 × 3, statement-auditor × 2).

문법은 자연어 한 줄. 예:

```
Build pitch book: target CRWD, acquirer PANW, thesis: platform consolidation in security
Process earnings: NVDA Q1-FY27
Reconcile GL vs subledger, trade date 2026-04-30, classes: equities, fixed-income, derivatives
Screen onboarding packet PKT-2026-00318
Close entity US-OPCO for period 2026-04
```

커버리지 리스트 팬아웃은 **오케스트레이션 레이어가 티커당 세션을 연다.** 에이전트 하나가 리스트를 돌리지 않는다.

## 11. MCP 허브

코어 커넥터는 `plugins/vertical-plugins/financial-analysis/.mcp.json` 한곳. HTTP URL만 있고 인증 스키마는 없다.

| Key | URL |
|---|---|
| daloopa | `https://mcp.daloopa.com/server/mcp` |
| morningstar | `https://mcp.morningstar.com/mcp` |
| sp-global | `https://kfinance.kensho.com/integrations/mcp` |
| factset | `https://mcp.factset.com/mcp` |
| moodys | `https://api.moodys.com/genai-ready-data/m1/mcp` |
| mtnewswire | `https://vast-mcp.blueskyapi.com/mtnewswires` |
| aiera | `https://mcp-pub.aiera.com` |
| lseg | `https://api.analytics.lseg.com/lfa/mcp` |
| pitchbook | `https://premium.mcp.pitchbook.com/mcp` |
| chronograph | `https://ai.chronograph.pe/mcp` |
| egnyte | `https://mcp-server.egnyte.com/mcp` |
| box | `https://mcp.box.com` |

이 파일은 `egnyte` 다음 콤마가 빠져 **invalid JSON**이다.

파트너 플러그인이 같은 벤더를 다시 선언한다.

- LSEG partner: `https://api.analytics.lseg.com/lfa/mcp/server-cl` (코어와 path가 다름)
- S&P partner: 같은 Kensho URL, 키 이름만 `spglobal` vs `sp-global`

CMA cookbook MCP는 코어 `.mcp.json`과 **다른 이름**을 쓴다. 내부 시스템용 placeholder:

| Cookbook MCP name | Env |
|---|---|
| capiq | `CAPIQ_MCP_URL` |
| daloopa | `DALOOPA_MCP_URL` |
| factset | `FACTSET_MCP_URL` |
| crm | `CRM_MCP_URL` |
| internal-gl | `GL_MCP_URL` |
| subledger | `SUBLEDGER_MCP_URL` |
| screening | `SCREENING_MCP_URL` |
| portfolio | `PORTFOLIO_MCP_URL` |
| nav | `NAV_MCP_URL` |

IB / PE `.mcp.json`은 `{"mcpServers": {}}`. fund-admin / operations는 파일 자체가 없다. 스킬 본문은 그래도 `internal-gl`, `subledger`, `nav`, `screening`을 이름으로 부른다.

## 12. Neos가 복제해야 하는 하네스 표면

1. 스킬 카탈로그: `SKILL.md` frontmatter `name`+`description`, 디렉터리 번들, 소스/카피 드리프트 검사.
2. Named agent: 짧은 시스템 프롬프트 + 스킬 목록 + 도구 default-deny.
3. Depth-1 callable workers, Write는 leaf 하나.
4. Reader `output_schema` 검증을 부모 소비 전에 수행.
5. 세션 + steer (후속 자연어 이벤트).
6. 에이전트 간 핸드오프는 모델 인용 JSON이 아니라 typed event.
7. `./out/` 아티팩트 수집.
8. MCP를 에이전트별로 최소 권한 attach.
9. Human sign-off 스테이징을 런타임 계약으로.
