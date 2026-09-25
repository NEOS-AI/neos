# financial-services MCP 서버 및 plugin 매니페스트 분석

조사 경로: `/Users/yeonwoosung/Desktop/financial-services`  
조사일: 2026-09-25  
범위: 저장소 내 모든 `.mcp.json`, 모든 `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, 루트 `README.md` MCP 표, `plugins/partner-built/lseg/CONNECTORS.md`.  
방법: 파일 목록은 `find`로 확정. JSON 파싱은 `json.loads`. 존재하지 않는 경로는 `ls`로 확인. 발명하지 않음.

---

## 1. 파일 목록 (실재)

`.mcp.json` 5개:

- `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/.mcp.json`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/investment-banking/.mcp.json`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/private-equity/.mcp.json`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/lseg/.mcp.json`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/spglobal/.mcp.json`

`plugin.json` 19개 (모두 `.claude-plugin/plugin.json`):

- `claude-for-msft-365-install/.claude-plugin/plugin.json`
- `plugins/agent-plugins/{earnings-reviewer,gl-reconciler,kyc-screener,market-researcher,meeting-prep-agent,model-builder,month-end-closer,pitch-agent,statement-auditor,valuation-reviewer}/.claude-plugin/plugin.json`
- `plugins/partner-built/{lseg,spglobal}/.claude-plugin/plugin.json`
- `plugins/vertical-plugins/{equity-research,financial-analysis,fund-admin,investment-banking,operations,private-equity}/.claude-plugin/plugin.json`

마켓플레이스:

- `/Users/yeonwoosung/Desktop/financial-services/.claude-plugin/marketplace.json`

파트너 커넥터 문서:

- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/lseg/CONNECTORS.md` (저장소에서 `CONNECTORS.md`는 이 파일 1개뿐)
- `plugins/partner-built/spglobal/` 에는 `CONNECTORS.md` 없음

`.mcp.json`이 **없는** 플러그인 디렉터리:

- 모든 `plugins/agent-plugins/*` (10개)
- `plugins/vertical-plugins/equity-research`
- `plugins/vertical-plugins/fund-admin`
- `plugins/vertical-plugins/operations`
- `claude-for-msft-365-install`

CLAUDE.md Key Files에 적힌 `mcp-categories.json`은 저장소 루트에 없음 (`ls: .../mcp-categories.json: No such file or directory`).

---

## 2. MCP 서버 전체 (소유 플러그인, type, URL)

아래는 각 `.mcp.json`에 적힌 그대로. 모든 비어 있지 않은 엔트리는 `"type": "http"` 이다. stdio/sse 등 다른 type은 없음.

### 2.1 `financial-analysis` (core) — 파싱 실패, 키는 텍스트상 12개

파일: `plugins/vertical-plugins/financial-analysis/.mcp.json`  
`plugin.json` name: `"financial-analysis"`  
marketplace name: `"financial-analysis"`

`json.loads` 결과:

```
PARSE_ERROR JSONDecodeError Expecting ',' delimiter: line 47 column 5 (char 1100)
```

문법 오류가 있어도 파일에 적힌 서버 키/URL은 아래와 같다.

| 서버 키 | type | url | 소유 플러그인 |
|---|---|---|---|
| `daloopa` | `http` | `https://mcp.daloopa.com/server/mcp` | financial-analysis |
| `morningstar` | `http` | `https://mcp.morningstar.com/mcp` | financial-analysis |
| `sp-global` | `http` | `https://kfinance.kensho.com/integrations/mcp` | financial-analysis |
| `factset` | `http` | `https://mcp.factset.com/mcp` | financial-analysis |
| `moodys` | `http` | `https://api.moodys.com/genai-ready-data/m1/mcp` | financial-analysis |
| `mtnewswire` | `http` | `https://vast-mcp.blueskyapi.com/mtnewswires` | financial-analysis |
| `aiera` | `http` | `https://mcp-pub.aiera.com` | financial-analysis |
| `lseg` | `http` | `https://api.analytics.lseg.com/lfa/mcp` | financial-analysis |
| `pitchbook` | `http` | `https://premium.mcp.pitchbook.com/mcp` | financial-analysis |
| `chronograph` | `http` | `https://ai.chronograph.pe/mcp` | financial-analysis |
| `egnyte` | `http` | `https://mcp-server.egnyte.com/mcp` | financial-analysis |
| `box` | `http` | `https://mcp.box.com` | financial-analysis (문법 깨진 엔트리) |

원문 전체:

```json
{
  "mcpServers": {
    "daloopa": {
      "type": "http",
      "url": "https://mcp.daloopa.com/server/mcp"
    },
    "morningstar": {
      "type": "http",
      "url": "https://mcp.morningstar.com/mcp"
    },
    "sp-global": {
      "type": "http",
      "url": "https://kfinance.kensho.com/integrations/mcp"
    },
    "factset": {
      "type": "http",
      "url": "https://mcp.factset.com/mcp"
    },
    "moodys": {
      "type": "http",
      "url": "https://api.moodys.com/genai-ready-data/m1/mcp"
    },
    "mtnewswire": {
      "type": "http",
      "url": "https://vast-mcp.blueskyapi.com/mtnewswires"
    },
    "aiera": {
      "type": "http",
      "url": "https://mcp-pub.aiera.com"
    },
    "lseg": {
      "type": "http",
      "url": "https://api.analytics.lseg.com/lfa/mcp"
    },
    "pitchbook": {
      "type": "http",
      "url": "https://premium.mcp.pitchbook.com/mcp"
    },
    "chronograph": {
      "type": "http",
      "url": "https://ai.chronograph.pe/mcp"
    },
    "egnyte": {
      "type": "http",
      "url": "https://mcp-server.egnyte.com/mcp"
    }
    "box": {
      "type": "http",
      "url": "https://mcp.box.com"
  }
}
```

### 2.2 `lseg` (partner)

파일: `plugins/partner-built/lseg/.mcp.json` — 파싱 OK.

```json
{
  "mcpServers": {
    "lseg": {
      "type": "http",
      "url": "https://api.analytics.lseg.com/lfa/mcp/server-cl"
    }
  }
}
```

| 서버 키 | type | url | 소유 플러그인 |
|---|---|---|---|
| `lseg` | `http` | `https://api.analytics.lseg.com/lfa/mcp/server-cl` | lseg (partner-built) |

### 2.3 `sp-global` (partner, 디렉터리명은 `spglobal`)

파일: `plugins/partner-built/spglobal/.mcp.json` — 파싱 OK.  
서버 키는 `spglobal` (하이픈 없음). plugin.json / marketplace name은 `sp-global`.

```json
{
  "mcpServers": {
    "spglobal": {
      "type": "http",
      "url": "https://kfinance.kensho.com/integrations/mcp"
    }
  }
}
```

| 서버 키 | type | url | 소유 플러그인 |
|---|---|---|---|
| `spglobal` | `http` | `https://kfinance.kensho.com/integrations/mcp` | sp-global (partner-built/spglobal) |

### 2.4 `investment-banking` — 빈 객체

파일: `plugins/vertical-plugins/investment-banking/.mcp.json` — 파싱 OK.

```json
{
  "mcpServers": {}
}
```

서버 0개.

### 2.5 `private-equity` — 빈 객체

파일: `plugins/vertical-plugins/private-equity/.mcp.json` — 파싱 OK.

```json
{
  "mcpServers": {}
}
```

서버 0개.

### 2.6 소유 플러그인별 요약

| 플러그인 (plugin.json name) | `.mcp.json` 경로 | 서버 수 | 비고 |
|---|---|---|---|
| financial-analysis | `plugins/vertical-plugins/financial-analysis/.mcp.json` | 텍스트상 12, JSON 무효 | core |
| investment-banking | `plugins/vertical-plugins/investment-banking/.mcp.json` | 0 | `{}` |
| private-equity | `plugins/vertical-plugins/private-equity/.mcp.json` | 0 | `{}` |
| lseg | `plugins/partner-built/lseg/.mcp.json` | 1 (`lseg`) | URL이 core와 다름 |
| sp-global | `plugins/partner-built/spglobal/.mcp.json` | 1 (`spglobal`) | 키 철자가 core와 다름, URL은 동일 |
| 그 외 14개 plugin.json | 없음 | — | agent 10 + equity-research + fund-admin + operations + claude-for-msft-365-install |

---

## 3. JSON 문법 문제 (`financial-analysis/.mcp.json`)

`json.loads` 에러: `Expecting ',' delimiter: line 47 column 5 (char 1100)`.

문제 위치 원문:

```json
    "egnyte": {
      "type": "http",
      "url": "https://mcp-server.egnyte.com/mcp"
    }
    "box": {
      "type": "http",
      "url": "https://mcp.box.com"
  }
}
```

확인된 문법 결함:

1. **`egnyte` 객체 닫는 `}` 뒤에 콤마 없음.** 그 다음 토큰이 `"box"`이므로 parser가 line 47 column 5에서 `Expecting ',' delimiter`를 낸다. (사용자 지적이 파일과 일치.)
2. **`box` 객체의 닫는 `}`가 없음.** `"url": "https://mcp.box.com"` 다음 `}`는 들여쓰기가 2칸이라 `mcpServers`를 닫는 것으로 읽히고, 그다음 `}`가 루트를 닫는다. 콤마만 넣어도 `box` 미종결로 여전히 무효.

다른 4개 `.mcp.json`은 `json.loads` 성공. 19개 `plugin.json`과 `marketplace.json`도 읽기 성공 (본문에서 직접 로드).

---

## 4. 중복 (core vs partner)

README는 커넥터가 financial-analysis에 중앙화되어 있다고 적는다:

> All connectors are centralized in the **financial-analysis** core plugin and shared across the rest.

실제로는 partner 플러그인이 같은 벤더를 다시 선언한다.

### 4.1 LSEG

| 위치 | 서버 키 | url |
|---|---|---|
| core `financial-analysis/.mcp.json` | `lseg` | `https://api.analytics.lseg.com/lfa/mcp` |
| partner `lseg/.mcp.json` | `lseg` | `https://api.analytics.lseg.com/lfa/mcp/server-cl` |
| README MCP 표 | LSEG | `https://api.analytics.lseg.com/lfa/mcp` |

키는 둘 다 `lseg`. URL은 **동일하지 않음**. partner 쪽이 `/server-cl` suffix. README 표는 core URL과 같다.

partner README/CONNECTORS.md는 서버를 **LFA MCP Server** 라고만 부르고, URL 문자열은 CONNECTORS.md에 없음. URL은 `.mcp.json`에만 있다.

### 4.2 S&P Global

| 위치 | 서버 키 | url |
|---|---|---|
| core `financial-analysis/.mcp.json` | `sp-global` | `https://kfinance.kensho.com/integrations/mcp` |
| partner `spglobal/.mcp.json` | `spglobal` | `https://kfinance.kensho.com/integrations/mcp` |
| README MCP 표 | S&P Global | `https://kfinance.kensho.com/integrations/mcp` |

URL은 세 곳 모두 동일. 서버 **키 철자만 다름**: core/README 쪽 하이픈 `sp-global`, partner `.mcp.json`은 `spglobal`. plugin.json name과 marketplace name은 `sp-global`, 디렉터리는 `spglobal`.

### 4.3 그 외 겹침

core에만 있고 partner `.mcp.json`에는 없는 키: `daloopa`, `morningstar`, `factset`, `moodys`, `mtnewswire`, `aiera`, `pitchbook`, `chronograph`, `egnyte`, `box`.

IB/PE `.mcp.json`은 빈 객체라 서버 키 충돌 없음.

---

## 5. README MCP 표 vs `.mcp.json`

README `## MCP Integrations` 표 (12행):

| Provider | URL |
|---|---|
| Daloopa | `https://mcp.daloopa.com/server/mcp` |
| Morningstar | `https://mcp.morningstar.com/mcp` |
| S&P Global | `https://kfinance.kensho.com/integrations/mcp` |
| FactSet | `https://mcp.factset.com/mcp` |
| Moody's | `https://api.moodys.com/genai-ready-data/m1/mcp` |
| MT Newswires | `https://vast-mcp.blueskyapi.com/mtnewswires` |
| Aiera | `https://mcp-pub.aiera.com` |
| LSEG | `https://api.analytics.lseg.com/lfa/mcp` |
| PitchBook | `https://premium.mcp.pitchbook.com/mcp` |
| Chronograph | `https://ai.chronograph.pe/mcp` |
| Egnyte | `https://mcp-server.egnyte.com/mcp` |
| Box | `https://mcp.box.com` |

같은 README Vertical Plugins 표는 financial-analysis를 **「All 11 data connectors」** 라고 적는다. MCP 표는 12행이고, core `.mcp.json` 키도 텍스트상 12개(box 포함). 11 vs 12 불일치.

README How It Fits Together는 커넥터 위치를 `plugins/vertical-plugins/financial-analysis/.mcp.json` 한 곳으로만 적는다. partner `lseg/.mcp.json`, `spglobal/.mcp.json`은 그 표에 없음.

---

## 6. partner CONNECTORS.md (LSEG만)

경로: `plugins/partner-built/lseg/CONNECTORS.md`

문서가 말하는 연결:

> This plugin connects to the **LFA MCP Server**, which provides financial analytics tools from LSEG (London Stock Exchange Group). All tools are served by a single MCP server — no additional connectors are needed.

URL은 이 파일에 없고 `.mcp.json`의 `https://api.analytics.lseg.com/lfa/mcp/server-cl` 과 README의 `https://api.analytics.lseg.com/lfa/mcp` 가 따로 있다.

CONNECTORS.md 카테고리/툴 (문서 표 그대로):

| Category | Placeholder | Tools |
|----------|-------------|-------|
| Bond Pricing | `~~bond-pricing` | `bond_price`, `bond_future_price` |
| FX Pricing | `~~fx-pricing` | `fx_spot_price`, `fx_forward_price` |
| Interest Rate Curves | `~~ir-curves` | `interest_rate_curve`, `inflation_curve` |
| Credit Curves | `~~credit-curves` | `credit_curve` |
| FX Curves | `~~fx-curves` | `fx_forward_curve` |
| Options | `~~options` | `option_value`, `option_template_list` |
| Swaps | `~~swaps` | `ir_swap` |
| Volatility Surfaces | `~~volatility` | `fx_vol_surface`, `equity_vol_surface` |
| Quantitative Analytics | `~~qa` | `qa_ibes_consensus`, `qa_company_fundamentals`, `qa_historical_equity_price`, `qa_macroeconomic` |
| Time Series | `~~time-series` | `tscc_historical_pricing_summaries` |
| Fixed Income Analytics | `~~yieldbook` | `yieldbook_bond_reference`, `yieldbook_cashflow`, `yieldbook_scenario`, `fixed_income_risk_analytics` |

`plugins/partner-built/spglobal/` 에는 CONNECTORS.md가 없다. spglobal README는 MCP를 문장으로만 언급하고 `.mcp.json` URL을 인용하지 않는다:

> The LLM-ready API is easy to integrate in Claude or other applications via its MCP server.

---

## 7. plugin.json 스키마 필드 인벤토리

조사한 필드: `name`, `version`, `description`, `author`, `keywords`, `agents`, `skills`, `commands`.  
19개 파일 전부 직접 읽음. 어떤 `plugin.json`에도 `agents`, `skills`, `commands` 키는 없다 (디렉터리 `agents/`, `skills/`, `commands/` 존재와 무관).

### 7.1 필드 출현

| 필드 | 있는 플러그인 수 | 없는 플러그인 |
|---|---|---|
| `name` | 19/19 | — |
| `version` | 19/19 | — |
| `description` | 19/19 | — |
| `author` | 19/19 (`{"name": ...}` 객체) | — |
| `author.email` | 2/19 | 나머지 17 |
| `keywords` | 1/19 (`sp-global`만) | 나머지 18 |
| `agents` | 0/19 | 전부 |
| `skills` | 0/19 | 전부 |
| `commands` | 0/19 | 전부 |

`plugin.json`에만 있고 요청 목록 밖인 추가 키 (sp-global만): `homepage`, `repository`, `license`.

### 7.2 플러그인별 값

author.name 기본값은 대다수가 `"Anthropic FSI"`. 예외만 아래 표에 표시.

| name | version | author.name | author.email | keywords | agents | skills | commands | 추가 키 |
|---|---|---|---|---|---|---|---|---|
| financial-analysis | 0.1.1 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| investment-banking | 0.2.1 | Anthropic | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| equity-research | 0.1.2 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| private-equity | 0.1.2 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| fund-admin | 0.1.0 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| operations | 0.1.0 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| pitch-agent | 0.1.1 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| market-researcher | 0.1.1 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| earnings-reviewer | 0.1.1 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| meeting-prep-agent | 0.1.1 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| model-builder | 0.1.0 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| gl-reconciler | 0.1.0 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| kyc-screener | 0.1.0 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| valuation-reviewer | 0.1.1 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| month-end-closer | 0.1.0 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| statement-auditor | 0.1.0 | Anthropic FSI | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| lseg | 1.0.0 | LSEG | 없음 | 없음 | 없음 | 없음 | 없음 | — |
| sp-global | 1.0.1 | Kensho Technologies | spglobal-agent-skills-maintainers@kensho.com | 있음 (아래 인용) | 없음 | 없음 | 없음 | homepage, repository, license |
| claude-for-msft-365-install | 0.1.13 | Anthropic | support@anthropic.com | 없음 | 없음 | 없음 | 없음 | — |

최소 형태 인용 (대다수 agent/vertical과 동일 스키마):

```json
{
  "name": "financial-analysis",
  "version": "0.1.1",
  "description": "Core financial modeling and analysis tools: DCF, comps, LBO, 3-statement models, competitive analysis, and deck QC",
  "author": {
    "name": "Anthropic FSI"
  }
}
```

`keywords`가 있는 유일한 파일 `plugins/partner-built/spglobal/.claude-plugin/plugin.json`:

```json
{
  "name": "sp-global",
  "description": "S&P Global - Financial data and analytics skills including company tearsheets, earnings previews, and transaction summaries",
  "version": "1.0.1",
  "author": {
    "name": "Kensho Technologies",
    "email": "spglobal-agent-skills-maintainers@kensho.com"
  },
  "homepage": "https://www.marketplace.spglobal.com/en/solutions/kensho-llm-ready-api-%28a156fe9f-5564-4f60-a624-95d8645dc98f%29",
  "repository": "https://github.com/kensho-technologies/spglobal-agent-skills",
  "license": "Apache-2.0",
  "keywords": [
    "sp-global",
    "finance",
    "capital-iq",
    "tearsheets",
    "earnings",
    "transactions",
    "excel"
  ]
}
```

email이 있는 다른 파일 `claude-for-msft-365-install/.claude-plugin/plugin.json`:

```json
{
  "name": "claude-for-msft-365-install",
  "description": "Provision direct cloud access (Vertex AI, Bedrock, Azure AI Foundry, or LLM gateway) for the Claude Office add-in. Generates the customized add-in manifest, walks through Azure admin consent, and writes per-user config via Microsoft Graph extension attributes.",
  "version": "0.1.13",
  "author": {
    "name": "Anthropic",
    "email": "support@anthropic.com"
  }
}
```

참고: marketplace description은 "Vertex AI, Bedrock, or LLM gateway" / "Claude Microsoft 365 add-in". plugin.json description은 "Vertex AI, Bedrock, Azure AI Foundry, or LLM gateway" / "Claude Office add-in". 문구가 다름.

CLAUDE.md는 `plugin.json`을 "name, description, version, and component discovery settings"라고 하지만, 실제 19개 파일에 component discovery 키(`agents`/`skills`/`commands`)는 없다. 컴포넌트는 디렉터리 관례로만 존재한다.

---

## 8. marketplace.json 등록 vs 실제 플러그인

파일: `.claude-plugin/marketplace.json`

루트:

```json
{
  "name": "claude-for-financial-services",
  "owner": {
    "name": "Matt Piccolella"
  },
  "plugins": [ ... 19 entries ... ]
}
```

각 엔트리 키 union: `name`, `displayName`, `source`, `description`. version 없음.

등록 19개:

| marketplace name | source |
|---|---|
| financial-analysis | `./plugins/vertical-plugins/financial-analysis` |
| investment-banking | `./plugins/vertical-plugins/investment-banking` |
| equity-research | `./plugins/vertical-plugins/equity-research` |
| private-equity | `./plugins/vertical-plugins/private-equity` |
| fund-admin | `./plugins/vertical-plugins/fund-admin` |
| operations | `./plugins/vertical-plugins/operations` |
| pitch-agent | `./plugins/agent-plugins/pitch-agent` |
| market-researcher | `./plugins/agent-plugins/market-researcher` |
| earnings-reviewer | `./plugins/agent-plugins/earnings-reviewer` |
| meeting-prep-agent | `./plugins/agent-plugins/meeting-prep-agent` |
| model-builder | `./plugins/agent-plugins/model-builder` |
| gl-reconciler | `./plugins/agent-plugins/gl-reconciler` |
| kyc-screener | `./plugins/agent-plugins/kyc-screener` |
| valuation-reviewer | `./plugins/agent-plugins/valuation-reviewer` |
| month-end-closer | `./plugins/agent-plugins/month-end-closer` |
| statement-auditor | `./plugins/agent-plugins/statement-auditor` |
| lseg | `./plugins/partner-built/lseg` |
| sp-global | `./plugins/partner-built/spglobal` |
| claude-for-msft-365-install | `./claude-for-msft-365-install` |

대조:

- marketplace 19개 source 경로 모두 해당 디렉터리에 `plugin.json`이 있다.
- `plugin.json`이 있는 19개 디렉터리는 모두 marketplace에 있다.
- marketplace에만 있고 디스크에 없는 등록은 없다 (19↔19).
- README Vertical Plugins 표의 `claude-for-financial-advisors` 는 marketplace에 **없다**.

---

## 9. 누락: `claude-for-financial-advisors`

README Vertical Plugins 표 원문:

```
| **[claude-for-financial-advisors](./claude-for-financial-advisors)** | Advisor workflows: meeting prep and follow-up, compliance pre-check, prospect intake, rebalance review, alts and estate briefs, on live data from the advisor's CRM, portfolio, planning, and estate platforms. |
```

확인:

- `ls /Users/yeonwoosung/Desktop/financial-services/claude-for-financial-advisors` → `No such file or directory`
- marketplace.json에 이름 없음 (`grep` 무매치)
- `plugin.json` 없음
- `.mcp.json` 없음

README 링크 `./claude-for-financial-advisors` 는 깨진 상대경로. 저장소 레이아웃 트리에도 이 디렉터리가 없다.

---

## 10. 기타 관측 (파일에 있는 것만)

- README: 「All 11 data connectors」 vs MCP 표 12행 vs core `.mcp.json` 키 12개.
- CLAUDE.md 트리: 모든 vertical이 `.mcp.json`을 가진 것처럼 그림. 실제 `.mcp.json`이 있는 vertical은 financial-analysis, investment-banking, private-equity 세 곳뿐.
- CLAUDE.md Key Files의 `mcp-categories.json` 파일은 저장소에 없음.
- IB/PE `.mcp.json`은 빈 `mcpServers` 객체. equity-research / fund-admin / operations는 `.mcp.json` 자체 없음.
- agent-plugins 10개는 `.mcp.json` 없음. 커넥터는 README대로 core를 공유한다는 설명만 있고, agent 매니페스트에 MCP 선언은 없다.
