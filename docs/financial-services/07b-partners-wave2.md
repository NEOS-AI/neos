# 파트너 플러그인(LSEG, S&P Global) 분석

범위: `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/lseg/` 및 `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/spglobal/`의 모든 파일. 비교용으로 리포 루트 `README.md`, `CLAUDE.md`, `LICENSE`, `.claude-plugin/marketplace.json`, `plugins/vertical-plugins/`의 `plugin.json` / `.mcp.json`만 인용. 문서에 없는 내용은 추정하지 않는다.

---

## Anthropic 버티컬과 파트너 플러그인의 차이

리포는 세 계층을 구분한다.

> `partner-built/` — partner plugins (LSEG, S&P Global)
>
> — `CLAUDE.md`

> `plugins/agent-plugins/` — named agents — one self-contained plugin each
> `plugins/vertical-plugins/` — FSI verticals — skill sources, commands, MCPs
> `plugins/partner-built/` — Partner-authored plugins (LSEG, S&P Global)
>
> — `README.md`

버티컬은 “스킬 소스 + 슬래시 커맨드 + 데이터 커넥터를 FSI 버티컬별로 묶은 것”이고, 에이전트는 그 스킬을 번들한 named workflow다.

> **Vertical plugins** — the underlying skills, slash commands, and data connectors, bundled by FSI vertical.
>
> **Skills** — Domain expertise, conventions, and step-by-step methods Claude draws on automatically when relevant. Authored once in the verticals; each agent bundles a synced copy of the ones it needs.
>
> **Connectors** — MCP servers that wire Claude to your data — terminals, research platforms, document stores. `plugins/vertical-plugins/financial-analysis/.mcp.json`
>
> — `README.md`

파트너 플러그인은 이 동기화 파이프라인 밖에 있다. `CLAUDE.md`는 스킬 편집을 `vertical-plugins/`에서 하고 `scripts/sync-agent-skills.py`로 에이전트 번들에 전파하라고 한다. partner-built 경로는 언급되지 않는다. partner-built 아래에는 `agents/` 디렉터리와 `managed-agent-cookbooks/` 대응물이 없다.

마켓플레이스에는 버티컬·에이전트·파트너가 함께 등록된다.

> `"name": "lseg", "displayName": "LSEG", "source": "./plugins/partner-built/lseg"`
> `"name": "sp-global", "displayName": "S&P Global", "source": "./plugins/partner-built/spglobal"`
>
> — `.claude-plugin/marketplace.json`

`plugin.json` 저자 필드:

| 플러그인 | author.name | 추가 필드 |
|---|---|---|
| `financial-analysis`, `equity-research`, agent 플러그인 | `"Anthropic FSI"` | name/version/description만 |
| `investment-banking` | `"Anthropic"` | name/version/description만 |
| `lseg` | `"LSEG"` | name/version/description만. license 필드 없음 |
| `sp-global` | `"Kensho Technologies"` | email, homepage, repository, license, keywords |

버전: LSEG `1.0.0`, S&P Global `1.0.1`. 인용한 Anthropic 버티컬/에이전트는 `0.1.x`~`0.2.x`.

구성 차이 (파일 트리 기준):

- Anthropic 버티컬: `.claude-plugin/plugin.json`, `commands/`, `skills/`, 다수는 `hooks/hooks.json`. MCP는 **financial-analysis가 커넥터를 중앙 집중**. investment-banking·private-equity의 `.mcp.json`은 `"mcpServers": {}`.
- LSEG 파트너: `.claude-plugin/plugin.json`, **자체 `.mcp.json`**, `commands/` 8개, `skills/` 8개, `CONNECTORS.md`, `README.md`. `hooks/` 없음. **LICENSE 파일 없음**.
- S&P 파트너: `.claude-plugin/plugin.json`, **자체 `.mcp.json`**, `skills/` 3개, 루트 `LICENSE` + 스킬별 `LICENSE`. **`commands/` 없음**. `CONNECTORS.md` 없음. `hooks/` 없음.

README가 파트너를 버티컬 표에 `*(partner)*`로 넣는다.

> **[lseg](./plugins/partner-built/lseg)** *(partner)* — Bond RV, swap curves, FX carry, options vol, macro-rates monitoring on LSEG data.
> **[sp-global](./plugins/partner-built/spglobal)** *(partner)* — Tear sheets, earnings previews, funding digests on S&P Capital IQ.
>
> — `README.md`

데이터 커넥터 소유권:

> All connectors are centralized in the **financial-analysis** core plugin and shared across the rest.
>
> — `README.md`

파트너 플러그인은 이 중앙화와 별도로 **자기 `.mcp.json`을 가진다**. LSEG는 워크플로가 MCP 툴 체인에 고정되어 있다.

> This plugin packages LSEG's financial analytics MCP tools into 8 high-level workflows that stitch together multiple tool calls for common financial analysis tasks. Instead of calling individual tools one at a time, each command orchestrates 4-5 tools into a cohesive analysis.
>
> — `plugins/partner-built/lseg/README.md`

S&P는 Cowork 표준을 따르되 스킬이 플랫폼 비종속이라고 명시한다. Anthropic 버티컬 README에는 이 문구가 없다.

> The skills are built on open standards (MCP) and are designed to work across AI platforms and agent frameworks. While the plugin follows the Claude Cowork standard, all skills and the underlying data layer are platform-agnostic.
>
> — `plugins/partner-built/spglobal/README.md`

S&P README는 ChatGPT Custom Instructions, Microsoft Copilot, Claude Desktop Skills 업로드, Claude Code 플러그인을 설치 경로로 나열한다. LSEG README 설치는 `claude plugins add LSEG`만.

Anthropic 버티컬 equity-research의 `earnings-preview`는 합의 추정치를 “via web search”로 가져오라고 한다. S&P `earnings-preview-beta`는 웹 검색을 금지하고 Kensho Grounding MCP `search`와 S&P Global MCP `kfinance`만 허용한다 (아래 인용).

S&P README의 스킬 표기는 디렉터리명과 어긋난다. README: Tearsheets / Industry Transaction Summaries / Earnings Previews. 실제 디렉터리: `tear-sheet`, `funding-digest`, `earnings-preview-beta`.

---

## MCP 엔드포인트

### 파트너 `.mcp.json` (있는 그대로)

LSEG (`plugins/partner-built/lseg/.mcp.json`):

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

> This plugin connects to the **LFA MCP Server**, which provides financial analytics tools from LSEG (London Stock Exchange Group). All tools are served by a single MCP server — no additional connectors are needed.
>
> — `plugins/partner-built/lseg/CONNECTORS.md`

S&P (`plugins/partner-built/spglobal/.mcp.json`):

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

> The LLM-ready API is easy to integrate in Claude or other applications via its MCP server. Follow [these steps](docs.kensho.com/llmreadyapi/mcp/third-party/claude) to set it up.
>
> — `plugins/partner-built/spglobal/README.md`

> Use the **S&P Global** MCP tools (also known as the Kensho LLM-ready API).
>
> — `plugins/partner-built/spglobal/skills/tear-sheet/SKILL.md`

### Anthropic `financial-analysis` 중앙 커넥터와 불일치

리포 README MCP 표:

> [S&P Global](https://www.spglobal.com/) | `https://kfinance.kensho.com/integrations/mcp`
> [LSEG](https://www.lseg.com/) | `https://api.analytics.lseg.com/lfa/mcp`
>
> — `README.md`

`plugins/vertical-plugins/financial-analysis/.mcp.json`:

- 키 `"sp-global"` (하이픈), URL `https://kfinance.kensho.com/integrations/mcp` — S&P 파트너와 **URL은 같고 키는 다름** (`spglobal` vs `sp-global`).
- 키 `"lseg"`, URL `https://api.analytics.lseg.com/lfa/mcp` — LSEG 파트너는 **`/lfa/mcp/server-cl`**. 경로가 다르다.

같은 `.mcp.json`에 Daloopa, Morningstar, FactSet, Moody's, MT Newswires, Aiera, PitchBook, Chronograph, Egnyte, Box가 더 있다. 파트너 플러그인 `.mcp.json`에는 없다.

### LSEG 툴 (CONNECTORS.md + 커맨드/스킬)

CONNECTORS.md 카테고리 플레이스홀더와 툴명:

| Category | Placeholder | Tools |
|---|---|---|
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

커맨드 8개와 스킬 매핑 (LSEG README):

| Command | Skill |
|---|---|
| `/analyze-bond-rv` | `bond-relative-value` |
| `/analyze-fx-carry` | `fx-carry-trade` |
| `/research-equity` | `equity-research` |
| `/analyze-swap-curve` | `swap-curve-strategy` |
| `/analyze-option-vol` | `option-vol-analysis` |
| `/review-fi-portfolio` | `fixed-income-portfolio` |
| `/macro-rates` | `macro-rates-monitor` |
| `/analyze-bond-basis` | `bond-futures-basis` |

다수 커브/스왑 툴은 “two-phase: list then calculate/price”다 (`CONNECTORS.md`, 각 SKILL.md).

### S&P 툴 (스킬에 등장하는 이름; `.mcp.json`은 URL만)

`.mcp.json`은 서버 URL만 선언한다. 툴 목록은 스킬 본문에 있다.

`funding-digest/SKILL.md`:

- `get_info_from_identifiers`
- `get_competitors_from_identifiers` (`competitor_source="all"`)
- `get_rounds_of_funding_from_identifiers` (`role="company_raising_funds"` 또는 `company_investing_in_round_of_funding`)
- `get_funding_summary_from_identifiers` (primary가 아님)
- `get_rounds_of_funding_info_from_transaction_ids`
- `get_company_summary_from_identifiers`

Capital IQ 딥링크:

> `https://www.capitaliq.spglobal.com/web/client?#offering/capitalOfferingProfile?id=<transaction_id>`
>
> — `funding-digest/SKILL.md`

`earnings-preview-beta/SKILL.md`가 허용하는 소스:

> The ONLY permitted data sources are **Kensho Grounding MCP** (`search`) and **S&P Global MCP** (`kfinance`).
>
> — `earnings-preview-beta/SKILL.md`

같은 스킬의 `kfinance` 함수명:

- `get_latest()`
- `get_info_from_identifiers`
- `get_company_summary_from_identifiers`
- `get_next_earnings_from_identifiers`
- `get_earnings_from_identifiers`
- `get_latest_earnings_from_identifiers`
- `get_transcript_from_key_dev_id`
- `get_competitors_from_identifiers`
- `get_prices_from_identifiers`
- `get_financial_line_item_from_identifiers`
- `get_capitalization_from_identifiers`
- `get_consensus_estimates_from_identifiers`
- `get_segments_from_identifiers`

Kensho Grounding은 파트너 `.mcp.json`에 별도 서버로 없다. 스킬 본문만 `search`를 요구한다.

`tear-sheet/SKILL.md`는 툴을 함수명으로 고정하지 않고 “structured tools for financial data, company information, market data, consensus estimates, earnings transcripts, M&A transactions, and business relationships”에 레퍼런스 query plan을 매핑하라고 한다. Data Integrity Rule 10:

> **No S&P Global tool returns executive or management data.**
>
> — `tear-sheet/SKILL.md`

---

## 인증·구독

리포 공통:

> MCP access may require a subscription or API key from the provider.
>
> — `README.md`

### LSEG

> ## Requirements
> - Access to the LSEG MCP Server with valid credentials
> - LSEG data entitlements for the relevant product offerings
>
> — `plugins/partner-built/lseg/README.md`

인증 프로토콜(OAuth, API key, 프롬프트 로그인)은 LSEG 파일에 없다. Cowork 인증 단계도 없다.

### S&P Global

각 스킬:

> **Requires**: [S&P Global LLM-ready API](https://www.marketplace.spglobal.com/en/solutions/kensho-llm-ready-api-%28a156fe9f-5564-4f60-a624-95d8645dc98f%29) subscription
>
> — `plugins/partner-built/spglobal/README.md` (Tearsheets, Industry Transaction Summaries, Earnings Previews 각각)

플러그인 전체:

> The plugin and skills require access to S&P Global data to work with, either [Capital IQ Pro](https://www.spglobal.com/market-intelligence/en/solutions/products/sp-capital-iq-pro) or [S&P Global LLM-ready API](...) subscriptions.
>
> — 같은 README

Cowork:

> You'll need a paid Claude plan (Pro, Max, Team, or Enterprise) and the Claude Desktop app for macOS or Windows.
> ...
> Authenticate with your S&P Global credentials when prompted
>
> — 같은 README

homepage (`plugin.json`):

> `https://www.marketplace.spglobal.com/en/solutions/kensho-llm-ready-api-%28a156fe9f-5564-4f60-a624-95d8645dc98f%29`

문의:

> contact [commercial@kensho.com](mailto:commercial@kensho.com)
>
> — `plugins/partner-built/spglobal/README.md`

Anthropic 버티컬 `plugin.json`에는 벤더 구독 필드가 없다. 커넥터 구독은 루트 README 한 줄만.

---

## 시장데이터 재배포 제약

**이 디렉터리와 인용한 리포 파일에는 “시장데이터를 재배포하지 말 것”이라는 명시 조항이 없다.** 있는 것은 엔타이틀먼트, 구독, 허용 소스, 출처 표기, 투자자문 부인, AI 생성 고지다.

### LSEG — 엔타이틀먼트만

> Access to the LSEG MCP Server with valid credentials
> LSEG data entitlements for the relevant product offerings
>
> — `lseg/README.md`

스킬/커맨드는 툴 출력을 리포트·테이블로 합성하라고 한다. 재배포·저장·제3자 공유 금지는 없다.

### S&P — 소스 폐쇄, 출처, 고지. 재배포 금지는 없음

데이터 소스 전용 (earnings preview):

> Absolutely NO other tools, data sources, or web access of any kind. Specifically:
> - Do NOT use `WebSearch`, `WebFetch`, `web_search`, `brave_search`, `google_search`, or ANY generic web/internet search tool — even if Kensho is slow, returns no results, or is temporarily unavailable.
> - Do NOT use any browser, URL fetch, or web scraping tool.
> - If Kensho Grounding returns no results for a query, try rephrasing the query or note "data not available" in the report. **NEVER fall back to web search as an alternative.**
> - Every piece of information in the report must be traceable to either a `kfinance` MCP function call or a Kensho `search` call.
>
> — `earnings-preview-beta/SKILL.md`

Tear sheet:

> **S&P Global tools are the only source for financial data.** Do not fill gaps with training knowledge — it may be stale or wrong.
> Never fabricate data. If the tools don't return a number, do not estimate from training knowledge.
>
> — `tear-sheet/SKILL.md`

필수 푸터 (tear sheet, 모든 페이지):

> Line 1: "Data: S&P Capital IQ via Kensho | Analysis: AI-generated | [Month Day, Year]"
> Line 2: "For informational purposes only. Not investment advice."
>
> — `tear-sheet/SKILL.md`

Earnings preview 필수 문구 (헤더·푸터·부록 3곳):

> **"Analysis is AI-generated — please confirm all outputs"**
>
> — `earnings-preview-beta/SKILL.md`

Funding digest:

> You MUST include the following disclaimer text in the powerpoint footer.
> **"Analysis is AI-generated — please confirm all outputs"**
> Footer: "Deal Flow Digest · [Period] · Sources: S&P Global Capital IQ · Generated [Date]"
>
> — `funding-digest/SKILL.md`

플러그인 README:

> The skills in this plugin are provided as-is. Generated outputs and data are not guaranteed to be correct. **Always verify outputs generated by an LLM for correctness.**
>
> — `spglobal/README.md`

리포 공통 고지:

> Nothing in this repository constitutes investment, legal, tax, or accounting advice. ... You are responsible for verifying outputs and for compliance with the laws and regulations that apply to your firm.
>
> — 루트 `README.md`

Funding digest는 Capital IQ 프로필로 링크한다. 데이터를 외부 CDN/웹에서 채우지 말라는 지시도 있다 (로고: Clearbit 사용 금지, `simple-icons`/`sharp` 로컬 파이프라인). 이는 로고 파이프라인이지 시세 재배포 조항이 아니다.

Apache 2.0 섹션 4 “Redistribution”은 **이 Work(스킬 마크다운/소프트웨어)** 의 복제·배포 조건이다. 벤더 시세 피드의 재배포 허가가 아니다. 라이선스 본문은 시장데이터를 정의하지 않는다.

---

## 라이선스

### 리포

루트 `LICENSE`: Apache License 2.0. Appendix 저작권은 플레이스홀더 `Copyright [yyyy] [name of copyright owner]`.

루트 README: `[Apache License 2.0](./LICENSE)`.

### LSEG 파트너 디렉터리

- `LICENSE` 파일 없음.
- `plugin.json`에 `"license"` 키 없음.
- 저작권 고지 없음.
- 적용 여부는 리포 루트 LICENSE에만 의존. LSEG 플러그인 자체는 별도 라이선스 파일을 두지 않았다.

### S&P / Kensho

`plugin.json`: `"license": "Apache-2.0"`.

루트 및 세 스킬 디렉터리 `LICENSE` 동일: Apache 2.0, appendix:

> Copyright 2026-present Kensho Technologies, LLC.

README:

> Licensed under the Apache 2.0 License. Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
> Copyright 2026-present Kensho Technologies, LLC. The present date is determined by the timestamp of the most recent commit in the repository.
>
> — `spglobal/README.md`

Apache 2.0이 명시하는 것 (LICENSE 원문 요약이 아니라 조항 제목): Grant of Copyright License, Grant of Patent License, Redistribution (NOTICE 유지 등), Trademarks (상호·상표 사용 허가 없음, NOTICE 재현 및 출처 설명에 필요한 경우 제외), Disclaimer of Warranty (AS IS), Limitation of Liability.

> 6. Trademarks. This License does not grant permission to use the trade names, trademarks, service marks, or product names of the Licensor, except as required for reasonable and customary use in describing the origin of the Work and reproducing the content of the NOTICE file.
>
> — `spglobal/LICENSE`

데이터 구독(Capital IQ Pro / LLM-ready API)은 이 Apache 라이선스와 별개다. README는 스킬 사용에 그 구독을 요구한다.

---

## 파일 인벤토리

### LSEG (`plugins/partner-built/lseg/`) — LICENSE 없음

- `.claude-plugin/plugin.json` — name `lseg`, version `1.0.0`, author LSEG
- `.mcp.json` — `https://api.analytics.lseg.com/lfa/mcp/server-cl`
- `README.md`, `CONNECTORS.md`
- `commands/`: `analyze-bond-basis.md`, `analyze-bond-rv.md`, `analyze-fx-carry.md`, `analyze-option-vol.md`, `analyze-swap-curve.md`, `macro-rates.md`, `research-equity.md`, `review-fi-portfolio.md`
- `skills/*/SKILL.md`: `bond-futures-basis`, `bond-relative-value`, `equity-research`, `fixed-income-portfolio`, `fx-carry-trade`, `macro-rates-monitor`, `option-vol-analysis`, `swap-curve-strategy`

### S&P (`plugins/partner-built/spglobal/`)

- `.claude-plugin/plugin.json` — name `sp-global`, version `1.0.1`, author Kensho Technologies, license Apache-2.0, repository `https://github.com/kensho-technologies/spglobal-agent-skills`
- `.mcp.json` — `https://kfinance.kensho.com/integrations/mcp` (키 `spglobal`)
- `LICENSE`, `README.md`
- `skills/earnings-preview-beta/`: `SKILL.md` (frontmatter name `earnings-preview-single`), `report-template.md`, `LICENSE`
- `skills/funding-digest/`: `SKILL.md`, `references/sector-seeds.md`, `LICENSE`
- `skills/tear-sheet/`: `SKILL.md`, `references/{equity-research,ib-ma,corp-dev,sales-bd}.md`, `LICENSE`

### 비교에 쓴 Anthropic 파일

- `README.md`, `CLAUDE.md`, `LICENSE`, `.claude-plugin/marketplace.json`
- `plugins/vertical-plugins/financial-analysis/.mcp.json`, `.claude-plugin/plugin.json`
- `plugins/vertical-plugins/{equity-research,investment-banking}/.claude-plugin/plugin.json`
- `plugins/vertical-plugins/{investment-banking,private-equity}/.mcp.json` (`mcpServers` 빈 객체)
- `plugins/vertical-plugins/equity-research/skills/earnings-preview/SKILL.md` (web search 합의치)
- `plugins/vertical-plugins/investment-banking/README.md`

---

## 인용 원문 (핵심)

LSEG 설치·요구사항:

```
claude plugins add LSEG
```

> - Access to the LSEG MCP Server with valid credentials
> - LSEG data entitlements for the relevant product offerings

S&P MCP:

> type: http, url: https://kfinance.kensho.com/integrations/mcp

LSEG MCP (파트너):

> type: http, url: https://api.analytics.lseg.com/lfa/mcp/server-cl

LSEG MCP (financial-analysis 버티컬):

> type: http, url: https://api.analytics.lseg.com/lfa/mcp
