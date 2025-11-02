# API Integrations Guide

ApiCallAgent now supports integration with multiple external APIs for weather, currency exchange, and stock market data.

## Supported APIs

### 1. Weather API (OpenWeatherMap)

Get real-time weather information for any city worldwide.

**Configuration:**
```bash
OPENWEATHER_API_KEY=your_api_key_here
```

**Get API Key:** https://openweathermap.org/api

**Features:**
- Current temperature, humidity, pressure
- Weather conditions and descriptions
- Wind speed and visibility
- Feels-like temperature

**Example Queries:**
- "서울 날씨 알려줘"
- "What's the weather in Tokyo?"
- "뉴욕의 기온은?"

---

### 2. Currency Exchange API

Get real-time currency exchange rates between different currencies.

**Configuration:**
```bash
# Optional - uses free fallback API if not set
EXCHANGERATE_API_KEY=your_api_key_here
```

**Get API Key:** https://www.exchangerate-api.com/

**Features:**
- Real-time exchange rates
- Support for 160+ currencies
- Automatic fallback to free API (exchangerate.host)
- Last update timestamp

**Example Queries:**
- "USD to KRW 환율"
- "What's the exchange rate from EUR to JPY?"
- "달러 원화 환율 알려줘"

**Supported Currencies:**
- USD (US Dollar)
- KRW (Korean Won)
- EUR (Euro)
- JPY (Japanese Yen)
- GBP (British Pound)
- And 150+ more...

---

### 3. Stock Market API

Get real-time stock prices, market data, and financial statements.

**Configuration:**
```bash
# Choose your provider: "yahoo" (free) or "financialdatasets"
STOCK_API_PROVIDER=yahoo

# Optional: FinancialDatasets.ai API Key
FINANCIALDATASETS_API_KEY=your_api_key_here

# Optional: Alpha Vantage API Key (backup for financial statements)
ALPHA_VANTAGE_API_KEY=your_api_key_here
```

**Providers:**

#### Yahoo Finance (Default, Free)
- **No API key required**
- Real-time stock prices
- Historical data
- Financial statements (income statement, balance sheet, cash flow)
- Company information
- Market cap, P/E ratio, dividend yield
- 52-week high/low

**Get FinancialDatasets.ai API Key:** https://financialdatasets.ai/

#### FinancialDatasets.ai (Premium)
- More comprehensive data
- Better rate limits
- Advanced financial metrics
- Professional-grade data quality

**Features:**
- Current stock price and changes
- Trading volume and market cap
- P/E ratio, dividend yield
- 52-week high/low
- **Financial Statements:**
  - Income Statement (revenue, profits, EBITDA)
  - Balance Sheet (assets, liabilities, equity)
  - Cash Flow Statement (operating, investing, financing cash flows)

**Example Queries:**
- "AAPL 주식 가격"
- "Tell me about Tesla stock"
- "애플 재무제표 보여줘"
- "엔비디아 주가는?"
- "삼성전자 주식 정보"

**Supported Stock Symbols:**
- US Stocks: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, etc.
- Korean Stocks: 005930.KS (삼성전자), 035420.KS (네이버), 035720.KS (카카오)
- International stocks on major exchanges

---

## Setup Instructions

### 1. Copy the template file
```bash
cp .env.template .env
```

### 2. Add your API keys to `.env`

```bash
# Weather API
OPENWEATHER_API_KEY=your_openweather_key

# Currency API (optional)
EXCHANGERATE_API_KEY=your_exchangerate_key

# Stock API (choose provider)
STOCK_API_PROVIDER=yahoo  # or "financialdatasets"
FINANCIALDATASETS_API_KEY=your_financialdatasets_key  # only if using financialdatasets
```

### 3. Install dependencies
```bash
uv sync
```

---

## Usage Examples

### Weather Queries
```python
from neos.agents.generation_agents import ApiCallAgent

agent = ApiCallAgent()

# Query weather
result = await agent.execute("서울 날씨 알려줘")
# Returns: temperature, humidity, conditions, wind speed, etc.

result = await agent.execute("What's the weather in London?")
```

### Currency Exchange Queries
```python
# Query exchange rates
result = await agent.execute("USD to KRW 환율")
# Returns: exchange rate, last update time

result = await agent.execute("달러 원화 환율은?")
```

### Stock Market Queries
```python
# Query stock prices
result = await agent.execute("AAPL 주식 가격")
# Returns: current price, change, volume, market cap, etc.

result = await agent.execute("애플 재무제표 보여줘")
# Returns: income statement, balance sheet, cash flow

result = await agent.execute("엔비디아 주가는?")
# Automatically recognizes "엔비디아" = NVDA
```

---

## Smart Parameter Extraction

The ApiCallAgent automatically extracts parameters from natural language queries:

### City Names
- "서울 날씨" → city: Seoul
- "weather in Tokyo" → city: Tokyo
- "뉴욕의 기온" → city: New York

### Stock Tickers
- "AAPL 주식" → ticker: AAPL
- "$TSLA" → ticker: TSLA
- "애플" → ticker: AAPL (auto-mapped)
- "엔비디아" → ticker: NVDA (auto-mapped)

### Currency Pairs
- "USD to KRW" → from: USD, to: KRW
- "달러 원화" → from: USD, to: KRW
- "EUR/JPY" → from: EUR, to: JPY

### Company Name Mapping
The agent automatically maps common company names to tickers:
- 애플, Apple → AAPL
- 마이크로소프트, Microsoft → MSFT
- 구글, Google, 알파벳 → GOOGL
- 아마존, Amazon → AMZN
- 테슬라, Tesla → TSLA
- 엔비디아, NVIDIA → NVDA
- 삼성 → 005930.KS
- 네이버 → 035420.KS
- 카카오 → 035720.KS

---

## API Response Format

### Weather API Response
```json
{
  "api_type": "weather",
  "result": {
    "location": "Seoul",
    "country": "KR",
    "temperature": "15.3°C",
    "feels_like": "14.1°C",
    "humidity": "65%",
    "pressure": "1013 hPa",
    "condition": "partly cloudy",
    "wind_speed": "3.5 m/s",
    "visibility": "10.0 km"
  }
}
```

### Currency API Response
```json
{
  "api_type": "currency",
  "result": {
    "from": "USD",
    "to": "KRW",
    "rate": 1320.50,
    "last_update": "2025-01-20 00:00:01 UTC"
  }
}
```

### Stock API Response
```json
{
  "api_type": "stock",
  "result": {
    "ticker": "AAPL",
    "name": "Apple Inc.",
    "current_price": 185.50,
    "change": "+2.15",
    "change_percent": "+1.17%",
    "volume": 58234567,
    "market_cap": 2876543210000,
    "pe_ratio": 28.5,
    "dividend_yield": 0.0053,
    "52week_high": 199.62,
    "52week_low": 164.08,
    "financial_statements": {
      "income_statement": {
        "total_revenue": 383285000000,
        "gross_profit": 170782000000,
        "operating_income": 114301000000,
        "net_income": 96995000000,
        "ebitda": 129956000000
      },
      "balance_sheet": {
        "total_assets": 352755000000,
        "total_liabilities": 290437000000,
        "stockholders_equity": 62318000000,
        "cash": 29965000000,
        "total_debt": 108047000000
      },
      "cash_flow": {
        "operating_cash_flow": 110543000000,
        "investing_cash_flow": -10959000000,
        "financing_cash_flow": -108488000000,
        "free_cash_flow": 99584000000
      }
    }
  }
}
```

---

## Error Handling

The agent provides informative error messages:

### Missing API Key
```json
{
  "error": "OpenWeatherMap API key not configured",
  "note": "Please set OPENWEATHER_API_KEY in .env file"
}
```

### Invalid Ticker
```json
{
  "error": "Failed to fetch stock data for INVALID: No data found"
}
```

### API Rate Limit
```json
{
  "error": "API returned status 429",
  "message": "Rate limit exceeded"
}
```

---

## Rate Limits

### OpenWeatherMap (Free Tier)
- 60 calls/minute
- 1,000,000 calls/month

### ExchangeRate-API (Free Tier)
- 1,500 requests/month
- Fallback to exchangerate.host (unlimited)

### Yahoo Finance
- No official limit (reasonable use)
- Recommended: < 2000 requests/hour

### FinancialDatasets.ai
- Varies by plan
- Check your account dashboard

---

## Troubleshooting

### Weather API not working
1. Check API key is set in `.env`
2. Verify API key is valid at openweathermap.org
3. Ensure city name is correct

### Currency API returns error
1. Check currency codes are valid (3-letter ISO codes)
2. If EXCHANGERATE_API_KEY not set, fallback API will be used
3. Verify internet connection

### Stock API returns no data
1. Verify ticker symbol is correct
2. Check if market is open (for real-time data)
3. Try with a well-known ticker (e.g., AAPL) to test
4. For Korean stocks, use format: 005930.KS

### Financial statements are missing
- Not all stocks have complete financial data
- Check if the company files financial reports
- Try using Alpha Vantage as backup (set ALPHA_VANTAGE_API_KEY)

---

## Best Practices

1. **API Key Security**
   - Never commit `.env` file to version control
   - Use `.env.template` for sharing configuration format
   - Rotate API keys periodically

2. **Rate Limiting**
   - Implement caching for frequently requested data
   - Add delays between bulk requests
   - Monitor API usage

3. **Error Handling**
   - Always check for errors in responses
   - Implement retry logic for transient failures
   - Provide fallback data when possible

4. **Performance**
   - Cache weather data (updates every 10 minutes)
   - Cache currency rates (updates every hour)
   - Cache stock data (updates every minute during market hours)

---

## Future Enhancements

Potential additions:
- News API integration
- Cryptocurrency price data
- Economic indicators (GDP, unemployment, etc.)
- More financial data providers
- Historical data queries
- Alert/notification system

---

## Support

For issues or questions:
1. Check this documentation
2. Review `.env.template` for configuration
3. Check API provider documentation
4. Open an issue on the project repository
