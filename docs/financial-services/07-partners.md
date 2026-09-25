# Partner-built 플러그인 분석: `lseg` / `sp-global`

- **범위:** `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/{lseg,spglobal}` 전체 파일, 그리고 Anthropic-authored `vertical-plugins/` / `agent-plugins/` / `.claude-plugin/marketplace.json` / repo `README.md` / `LICENSE` / `CLAUDE.md` 와의 대조.
- **원칙:** 저장소에 적힌 내용만 기록. 도구 동작, 구독 가격, 엔타이틀먼트 범위는 파일이 명시하지 않으면 “파일에 없음”으로 표기.
- **작성일 기준 트리:** partner-built 아래는 `lseg/` 와 `spglobal/` 두 개뿐.

---

## 1. 위치와 마켓플레이스 등록

Repo root `README.md` 와 `CLAUDE.md` 는 세 갈래를 구분한다.

| 디렉터리 | 역할 (repo 문구) |
|---|---|
| `plugins/agent-plugins/` | Named agents — 자기완결 플러그인. `agents/<slug>.md` + 번들 skills. Cowork 와 Managed Agents 가 같은 소스를 참조. |
| `plugins/vertical-plugins/` | FSI verticals — skill 소스, commands, MCP. `sync-agent-skills.py` 가 agent 번들로 복사. |
| `plugins/partner-built/` | Partner-authored plugins (LSEG, S&P Global). |

`.claude-plugin/marketplace.json` (`name`: `claude-for-financial-services`) 에 두 partner 플러그인이 등록되어 있다.

| marketplace `name` | `displayName` | `source` | `description` |
|---|---|---|---|
| `lseg` | LSEG | `./plugins/partner-built/lseg` | Price bonds, analyze yield curves, evaluate FX carry trades, value options, and build macro dashboards using LSEG financial data and analytics. |
| `sp-global` | S&P Global | `./plugins/partner-built/spglobal` | S&P Global - Financial data and analytics skills including company tearsheets, earnings previews, and transaction summaries |

Root `README.md` Vertical Plugins 표:

- **`lseg`** *(partner)* — Bond RV, swap curves, FX carry, options vol, macro-rates monitoring on LSEG data.
- **`sp-global`** *(partner)* — Tear sheets, earnings previews, funding digests on S&P Capital IQ.

Partner 플러그인에는 `agents/` 디렉터리, `hooks/`, `managed-agent-cookbooks/` 대응물, `scripts/sync-agent-skills.py` 대상 스킬이 **없다**. `CLAUDE.md` 의 “Edit skills in `vertical-plugins/`, then sync into agent bundles” 규칙은 partner-built 에 적용되지 않는다.

---

## 2. Anthropic-authored verticals 와의 차이

### 2.1 저자·버전·매니페스트

Anthropic vertical `plugin.json` 패턴 (전부 `.claude-plugin/plugin.json`):

| Plugin | `name` | `version` | `author.name` | 추가 필드 |
|---|---|---|---|---|
| `financial-analysis` | `financial-analysis` | `0.1.1` | `Anthropic FSI` | 없음 |
| `investment-banking` | `investment-banking` | `0.2.1` | `Anthropic` | 없음 |
| `equity-research` | `equity-research` | `0.1.2` | `Anthropic FSI` | 없음 |
| `private-equity` | `private-equity` | `0.1.2` | `Anthropic FSI` | 없음 |
| `fund-admin` | `fund-admin` | `0.1.0` | `Anthropic FSI` | 없음 |
| `operations` | `operations` | `0.1.0` | `Anthropic FSI` | 없음 |

Partner:

| Plugin | `name` | `version` | `author` | 추가 필드 |
|---|---|---|---|---|
| LSEG | `lseg` | `1.0.0` | `{ "name": "LSEG" }` | 없음 |
| S&P | `sp-global` | `1.0.1` | `{ "name": "Kensho Technologies", "email": "spglobal-agent-skills-maintainers@kensho.com" }` | `homepage`, `repository`, `license: "Apache-2.0"`, `keywords` |

S&P `plugin.json` 고유 필드:

- `homepage`: `https://www.marketplace.spglobal.com/en/solutions/kensho-llm-ready-api-%28a156fe9f-5564-4f60-a624-95d8645dc98f%29`
- `repository`: `https://github.com/kensho-technologies/spglobal-agent-skills`
- `keywords`: `sp-global`, `finance`, `capital-iq`, `tearsheets`, `earnings`, `transactions`, `excel`

Anthropic verticals 는 `0.x` 버전, partner 는 `1.0.x`. Anthropic 매니페스트에는 `license` / `homepage` / `repository` / `email` / `keywords` 가 없다.

### 2.2 구성 요소

| 요소 | Anthropic verticals | `lseg` | `spglobal` |
|---|---|---|---|
| `commands/*.md` | 대부분 있음 (`fund-admin`, `operations` 는 없음) | 8개 | **없음** |
| `skills/*/SKILL.md` | 있음 (vertical 이 소스, agent 가 복사본) | 8개 | 3개 |
| `.mcp.json` | `financial-analysis` 에 커넥터 일괄 집중. IB/PE 는 `"mcpServers": {}`. equity-research / fund-admin / operations 는 `.mcp.json` 없음 | 전용 LFA 서버 1개 | 전용 Kensho MCP 1개 |
| `CONNECTORS.md` | 없음 | 있음 (도구 카탈로그) | 없음 |
| `hooks/hooks.json` | equity-research, financial-analysis, IB, PE 에 존재 (`{ "hooks": {} }`) | 없음 | 없음 |
| `agents/` | `agent-plugins/` 에만 존재 | 없음 | 없음 |
| `LICENSE` | repo root Apache 2.0. 플러그인 단위 LICENSE 없음. 예외: `financial-analysis/skills/skill-creator/LICENSE.txt` | **없음** | 플러그인 루트 + 스킬 3개, 총 4개 |
| 산출물 | 메모, Excel, PPT, CIM 등. 벤더 락인 약함 | 인라인 리서치 노트/대시보드 (파일 산출 지시 없음) | HTML / PPTX / DOCX 산출 + `/tmp` 중간 파일 |
| 데이터 소스 | 공유 MCP 11개 + web search 허용 스킬 다수 (예: `equity-research/skills/earnings-preview` 는 “Pull consensus estimates via web search”) | LFA MCP 도구만 명시 | S&P Capital IQ / Kensho 만 허용 (earnings-preview 는 web search 금지) |
| 설치 문서 | `claude plugin marketplace add anthropics/financial-services` 후 `claude plugin install <name>@claude-for-financial-services` | `claude plugins add LSEG` | Cowork Personal 플러그인 + S&P 인증. Desktop skill 업로드. Claude Code GitHub 문서. ChatGPT/Copilot 붙여넣기까지 설명 |
| Managed Agents | `managed-agent-cookbooks/<slug>/` | 없음 | 없음 |
| 플랫폼 서술 | Cowork + Claude Code + Managed Agents | Claude plugin | “platform-agnostic”, ChatGPT Custom Instructions, Microsoft Copilot, 기타 system prompt 업로드 |

### 2.3 MCP 배치 철학

Root `README.md`:

> All connectors are centralized in the **financial-analysis** core plugin and shared across the rest.

`plugins/vertical-plugins/financial-analysis/.mcp.json` 키:

`daloopa`, `morningstar`, `sp-global`, `factset`, `moodys`, `mtnewswire`, `aiera`, `lseg`, `pitchbook`, `chronograph`, `egnyte`, `box`.

Partner 플러그인은 **자기 `.mcp.json` 에 자기 벤더만** 넣는다. 즉 같은 LSEG / S&P 엔드포인트가 (1) 코어 `financial-analysis` 와 (2) partner 플러그인에 이중으로 선언된다.

URL 불일치 (파일에 적힌 그대로):

| 선언 위치 | 키 | URL |
|---|---|---|
| `financial-analysis/.mcp.json` | `lseg` | `https://api.analytics.lseg.com/lfa/mcp` |
| repo `README.md` MCP Integrations 표 | LSEG | `https://api.analytics.lseg.com/lfa/mcp` |
| `partner-built/lseg/.mcp.json` | `lseg` | `https://api.analytics.lseg.com/lfa/mcp/server-cl` |
| `financial-analysis/.mcp.json` | `sp-global` | `https://kfinance.kensho.com/integrations/mcp` |
| repo `README.md` | S&P Global | `https://kfinance.kensho.com/integrations/mcp` |
| `partner-built/spglobal/.mcp.json` | `spglobal` | `https://kfinance.kensho.com/integrations/mcp` |

S&P URL 은 일치. 키 이름만 `sp-global` vs `spglobal`. LSEG URL 은 partner 쪽이 `/server-cl` suffix 를 갖는다. 차이 이유는 파일에 설명되어 있지 않다.

참고: `financial-analysis/.mcp.json` 은 `egnyte` 객체 다음 `box` 앞에 쉼표가 없어 JSON 이 깨져 있다. partner `.mcp.json` 두 파일은 유효한 JSON 이다.

### 2.4 스킬 작성 스타일

- **LSEG:** 짧은 SKILL.md (~50–66줄). “You are an expert …”. MCP 도구 체인 + 출력 테이블. 명령이 워크플로를 오케스트레이션하고 스킬은 도메인 지식.
- **S&P:** 긴 SKILL.md (513–524줄) + references + HTML/DOCX 템플릿 + 중간파일 규칙 + 산술 검증 + AI disclaimer. 명령 없이 스킬이 전체 워크플로.
- **Anthropic equity-research `earnings-preview`:** 80줄, web search 허용, bull/base/bear 시나리오, 벤더 고정 없음. S&P `earnings-preview-beta` 와 기능이 겹치지만 데이터 구속과 산출물 형식이 다르다.

### 2.5 설치 문구 차이

- Anthropic: marketplace 경유, `@claude-for-financial-services`.
- LSEG README: `` claude plugins add LSEG `` (marketplace 슬러그 `lseg` 와 대소문자/동사 불일치. 파일에 추가 설명 없음).
- S&P README: Cowork “Browse Plugins → Personal → +”, “Authenticate with your S&P Global credentials when prompted”. 유료 Claude plan (Pro, Max, Team, or Enterprise) + Claude Desktop macOS/Windows.

---

## 3. LSEG 플러그인 (`plugins/partner-built/lseg`)

### 3.1 파일 목록 (완전)

```
lseg/
  .claude-plugin/plugin.json
  .mcp.json
  CONNECTORS.md
  README.md
  commands/
    analyze-bond-basis.md
    analyze-bond-rv.md
    analyze-fx-carry.md
    analyze-option-vol.md
    analyze-swap-curve.md
    macro-rates.md
    research-equity.md
    review-fi-portfolio.md
  skills/
    bond-futures-basis/SKILL.md
    bond-relative-value/SKILL.md
    equity-research/SKILL.md
    fixed-income-portfolio/SKILL.md
    fx-carry-trade/SKILL.md
    macro-rates-monitor/SKILL.md
    option-vol-analysis/SKILL.md
    swap-curve-strategy/SKILL.md
```

LICENSE, hooks, agents, references, scripts: **없음**.

### 3.2 README 요약

제목: **LSEG Financial Analytics Plugin**.

역할: LSEG financial analytics MCP tools 를 8개 high-level workflow 로 패키징. “Instead of calling individual tools one at a time, each command orchestrates 4-5 tools into a cohesive analysis.”

Requirements (그대로):

- Access to the LSEG MCP Server with valid credentials
- LSEG data entitlements for the relevant product offerings

자격 증명 형식, OAuth, API 키 이름, 엔타이틀먼트 상품 목록은 **파일에 없음**.

### 3.3 MCP 엔드포인트와 도구

`.mcp.json`:

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

README: 단일 **LFA MCP Server**. “All tools are served by a single MCP server — no additional connectors are needed.” (`CONNECTORS.md`)

`CONNECTORS.md` 카테고리 (placeholder 토큰은 문서용):

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

도구 설명 (`CONNECTORS.md`):

- **`bond_price`** — ISIN, RIC, CUSIP, or AssetId. yield, duration, convexity, DV01, accrued interest. price/yield override what-if.
- **`bond_future_price`** — fair value, CTD, delivery basket, conversion factors, contract DV01.
- **`fx_spot_price`** — ISO pairs, mid/bid/ask.
- **`fx_forward_price`** — tenor/date, forward points, outright, carry.
- **`interest_rate_curve`** — two-phase list then calculate. par/zero, discount factors, forward rates.
- **`credit_curve`** — country + issuer type (Corporate, Sovereign, Agency, etc.).
- **`inflation_curve`** — breakevens and real yields. search then calculate.
- **`fx_forward_curve`** — list then calculate, standard tenors.
- **`ir_swap`** — list templates by currency/index, then price. par rates, DV01, NPV.
- **`option_value`** — vanilla, barrier, binary, Asian. premium + Greeks (delta, gamma, vega, theta, rho).
- **`option_template_list`** — available option templates.
- **`fx_vol_surface`** — SABR, tenors and delta strikes.
- **`equity_vol_surface`** — equities/indices via RIC, futures via RICROOT.
- **`qa_ibes_consensus`** — IBES EPS, revenue, EBITDA, DPS. analyst count, dispersion, high/low.
- **`qa_company_fundamentals`** — income statement, balance sheet. historical fiscal years.
- **`qa_historical_equity_price`** — OHLCV, total returns, beta.
- **`qa_macroeconomic`** — mnemonic or description search. latest or time series.
- **`tscc_historical_pricing_summaries`** — any RIC. interday (daily/weekly/monthly) and intraday (1min–1hr).
- **`yieldbook_bond_reference`** — security type, sector, ratings, coupon, maturity, issuer.
- **`yieldbook_cashflow`** — coupon and principal schedules.
- **`yieldbook_scenario`** — parallel rate shifts.
- **`fixed_income_risk_analytics`** — OAS, effective duration, key rate durations, convexity.

### 3.4 명령 (`commands/`) ↔ 스킬 매핑

모든 명령 파일은 YAML frontmatter (`description`, `argument-hint`) + CONNECTORS.md 링크 + 대응 스킬 참조 + numbered workflow + output format.

| Command 파일 | Slash (README) | `argument-hint` | 대응 skill |
|---|---|---|---|
| `analyze-bond-rv.md` | `/analyze-bond-rv` | `"<ISIN, RIC, or CUSIP> [vs benchmark]"` | `bond-relative-value` |
| `analyze-fx-carry.md` | `/analyze-fx-carry` | `"<currency pair e.g. USDJPY> [tenor e.g. 3M]"` | `fx-carry-trade` |
| `research-equity.md` | `/research-equity` | `"<ticker e.g. AAPL> [period e.g. FY2024-FY2026]"` | `equity-research` |
| `analyze-swap-curve.md` | `/analyze-swap-curve` | `"<currency e.g. EUR> [index e.g. ESTR]"` | `swap-curve-strategy` |
| `analyze-option-vol.md` | `/analyze-option-vol` | `"<underlying e.g. .SPX or EURUSD> [strike] [expiry]"` | `option-vol-analysis` |
| `review-fi-portfolio.md` | `/review-fi-portfolio` | `"<ISIN1,ISIN2,...> [scenario e.g. +100bp]"` | `fixed-income-portfolio` |
| `macro-rates.md` | `/macro-rates` | `"<country e.g. US> [timeframe e.g. 5Y]"` | `macro-rates-monitor` |
| `analyze-bond-basis.md` | `/analyze-bond-basis` | `"<bond future RIC e.g. FGBLc1>"` | `bond-futures-basis` |

명령은 사용자에게 식별자를 묻고, 명시된 MCP 도구를 순서대로 호출한 뒤 테이블 리포트를 합성한다. 파일 경로 산출, HTML/DOCX, disclaimer 문구는 **명령에 없다**.

### 3.5 스킬별 워크플로와 데이터 의존성

공통 패턴: 도구가 가격/커브를 계산하고, 모델은 spread/rich-cheap/trade idea 를 합성.

#### `bond-relative-value`

- **트리거 (frontmatter):** bond richness/cheapness, spread decomposition, comparing bonds, rate shock scenarios.
- **도구:** `bond_price`, `interest_rate_curve`, `credit_curve`, `yieldbook_scenario`, (optional) `tscc_historical_pricing_summaries`, `fixed_income_risk_analytics` (callable bonds).
- **체인:** price → G-spread vs govt curve → credit curve residual (G-spread − credit curve; positive = cheap, negative = rich) → parallel shocks −100/−50/0/+50/+100bp → optional historical Z-score.
- **출력:** Spread Decomposition, Scenario P&L, Rich/Cheap Summary (rich/avoid, cheap/buy, fair/neutral).
- **명령 추가 입력:** optional benchmark bond, valuation date default today.

#### `bond-futures-basis`

- **트리거:** bond futures, CTD, implied repo, basis trades.
- **도구:** `bond_future_price`, `bond_price`, `interest_rate_curve`, `tscc_historical_pricing_summaries`, (optional) `credit_curve`.
- **체인:** price future (CTD, CF, basket, DV01, delivery dates) → price CTD cash bond → gross/net basis, implied repo vs short-end as repo proxy → 3M daily history of future and CTD → optional sovereign credit (예: DE for Bund, US for Treasury).
- **명령 예시 RIC:** `FGBLc1` (Euro Bund), `TYc1` (US 10Y Note), `FFIc1` (UK Gilt).
- **출력:** Future Summary, CTD analytics, basis table (gross/net, implied vs market repo), historical context, long/short/neutral.

#### `fx-carry-trade`

- **트리거:** carry trades, FX forward curves, carry-to-vol.
- **도구:** `fx_spot_price`, `fx_forward_price`, `fx_forward_curve`, `fx_vol_surface`, `tscc_historical_pricing_summaries`, `interest_rate_curve` (스킬; 명령 워크플로 6단계는 커브 호출을 명시하지 않음).
- **체인:** spot → forward at target tenor (default 3M) → full carry curve ON–1Y → ATM vol / 25d RR / 25d BF, carry-to-vol = annualized carry / ATM IV → 1Y daily historical range.
- **출력:** Carry Profile (1M/3M/6M/1Y), Vol Surface, recommendation (attractive / moderate / unattractive — 명령 문구).

#### `equity-research` (LSEG; Anthropic `equity-research` vertical 과 이름만 공유)

- **트리거:** researching stocks, estimates vs actuals, valuations.
- **도구:** `qa_ibes_consensus`, `qa_company_fundamentals`, `qa_historical_equity_price`, `tscc_historical_pricing_summaries`, `qa_macroeconomic`.
- **체인:** FY1/FY2 IBES (EPS, Revenue, EBITDA, DPS, period type `"A"`) → 3–5 FY fundamentals → 1Y prices (YTD, 1Y, 52w, beta) → 3M daily OHLCV → GDP/CPI/policy rate.
- **티커 형식:** “IBES ticker format (e.g., AAPL, MSFT, VOD)”.
- **출력:** consensus table, financials, forward P/E = price / consensus EPS, thesis. 스킬은 buy/hold/sell + fair value range 를 요구. 명령은 “investment thesis summary (1-2 sentences)”.

#### `swap-curve-strategy`

- **트리거:** swap curves, swap spreads, steepener/flattener/butterfly.
- **도구:** `ir_swap`, `interest_rate_curve`, `inflation_curve`, `tscc_historical_pricing_summaries`, `qa_macroeconomic`.
- **체인:** list swap templates → price 2Y/5Y/7Y/10Y/20Y/30Y → govt overlay (swap spread = swap − govt) → inflation BE, real swap = nominal − BE → 2s10s, 5s30s, 2s5s10s butterfly.
- **명령 입력:** currency (EUR, USD, GBP, CHF, JPY), optional index (ESTR, SOFR, SONIA, TONA).
- **출력:** curve table, metrics, real-rate decomposition, DV01-neutral trade (legs, 3M carry, roll-down, breakeven, target, stop).

#### `option-vol-analysis`

- **트리거:** pricing options, vol surfaces, Greeks, vol premium.
- **도구:** `equity_vol_surface` or `fx_vol_surface`, `option_template_list`, `option_value`, `tscc_historical_pricing_summaries`, (스킬) `qa_historical_equity_price` alternative.
- **식별자:** equities `VOD.L@RIC`, `.SPX@RIC`; futures `ES@RICROOT`, `CL@RICROOT`; FX `EURUSD`, `USDJPY`.
- **체인:** surface (ATM, 25d RR, 25d BF) → templates → price option (default ATM, 3M, both call/put) → close-to-close RV 20d/60d/90d vs matching IV.
- **출력:** surface, Greeks, IV vs RV, regime, strategies.

#### `fixed-income-portfolio`

- **트리거:** portfolio duration/DV01, cashflow waterfall, rate scenarios, composition.
- **도구:** `bond_price` (comma-separated batch), `yieldbook_bond_reference`, `yieldbook_cashflow`, `yieldbook_scenario`, `interest_rate_curve`, `fixed_income_risk_analytics` (embedded options).
- **체인:** price all → MV-weighted yield/duration/DV01/convexity → reference (sector/rating/maturity/currency) → quarterly cashflow waterfall → shocks −200/−100/−50/0/+50/+100/+200bp → spread-to-curve.
- **명령:** optional position sizes (default equal weight), optional scenario string.
- **출력:** vs-benchmark summary (benchmark 은 “when available”), composition, waterfall, scenario P&L with top/bottom contributors.

#### `macro-rates-monitor`

- **트리거:** macro conditions, curve shape, real vs nominal, policy expectations, financial conditions.
- **도구:** `qa_macroeconomic`, `interest_rate_curve`, `inflation_curve`, `ir_swap`, `tscc_historical_pricing_summaries`.
- **명령 국가→통화 맵:** US→USD, DE→EUR, GB→GBP, JP→JPY. 기본 timeframe 3Y (명령) / 스킬은 명시적 default 없음.
- **매크로 검색 패턴 (스킬):** `US*GDP*`, `US*CPI*`, `US*PCE*`, `US*UNEMP*`; `EZ*GDP*`, `EZ*HICP*`; `UK*GDP*`, `UK*CPI*`. seasonally adjusted 선호. GDP quarterly, 나머지 monthly.
- **체인:** GDP/CPI/unemployment/policy (+ PMI in skill) → govt curve 2s10s, 3M-10Y, 5s30s → real = nominal − BE → swap spreads 2Y/5Y/10Y → historical benchmark yield.
- **출력:** dashboard. cycle, curve, real-rate regime, financial conditions, 2–3 sentence assessment.

### 3.6 LSEG 라이선스·안전

- 플러그인 트리에 LICENSE 파일 **없음**.
- `plugin.json` 에 `license` 필드 **없음**.
- Repo root `LICENSE` 는 Apache 2.0, appendix copyright `[yyyy] [name of copyright owner]` (placeholder). LSEG 콘텐츠가 그 라이선스에 포함되는지는 partner 디렉터리에 별도 고지가 없다.
- 데이터 제약으로 명시된 것은 README 의 **valid credentials** 와 **LSEG data entitlements for the relevant product offerings** 뿐.
- 재배포(redistribution) 금지, delayed vs real-time, 인용 고지 문구는 **LSEG 파일에 없음**.
- 스킬/명령에 “not investment advice”, AI disclaimer, 거래 집행 금지는 **없음**. (Repo root README 의 일반 고지 — “Nothing in this repository constitutes investment, legal, tax, or accounting advice” — 는 레포 전체에 적용된다고 적혀 있다.)
- LSEG `equity-research` 스킬은 buy/hold/sell 추천을 출력 포맷에 포함한다.

---

## 4. S&P Global 플러그인 (`plugins/partner-built/spglobal`)

### 4.1 파일 목록 (완전)

```
spglobal/
  .claude-plugin/plugin.json
  .mcp.json
  LICENSE
  README.md
  skills/
    earnings-preview-beta/
      LICENSE
      report-template.md
      SKILL.md
    funding-digest/
      LICENSE
      references/sector-seeds.md
      SKILL.md
    tear-sheet/
      LICENSE
      references/corp-dev.md
      references/equity-research.md
      references/ib-ma.md
      references/sales-bd.md
      SKILL.md
```

`commands/` **없음**. 스킬이 자연어 트리거 + (README) “typing / in the chat to see available commands” 라고만 언급. 이 플러그인 트리에는 command markdown 이 없다.

### 4.2 README 요약과 이름 불일치

제목: **S&P Global Plugin**. Kensho/S&P 가 작성. “built on open standards (MCP)”, “Claude Cowork standard” 이지만 “platform-agnostic”.

Skills Contained (README 표제 vs 실제 디렉터리):

| README 표제 | 실제 skill 디렉터리 | SKILL.md `name` |
|---|---|---|
| Tearsheets | `tear-sheet` | `tear-sheet` |
| Industry Transaction Summaries | `funding-digest` | `funding-digest` |
| Earnings Previews | `earnings-preview-beta` | `earnings-preview-single` |

README “Industry Transaction Summaries” 설명: “Summarizes recent M&A and deal activity within a sector or for a specific company, drawing on S&P Capital IQ transaction data.” 실제 `funding-digest` 스킬은 **weekly funding rounds / venture deal-flow one-slide PPTX** 이다. M&A 거래 요약 전용 스킬 디렉터리는 없다. Tear-sheet 의 IB/M&A 템플릿이 회사 M&A activity 를 다루고, earnings-preview 가 news 검색에서 M&A 를 언급한다.

제공 조건 (README 반복):

> The skills are provided as-is. Generated outputs and data are not guaranteed to be correct. **Always verify outputs generated by an LLM for correctness.**

연락: `commercial@kensho.com`. “We are actively building additional skills”.

### 4.3 MCP 엔드포인트와 구독/인증

`.mcp.json`:

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

README 가 요구하는 구독 (세 스킬 모두 동일 링크):

- [S&P Global LLM-ready API](https://www.marketplace.spglobal.com/en/solutions/kensho-llm-ready-api-%28a156fe9f-5564-4f60-a624-95d8645dc98f%29)
- 또는 [Capital IQ Pro](https://www.spglobal.com/market-intelligence/en/solutions/products/sp-capital-iq-pro)

MCP 설정 문서 (README): `docs.kensho.com/llmreadyapi/mcp/third-party/claude` (스킴 없는 상대 호스트 문자열로 적혀 있음).

Cowork: “Authenticate with your S&P Global credentials when prompted.”

자격 증명 환경변수 이름, 토큰 형식은 **파일에 없음**.

**Kensho Grounding MCP 갭:** `earnings-preview-beta/SKILL.md` 는 허용 소스를 **Kensho Grounding MCP (`search`) + S&P Global MCP (`kfinance`)** 두 개로 고정한다. 플러그인 `.mcp.json` 에는 `kfinance` URL 하나만 있다. Grounding `search` 서버 URL 은 partner 트리에 **선언되어 있지 않다**.

### 4.4 스킬: `tear-sheet`

**Frontmatter `name`:** `tear-sheet`  
**트리거:** tear sheet, company one-pager, profile, fact sheet, snapshot, overview; equity research summaries, M&A company profiles, corp-dev target profiles, sales/BD meeting prep. 사용자 미지정 시 audience 를 물어본다. public and private.

**산출:** Word `.docx` via `docx-js` (Node). Nested skill: `/mnt/skills/public/docx/SKILL.md`.  
**파일명:** `[CompanyName]_TearSheet_[Audience]_[YYYYMMDD].docx`  
**저장:** `/mnt/user-data/outputs/`

**Audience → reference:**

| Audience | Reference | Default pages |
|---|---|---|
| Equity Research | `references/equity-research.md` | 1 |
| IB / M&A | `references/ib-ma.md` | 1–2 |
| Corp Dev | `references/corp-dev.md` | 1–2 |
| Sales / BD | `references/sales-bd.md` | 1–2 |

**데이터 의존 (SKILL.md):** “S&P Global MCP tools (also known as the Kensho LLM-ready API)”. 쿼리 플랜은 자연어 질의로 적혀 있고, “map these to the appropriate S&P Global tools available in the conversation.” 도구 함수명을 tear-sheet SKILL 본문이 고정 나열하지는 않음 (earnings-preview / funding-digest 와 대조).

**중간 파일 (`/tmp/tear-sheet/`):**

| File | 용도 |
|---|---|
| `company-profile.txt` | All |
| `financials.csv` | All (`period,line_item,value,source`) |
| `segments.csv` | ER, IB, CD |
| `valuation.csv` | ER, IB, CD |
| `consensus.csv` | ER |
| `earnings.txt` | ER, IB, Sales |
| `relationships.txt` | IB, CD, Sales |
| `peer-comps.csv` | ER, IB, CD |
| `ma-activity.csv` | IB, CD |
| `calculations.csv` | All, Step 3b |

**워크플로:** Identify inputs (company, audience, optional comps, optional page length) → read reference → `mkdir -p /tmp/tear-sheet/` → MCP queries with write-after-query → Step 3b derived metrics (margins, YoY, FCF conversion, net debt, segment %) + arithmetic validation → verify files (soft gate) → generate DOCX with copy-pasted helper functions (`createHeaderBanner`, `createSectionHeader`, `createTable`, `createBulletList`, `createFooter`).

**필수 footer (every page, all audiences):**

1. `Data: S&P Capital IQ via Kensho | Analysis: AI-generated | [Month Day, Year]`
2. `For informational purposes only. Not investment advice.`

**Data Integrity Rules (1–10) 요지:**

1. S&P Global tools only for financial data. No training-knowledge gap fill.
2. Label missing as `N/A` / `Not disclosed`.
3. Dates / fiscal vs calendar / market data “as of”.
4. Don’t mix reporting periods unlabeled.
5. Prefer MCP pre-computed fields over manual recompute.
6. Same company, multiple tear sheets → identical underlying numbers.
7. Never downgrade known deal values to “Undisclosed”.
8. Segment % uses consolidated revenue denominator (intersegment eliminations).
9. Always include NTM multiples when tools return them.
10. **No S&P Global tool returns executive/management data.** Omit management tables. Do not invent names from training data.

**Private companies:** skip stock price, 52w, beta, stock performance, consensus, trading comps. Note “Private Company”.

**스타일:** Arial, navy `#1F3864`, accent `#2E75B6`, US Letter 0.75" margins. IB/M&A M&A 테이블만 `accentHeader`.

Audience 섹션 (references):

- **ER:** Header, 2–3 sentence rewritten description, valuation trailing+NTM, consensus, 3y financials + capital structure subtable, segments, earnings highlights (guidance first, beat/miss if consensus exists), optional KPIs, stock performance cut-first. Densest template (8pt tables).
- **IB/M&A:** Pitchbook prose overview, segments, 3y+LTM financials, capital structure + S&P credit rating if available, trading comps with peers, own M&A (Deal Value column required) + precedent txs, relationships, ownership if returned. Cut order starts at Ownership. Never cut overview/segments/core financials/own M&A.
- **Corp Dev:** Strategic Relevance tagline, product/tech overview, revenue mix + customer concentration, **Strategic Fit** (customer overlap / tech complement / competitive displacement — signature, 2–3 sentences/bucket), financials with R&D and FCF conversion, valuation with peers, ownership, **Integration Considerations** (required). Never cut overview, core financials, integration.
- **Sales/BD:** No EV/beta. Plain-language overview, strategic themes (not earnings recap), 3-row financial snapshot (Revenue, Gross Margin %, Employees), relationships, news + “Coming Up” catalysts, Conversation Starters tagged by persona and must cite a specific number/date/product. Warmest template, 9pt.

### 4.5 스킬: `funding-digest`

**Frontmatter `name`:** `funding-digest`  
**트리거:** deal flow digest, weekly recap, funding digest, transaction roundup, capital markets briefing, “what happened in [sector] this week”.

**산출:** 단일 슬라이드 PPTX (`pptxgenjs`, `LAYOUT_16x9`). Nested: `/mnt/skills/public/pptx/SKILL.md` + `pptxgenjs.md`.  
**경로:** write `/home/claude/deal-flow-digest.pptx` → copy `/mnt/user-data/outputs/` → `present_files`.  
**로고:** `/home/claude/logos/[company-name].png`. **금지:** Clearbit (`logo.clearbit.com`) “deprecated and consistently fails”. External logo CDNs (Brandfetch, logo.dev, Google Favicons) “require API keys or are blocked”. Tier 1 `simple-icons` + `sharp`; Tier 2 initial SVG via `sharp`; else pptxgenjs shapes.

**AI disclaimer (footer, mandatory):** `"Analysis is AI-generated — please confirm all outputs"` yellow banner.

**데이터 도구:**

| Tool | 역할 |
|---|---|
| `get_info_from_identifiers` | Pre-validate. Check resolve + `status` (`Operating` vs `Operating Subsidiary` vs other). |
| `get_competitors_from_identifiers` (`competitor_source="all"`) | Expand universe from seeds. |
| `get_rounds_of_funding_from_identifiers` (`role="company_raising_funds"`) | Primary funding source. Investor role only when analyzing an investor. |
| `get_rounds_of_funding_info_from_transaction_ids` | Enrich all `transaction_id`s in batch. |
| `get_company_summary_from_identifiers` | Notable-deal context. |
| `get_funding_summary_from_identifiers` | “faster but less reliable”; not primary. |

**Entity rules:** empty results → alias / legal name / `company_id` from `references/sector-seeds.md`. Subsidiaries return zero rounds. Batch 15–20. Case-insensitive, spelling-sensitive.

**워크플로:** coverage (watchlist or ask sectors/companies/period, default last 7 days) → seed + validate + competitor expand (15–40 operating companies/sector, 50–100+ multi-sector) → funding rounds in date window → enrich → notable flags (≥$100M, down rounds, new unicorns, ≥2x valuation jump, repeat raisers, large syndicates) → 3–5 takeaways → logos → one-slide PPTX → QA (`markitdown`, soffice PDF, pdftoppm) → present.

**슬라이드:** stat cards (Total Raised, # Rounds, Avg Pre-Money, Largest Round), key takeaways with logos, top 4–6 deals table (Company, Type, Announced, Closed, Amount, Pre-$, Post-$, Lead, Deal Link). Capital IQ URL:

`https://www.capitaliq.spglobal.com/web/client?#offering/capitalOfferingProfile?id=<transaction_id>`

Footer: `Deal Flow Digest · [Period] · Sources: S&P Global Capital IQ · Generated [Date]` + AI disclaimer.

**`references/sector-seeds.md`:** 검증된 시드 (AI/ML, Cybersecurity, Cloud/DevTools, Fintech, Vertical SaaS, Biotech, Digital Health, Med Devices, Climate, Clean Energy, E-commerce, Consumer Social, Logistics, Robotics, Space). 제외 목록: Inflection AI, Adept AI, DeepMind, Cerebral (only if user asks), Shockwave Medical, Temu/PDD, BeReal, Lemon8 (wrong entity), Convoy. Alias table: Together AI → Together Computer, Inc. (`C_1860042219`); Character.ai → Character Technologies, Inc. (`C_1829047235`); Runway ML → Runway AI, Inc. (`C_633706980`); Adept AI → Adept AI Labs Inc. (`C_1780739313`); xAI → X.AI LLC (`C_1863863313`). “Refresh cadence: quarterly.” US-skew. Competitor expansion for geo.

### 4.6 스킬: `earnings-preview-beta`

**디렉터리:** `earnings-preview-beta`  
**Frontmatter `name`:** `earnings-preview-single` (디렉터리명과 불일치)  
**설명:** 4–5 page single-company equity research earnings preview as self-contained HTML.

**허용 데이터 소스 (ZERO EXCEPTIONS):**

- Kensho Grounding MCP: `search`
- S&P Global MCP: `kfinance`

금지: `WebSearch`, `WebFetch`, `web_search`, `brave_search`, `google_search`, browser, URL fetch, scraping. Kensho 가 비어도 web search 로 폴백하지 말고 “data not available”. 출처 없는 정보는 보고서에 넣지 말 것.

**중간 파일:** `/tmp/earnings-preview/` (`mkdir -p` at start). write-after-each-call. Phase 7 전에 **각 파일을 별도 `cat` 으로** 다시 읽고 verification 블록을 사용자에게 출력. 파일이 진실의 원천.

파일: `company-info.txt`, `transcript-extracts.txt`, `financials.csv`, `segments.csv`, `prices.csv`, `peer-eps.csv`, `peer-market-caps.csv`, `consensus-eps.csv`, `kensho-findings.txt`, `earnings-dates.csv`, `calculations.csv`.

**kfinance 도구 (SKILL 이 이름으로 고정):**

| Tool | 용도 |
|---|---|
| `get_latest()` | current reporting period |
| `get_info_from_identifiers` | market cap, industry |
| `get_company_summary_from_identifiers` | business description |
| `get_next_earnings_from_identifiers` | upcoming date + fiscal quarter name (verbatim) |
| `get_latest_earnings_from_identifiers` | last completed call `key_dev_id` |
| `get_transcript_from_key_dev_id` | transcript |
| `get_competitors_from_identifiers` (`competitor_source="all"`) | top 5–7 public competitors |
| `get_prices_from_identifiers` (`periodicity="day"`, 12M) | prices |
| `get_financial_line_item_from_identifiers` | `diluted_eps`, `revenue`, `gross_profit`, `operating_income`, `ebitda`, `net_income`; quarterly, 8 periods |
| `get_capitalization_from_identifiers` (`capitalization="market_cap"`) | market cap |
| `get_consensus_estimates_from_identifiers` (`period_type="quarterly"`, `num_periods_forward=4`) | NTM EPS = sum of next 4 quarterly means |
| `get_segments_from_identifiers` (`segment_type="business"`, quarterly, 8) | segments; missing YoY → “y/y not available”, 추정 금지 |
| `get_earnings_from_identifiers` | historical earnings dates for chart annotations |

**Kensho `search` 카테고리 (필수, 건너뛰지 말 것):** estimates, analyst ratings, risks, recent news (60d), sector outlook. 각 결과에 source URL 기록.

**규칙:** Fiscal quarter는 API 콜 이름 그대로 (Walmart 예시). Quotes는 verbatim. Ratios는 LTM/NTM만 (trailing/forward 금지). 모든 숫자/주장은 `<a href="#ref-N" class="data-ref">`. 계산은 Phase 6 에서 파일 기반. 공통 주가 수익률 기준일. LTM P/E 는 회사별 최근 4 reported quarters.

**Phase 7 산출:** `earnings-preview-[TICKER]-YYYY-MM-DD.html` in CWD, then `open` that file.

**HTML:** `report-template.md` — embedded CSS, Chart.js 4.4.7 + annotation plugin 3.1.0 from jsDelivr with SRI hashes. Helpers only: `createRevEpsChart`, `createMarginChart`, `createRevGrowthChart`, `createAnnotatedPriceChart`, `createCompPerfChart`, `createPEChart`. Each chart in its own try/catch script.

**AI disclaimer 3곳 필수:** header banner, footer, appendix first line: `"Analysis is AI-generated — please confirm all outputs"`.

**리포트 구조:** Page 1 cover & thesis; Page 2 estimates/themes/news; Pages 3–5 Figures 1–8; Appendix sources. No emojis. Opinionated sell-side tone. “Our Estimate” vs consensus 컬럼이 템플릿에 있다.

**Appendix:** Ref #, Fact, Value, Source & Derivation. Raw CIQ → function+params. Calculated → formula with hyperlinked components. Transcript → verbatim + `key_dev_id`. Kensho → excerpt + clickable URL + query.

### 4.7 S&P 라이선스

네 파일 모두 Apache License 2.0 전문. Appendix copyright 동일:

```
Copyright 2026-present Kensho Technologies, LLC.
```

README License 절:

> Licensed under the Apache 2.0 License. … AS IS …  
> Copyright 2026-present Kensho Technologies, LLC. The present date is determined by the timestamp of the most recent commit in the repository.

`plugin.json` `"license": "Apache-2.0"`.

Repo root `LICENSE` 는 같은 Apache 2.0 이지만 copyright 필드가 placeholder. S&P 는 **Kensho 저작권 고지를 플러그인 및 각 스킬에 중복 삽입**.

Anthropic verticals: 플러그인 LICENSE 없음. 유일한 스킬 LICENSE 는 `financial-analysis/skills/skill-creator/LICENSE.txt` (Apache 2.0 텍스트, partner 와 별개).

Apache 2.0 이 커버하는 것은 **스킬/플러그인 저작물**이다. Capital IQ 데이터 자체에 대한 재배포 라이선스는 LICENSE 파일에 **없다**.

---

## 5. 안전 / 시장데이터 재배포 / 컴플라이언스 제약

저장소와 플러그인 파일에 **실제로 적힌** 제약만 정리. 일반 시장데이터 계약 조항을 추정하지 않음.

### 5.1 레포 공통 (root `README.md`)

> Nothing in this repository constitutes investment, legal, tax, or accounting advice. These agents draft analyst work product — models, memos, research notes, reconciliations — for review by a qualified professional. They do not make investment recommendations, execute transactions, bind risk, post to a ledger, or approve onboarding; every output is staged for human sign-off.

> MCP access may require a subscription or API key from the provider.

### 5.2 LSEG

명시:

- Valid credentials for LSEG MCP Server.
- LSEG data entitlements for relevant product offerings.

비명시 (파일에 없음):

- Redistribution / display / delayed-data 조항.
- 인용 고지 문장.
- AI/투자 권유 disclaimer (플러그인 내부).
- 엔타이틀먼트 상품 코드.

관찰: LSEG `equity-research` 스킬 출력 포맷은 `buy/hold/sell` 을 포함한다. 레포 공통 고지(“do not make investment recommendations”) 와 긴장 관계가 있으나, LSEG 스킬이 그 고지를 재인용하지는 않는다.

### 5.3 S&P / Kensho

명시:

- LLM-ready API 또는 Capital IQ Pro 구독.
- Cowork 에서 S&P credentials 인증.
- Outputs as-is, always verify.
- Tear-sheet footer: not investment advice; AI-generated; source “S&P Capital IQ via Kensho”.
- Funding-digest / earnings-preview: mandatory AI disclaimer “Analysis is AI-generated — please confirm all outputs”.
- Financials: S&P tools only; no training-data fill; no web search (earnings-preview).
- Do not fabricate consensus, deal values, YoY, management names.
- Capital IQ deal links point at `capitaliq.spglobal.com` (제품 UI). 링크가 깨지면 셀 생략.
- Clearbit/외부 로고 CDN 사용 금지 (funding-digest).
- Earnings-preview: 모든 숫자 하이퍼링크 + appendix 에 MCP function 또는 Kensho URL.

비명시 (파일에 없음):

- “Do not redistribute S&P data outside the licensed user” 같은 전용 재배포 조항.
- 데이터 보관 기간, 지연 시세, 외부 고객 전달 제한.
- Kensho Grounding `search` 결과 URL 을 보고서에 넣는 것은 스킬이 **요구**. 그 URL 의 재게시 가능 여부는 플러그인이 논하지 않음.

### 5.4 소프트웨어 vs 데이터

| 레이어 | 라이선스/제약 (파일 근거) |
|---|---|
| Repo 코드 (Anthropic) | Apache 2.0 (`/LICENSE`) |
| S&P 스킬 마크다운/템플릿 | Apache 2.0, Copyright 2026-present Kensho Technologies, LLC |
| LSEG 스킬/명령 마크다운 | 플러그인 내 LICENSE 없음 |
| LSEG / S&P **시장 데이터** | 구독·엔타이틀먼트·credentials. Apache 텍스트가 데이터를 공개 재배포 허가한다고 적혀 있지 않음 |

### 5.5 실행 환경 가정 (S&P 스킬이 하드코딩)

S&P 스킬은 Claude 호스팅 경로를 전제한다: `/mnt/skills/public/docx/`, `/mnt/skills/public/pptx/`, `/mnt/user-data/outputs/`, `/home/claude/`, `/tmp/tear-sheet/`, `/tmp/earnings-preview/`. LSEG 스킬은 이런 경로를 쓰지 않는다.

외부 네트워크: earnings-preview HTML 은 Chart.js CDN (`cdn.jsdelivr.net`) 을 로드. funding-digest 는 npm `simple-icons` / `sharp` / `pptxgenjs`. tear-sheet 는 `docx` npm. 이들은 데이터 벤더 재배포가 아니라 문서 생성 의존성이다.

---

## 6. 명령 종합 (partner)

### 6.1 LSEG — 8 slash commands

Anthropic 관례 (`CLAUDE.md`): `commands/*.md` → `/plugin:command-name`. README 는 `/analyze-bond-rv` 형식으로 적는다.

각 명령 한 줄:

1. `/analyze-bond-rv` — bond RV, spread decomposition, scenario stress. Tools: `bond_price`, `interest_rate_curve`, `credit_curve`, `yieldbook_scenario`.
2. `/analyze-fx-carry` — FX carry with spot, forwards, vol, history. Tools: `fx_spot_price`, `fx_forward_price`, `fx_forward_curve`, `fx_vol_surface`, `tscc_historical_pricing_summaries`.
3. `/research-equity` — IBES + fundamentals + prices + macro. Tools: `qa_ibes_consensus`, `qa_company_fundamentals`, `qa_historical_equity_price`, `tscc_historical_pricing_summaries`, `qa_macroeconomic`.
4. `/analyze-swap-curve` — swap vs govt vs inflation, curve trades. Tools: `ir_swap`, `interest_rate_curve`, `inflation_curve`.
5. `/analyze-option-vol` — surface, Greeks, IV vs RV. Tools: `equity_vol_surface`/`fx_vol_surface`, `option_template_list`, `option_value`, `tscc_historical_pricing_summaries`.
6. `/review-fi-portfolio` — multi-bond pricing, cashflows, scenarios. Tools: `bond_price`, `yieldbook_bond_reference`, `yieldbook_cashflow`, `yieldbook_scenario`, `interest_rate_curve`.
7. `/macro-rates` — macro + curve + real rates + swap spreads. Tools: `qa_macroeconomic`, `interest_rate_curve`, `inflation_curve`, `ir_swap`, `tscc_historical_pricing_summaries`.
8. `/analyze-bond-basis` — futures basis, CTD, implied repo. Tools: `bond_future_price`, `bond_price`, `interest_rate_curve`, `tscc_historical_pricing_summaries`, `credit_curve`.

### 6.2 S&P — command markdown 없음

README: “You can also invoke specific skills explicitly by typing / in the chat to see available commands.” 트리에는 `commands/` 가 없으므로 slash 이름은 이 플러그인이 정의하지 않는다. 스킬은 description 트리거로 자동 활성화된다고 README 가 말한다.

---

## 7. 관찰된 불일치·공백 (발명 없이)

1. LSEG MCP URL: partner `.mcp.json` 은 `.../lfa/mcp/server-cl`, 코어 `financial-analysis` 와 root README 는 `.../lfa/mcp`.
2. MCP 키: S&P 가 `spglobal` (partner) vs `sp-global` (financial-analysis / marketplace plugin name).
3. LSEG 설치 문구 `claude plugins add LSEG` vs marketplace `name` `lseg`.
4. S&P README “Industry Transaction Summaries” vs skill `funding-digest` (venture funding slide, not a general M&A summary skill).
5. Skill folder `earnings-preview-beta` vs frontmatter `name: earnings-preview-single`.
6. `earnings-preview-beta` 가 Kensho Grounding `search` 를 필수 소스로 두지만 `.mcp.json` 에 Grounding 서버가 없다.
7. `plugin.json` keywords 에 `excel` 이 있으나 트리에 Excel 생성 스킬/명령이 없다.
8. LSEG LICENSE 파일 없음.
9. Partner 플러그인에 hooks/agents/managed-agent cookbooks 없음.
10. `financial-analysis/.mcp.json` 의 `box` 항목 앞 쉼표 누락 (코어 파일; partner 파일은 해당 없음).
11. Anthropic `equity-research` vertical 의 `earnings-preview` 스킬과 S&P `earnings-preview-beta` 가 같은 업무를 다른 데이터 구속으로 수행. 설치 시 둘 다 켜면 트리거 충돌 가능성은 파일이 다루지 않음.
12. LSEG `skills/equity-research` 와 Anthropic vertical `equity-research` 동명.

---

## 8. 소스 경로 인덱스

### LSEG

- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/lseg/.claude-plugin/plugin.json`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/lseg/.mcp.json`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/lseg/README.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/lseg/CONNECTORS.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/lseg/commands/*.md` (8)
- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/lseg/skills/*/SKILL.md` (8)

### S&P

- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/spglobal/.claude-plugin/plugin.json`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/spglobal/.mcp.json`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/spglobal/README.md`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/spglobal/LICENSE`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/spglobal/skills/tear-sheet/{SKILL.md,LICENSE,references/*.md}`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/spglobal/skills/funding-digest/{SKILL.md,LICENSE,references/sector-seeds.md}`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/partner-built/spglobal/skills/earnings-preview-beta/{SKILL.md,LICENSE,report-template.md}`

### 대조

- `/Users/yeonwoosung/Desktop/financial-services/README.md`
- `/Users/yeonwoosung/Desktop/financial-services/CLAUDE.md`
- `/Users/yeonwoosung/Desktop/financial-services/LICENSE`
- `/Users/yeonwoosung/Desktop/financial-services/.claude-plugin/marketplace.json`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/financial-analysis/.mcp.json`
- `/Users/yeonwoosung/Desktop/financial-services/plugins/vertical-plugins/*/ .claude-plugin/plugin.json`
