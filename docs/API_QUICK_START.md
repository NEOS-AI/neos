# API Integration Quick Start Guide

ApiCallAgent에 날씨, 환율, 주식 API가 통합되었습니다.

## 빠른 시작 (3단계)

### 1단계: API 키 설정

```bash
# .env 파일 생성
cp .env.template .env

# .env 파일 편집하여 API 키 추가
nano .env
```

필수 설정:
```bash
# 날씨 API (OpenWeatherMap)
OPENWEATHER_API_KEY=your_key_here

# 환율 API (선택사항 - 없으면 무료 API 사용)
EXCHANGERATE_API_KEY=your_key_here

# 주식 API (Yahoo Finance는 키 불필요)
STOCK_API_PROVIDER=yahoo
```

### 2단계: 의존성 설치

```bash
uv sync
```

## API 키 발급 방법

### OpenWeatherMap (날씨)
1. https://openweathermap.org/api 방문
2. "Sign Up" 클릭
3. 무료 플랜 선택
4. API 키 복사

### ExchangeRate-API (환율)
1. https://www.exchangerate-api.com/ 방문
2. "Get Free Key" 클릭
3. 이메일로 API 키 수신
4. (선택사항: 키 없이도 무료 API 자동 사용)

### 주식 API
**Yahoo Finance (추천, 무료)**
- API 키 불필요
- 설정: `STOCK_API_PROVIDER=yahoo`

**FinancialDatasets.ai (유료, 고급)**
- https://financialdatasets.ai/ 방문
- 가입 후 API 키 발급
- 설정: `STOCK_API_PROVIDER=financialdatasets`

## 사용 예제

### Python 코드에서 사용

```python
from neos.agents.generation_agents import ApiCallAgent

agent = ApiCallAgent()

# 날씨 조회
result = await agent.execute("서울 날씨 알려줘")

# 환율 조회
result = await agent.execute("USD to KRW 환율")

# 주식 조회
result = await agent.execute("AAPL 주식 가격")

# 재무제표 조회
result = await agent.execute("애플 재무제표 보여줘")
```

### 지원되는 쿼리 예시

**날씨:**
- "서울 날씨"
- "What's the weather in Tokyo?"
- "뉴욕의 기온은?"

**환율:**
- "USD to KRW 환율"
- "달러 원화 환율"
- "EUR/JPY exchange rate"

**주식:**
- "AAPL 주식 가격"
- "테슬라 주가"
- "엔비디아 재무제표"
- "삼성전자 주식 정보"

## 자동 파라미터 추출

에이전트가 자연어에서 자동으로 파라미터를 추출합니다:

- **회사명 → 티커**: "애플" → AAPL, "엔비디아" → NVDA
- **도시명**: "서울 날씨" → city: Seoul
- **통화**: "달러 원화" → USD to KRW

## 주요 기능

### 날씨 API
- 현재 기온, 체감온도
- 습도, 기압
- 풍속, 가시거리
- 날씨 상태

### 환율 API
- 실시간 환율
- 160+ 통화 지원
- 마지막 업데이트 시간
- 무료 API 자동 폴백

### 주식 API
- 실시간 주가
- 거래량, 시가총액
- PER, 배당수익률
- 52주 최고/최저가
- **재무제표:**
  - 손익계산서
  - 대차대조표
  - 현금흐름표

## 트러블슈팅

### API 키 오류
```
"error": "OpenWeatherMap API key not configured"
```
→ `.env` 파일에 API 키를 추가하세요

### 주식 티커 오류
```
"error": "No stock ticker provided"
```
→ 정확한 티커 심볼을 사용하세요 (예: AAPL, NVDA)

### 한국 주식
한국 주식은 `.KS` 접미사 필요:
- 삼성전자: `005930.KS`
- 네이버: `035420.KS`
- 카카오: `035720.KS`

## 더 알아보기

전체 문서: [docs/API_INTEGRATIONS.md](./API_INTEGRATIONS.md)
- 상세 API 설명
- 응답 포맷
- Rate Limits
- Best Practices
