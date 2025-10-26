from typing import Dict, Any, List, Optional
import httpx
import yfinance as yf
import re

from neos.workflow.state import GenerationResult
from neos.config.settings import settings

from .base import GenerationAgent


class ImageGenerationAgent(GenerationAgent):
    """이미지 생성 에이전트"""

    def __init__(self):
        super().__init__(
            name="image_generation",
            generation_type="image",
            role="Image Generator",
            goal="Generate images based on text descriptions and requirements",
            backstory="You are skilled at creating detailed prompts for image generation and understanding visual requirements."
        )


    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}

        try:
            # 이미지 생성 요청인지 확인
            if not self._is_image_request(query):
                return {
                    "success": False, 
                    "error": "Query does not appear to be an image generation request"
                }

            # 이미지 생성 실행
            image_result = await self._generate_image(query, context)

            return self.format_output(image_result, {"generation_type": "image"})

        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}

    def _is_image_request(self, query: str) -> bool:
        """이미지 생성 요청 확인"""
        image_keywords = [
            "이미지", "그림", "사진", "그려", "만들어", "생성", "이미지 생성",
            "image", "picture", "draw", "create", "generate", "visualization"
        ]
        return any(keyword in query.lower() for keyword in image_keywords)

    async def _generate_image(self, query: str, context: Dict[str, Any]) -> GenerationResult:
        """이미지 생성"""
        try:
            # OpenAI DALL-E 3 사용
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "dall-e-3",
                        "prompt": self._enhance_prompt(query),
                        "size": "1024x1024",
                        "quality": "standard",
                        "n": 1
                    },
                    timeout=60.0
                )

            if response.status_code == 200:
                result = response.json()
                image_url = result["data"][0]["url"]

                return GenerationResult(
                    content_type="image",
                    content={
                        "image_url": image_url,
                        "prompt_used": self._enhance_prompt(query),
                        "model": "dall-e-3"
                    },
                    metadata={
                        "size": "1024x1024",
                        "quality": "standard"
                    }
                )
            else:
                raise Exception(f"Image generation failed: {response.text}")

        except Exception as e:
            # 실패 시 플레이스홀더 반환
            return GenerationResult(
                content_type="image",
                content={
                    "error": str(e),
                    "placeholder": "이미지 생성에 실패했습니다."
                }
            )

    def _enhance_prompt(self, query: str) -> str:
        """프롬프트 개선"""
        base_prompt = query
        
        # 스타일 및 품질 향상 키워드 추가
        enhancements = [
            "high quality", "detailed", "professional",
            "clear", "well-composed", "aesthetic"
        ]
        
        enhanced = f"{base_prompt}, {', '.join(enhancements)}"
        return enhanced[:1000]  # 프롬프트 길이 제한


class ApiCallAgent(GenerationAgent):
    """API 호출 에이전트"""

    def __init__(self):
        super().__init__(
            name="api_call",
            generation_type="api",
            role="API Integration Specialist",
            goal="Make API calls to external services and integrate third-party data",
            backstory="You specialize in integrating with various APIs and handling external service communications."
        )
    
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}
        
        try:
            # API 호출이 필요한지 판단
            api_requirements = self._analyze_api_requirements(query)

            if not api_requirements["needs_api"]:
                return {
                    "success": False,
                    "error": "Query does not require API integration"
                }
            
            # API 호출 실행
            api_result = await self._make_api_calls(api_requirements, context)
            
            return self.format_output(api_result, {"generation_type": "api"})
            
        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    def _analyze_api_requirements(self, query: str) -> Dict[str, Any]:
        """API 요구사항 분석"""
        api_indicators = {
            "weather": ["날씨", "기온", "weather", "temperature", "일기예보"],
            "currency": ["환율", "currency", "exchange rate", "달러", "원화"],
            "stock": ["주식", "stock", "주가", "market", "시세", "재무제표", "financial statement"],
            "news": ["뉴스", "news", "최신"],
            "translation": ["번역", "translate", "translation"]
        }

        detected_apis = []
        for api_type, keywords in api_indicators.items():
            if any(keyword in query.lower() for keyword in keywords):
                detected_apis.append(api_type)

        # 쿼리에서 파라미터 추출
        params = self._extract_parameters(query)

        return {
            "needs_api": len(detected_apis) > 0,
            "api_types": detected_apis,
            "priority": detected_apis[0] if detected_apis else None,
            "params": params
        }

    def _extract_parameters(self, query: str) -> Dict[str, Any]:
        """쿼리에서 파라미터 추출"""
        params = {}

        # 도시명 추출 (날씨용)
        city_patterns = [
            r'(?:in|의|에서)\s+([A-Za-z가-힣]+)',
            r'([A-Za-z가-힣]+)(?:\s+날씨|\s+weather)',
        ]
        for pattern in city_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                params['city'] = match.group(1).strip()
                break

        # 주식 티커 추출
        ticker_patterns = [
            r'\b([A-Z]{1,5})\b(?:\s+주식|\s+stock)',  # AAPL 주식
            r'(?:ticker|티커)[\s:]+([A-Z]{1,5})',
            r'\$([A-Z]{1,5})\b',  # $AAPL
        ]
        for pattern in ticker_patterns:
            match = re.search(pattern, query)
            if match:
                params['ticker'] = match.group(1).upper()
                break

        # 회사명에서 티커 추출 시도
        if 'ticker' not in params:
            company_ticker_map = {
                '애플': 'AAPL', 'apple': 'AAPL',
                '마이크로소프트': 'MSFT', 'microsoft': 'MSFT',
                '구글': 'GOOGL', 'google': 'GOOGL', '알파벳': 'GOOGL',
                '아마존': 'AMZN', 'amazon': 'AMZN',
                '테슬라': 'TSLA', 'tesla': 'TSLA',
                '엔비디아': 'NVDA', 'nvidia': 'NVDA',
                '삼성': '005930.KS', 'samsung': '005930.KS',
                '네이버': '035420.KS', 'naver': '035420.KS',
                '카카오': '035720.KS', 'kakao': '035720.KS',
            }
            query_lower = query.lower()
            for company, ticker in company_ticker_map.items():
                if company in query_lower:
                    params['ticker'] = ticker
                    break

        # 통화 쌍 추출
        currency_patterns = [
            r'([A-Z]{3})\s*(?:to|→|에서)\s*([A-Z]{3})',
            r'([A-Z]{3})/([A-Z]{3})',
        ]
        for pattern in currency_patterns:
            match = re.search(pattern, query)
            if match:
                params['from_currency'] = match.group(1).upper()
                params['to_currency'] = match.group(2).upper()
                break

        # 한국어 통화 매핑
        if 'from_currency' not in params:
            if any(word in query for word in ['달러', 'dollar', 'usd']):
                params['from_currency'] = 'USD'
            if any(word in query for word in ['원', 'won', 'krw']):
                if 'from_currency' not in params:
                    params['from_currency'] = 'KRW'
                else:
                    params['to_currency'] = 'KRW'
            if any(word in query for word in ['유로', 'euro', 'eur']):
                if 'from_currency' not in params:
                    params['from_currency'] = 'EUR'
                else:
                    params['to_currency'] = 'EUR'

        # 기본값 설정
        if 'city' not in params:
            params['city'] = 'Seoul'
        if 'from_currency' not in params:
            params['from_currency'] = 'USD'
        if 'to_currency' not in params:
            params['to_currency'] = 'KRW'

        return params

    async def _make_api_calls(self, requirements: Dict[str, Any], context: Dict[str, Any]) -> GenerationResult:
        """API 호출 실행"""
        results = []
        params = requirements.get("params", {})

        for api_type in requirements["api_types"]:
            try:
                if api_type == "weather":
                    result = await self._call_weather_api(params)
                elif api_type == "currency":
                    result = await self._call_currency_api(params)
                elif api_type == "stock":
                    result = await self._call_stock_api(params)
                else:
                    result = {"error": f"Unsupported API type: {api_type}"}

                results.append({
                    "api_type": api_type,
                    "result": result
                })

            except Exception as e:
                results.append({
                    "api_type": api_type,
                    "error": str(e)
                })

        return GenerationResult(
            content_type="api_data",
            content={"api_calls": results},
            metadata={"total_calls": len(results), "params": params}
        )

    async def _call_weather_api(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """OpenWeatherMap API를 사용한 날씨 정보 조회"""
        if not settings.OPENWEATHER_API_KEY:
            return {
                "error": "OpenWeatherMap API key not configured",
                "note": "Please set OPENWEATHER_API_KEY in .env file"
            }

        city = params.get('city', 'Seoul')

        try:
            async with httpx.AsyncClient() as client:
                # Current weather
                response = await client.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={
                        "q": city,
                        "appid": settings.OPENWEATHER_API_KEY,
                        "units": "metric",
                        "lang": "kr"
                    },
                    timeout=10.0
                )

                if response.status_code == 200:
                    data = response.json()
                    return {
                        "location": data.get("name"),
                        "country": data.get("sys", {}).get("country"),
                        "temperature": f"{data['main']['temp']:.1f}°C",
                        "feels_like": f"{data['main']['feels_like']:.1f}°C",
                        "humidity": f"{data['main']['humidity']}%",
                        "pressure": f"{data['main']['pressure']} hPa",
                        "condition": data['weather'][0]['description'],
                        "wind_speed": f"{data['wind']['speed']} m/s",
                        "visibility": f"{data.get('visibility', 0) / 1000:.1f} km",
                        "timestamp": data.get("dt")
                    }
                else:
                    return {
                        "error": f"Weather API returned status {response.status_code}",
                        "message": response.text
                    }

        except Exception as e:
            return {"error": f"Failed to fetch weather data: {str(e)}"}

    async def _call_currency_api(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """환율 API를 사용한 환율 정보 조회"""
        from_currency = params.get('from_currency', 'USD')
        to_currency = params.get('to_currency', 'KRW')

        # ExchangeRate-API 사용 (무료 tier 지원)
        if settings.EXCHANGERATE_API_KEY:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"https://v6.exchangerate-api.com/v6/{settings.EXCHANGERATE_API_KEY}/pair/{from_currency}/{to_currency}",
                        timeout=10.0
                    )

                    if response.status_code == 200:
                        data = response.json()
                        if data.get("result") == "success":
                            return {
                                "from": from_currency,
                                "to": to_currency,
                                "rate": data.get("conversion_rate"),
                                "last_update": data.get("time_last_update_utc"),
                                "next_update": data.get("time_next_update_utc")
                            }
                        else:
                            return {"error": data.get("error-type", "Unknown error")}
                    else:
                        return {"error": f"API returned status {response.status_code}"}

            except Exception as e:
                return {"error": f"Failed to fetch exchange rate: {str(e)}"}
        else:
            # Fallback: 무료 API 사용 (exchangerate.host)
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        "https://api.exchangerate.host/latest",
                        params={
                            "base": from_currency,
                            "symbols": to_currency
                        },
                        timeout=10.0
                    )

                    if response.status_code == 200:
                        data = response.json()
                        if data.get("success"):
                            rate = data.get("rates", {}).get(to_currency)
                            return {
                                "from": from_currency,
                                "to": to_currency,
                                "rate": rate,
                                "date": data.get("date"),
                                "source": "exchangerate.host (free tier)"
                            }
                        else:
                            return {"error": "Failed to get exchange rate"}
                    else:
                        return {"error": f"API returned status {response.status_code}"}

            except Exception as e:
                return {"error": f"Failed to fetch exchange rate: {str(e)}"}

    async def _call_stock_api(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """주식 정보 API 호출"""
        ticker = params.get('ticker')

        if not ticker:
            return {"error": "No stock ticker provided"}

        # 제공자에 따라 다른 API 사용
        if settings.STOCK_API_PROVIDER == "financialdatasets" and settings.FINANCIALDATASETS_API_KEY:
            return await self._call_financialdatasets_api(ticker)
        else:
            # 기본값: Yahoo Finance (무료)
            return await self._call_yahoo_finance_api(ticker)

    async def _call_yahoo_finance_api(self, ticker: str) -> Dict[str, Any]:
        """Yahoo Finance를 사용한 주식 정보 조회"""
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            hist = stock.history(period="1d")

            result = {
                "ticker": ticker,
                "name": info.get("longName", info.get("shortName", ticker)),
                "currency": info.get("currency", "USD"),
                "exchange": info.get("exchange", "N/A"),
            }

            # 현재 가격 정보
            if not hist.empty:
                latest = hist.iloc[-1]
                result["current_price"] = float(latest['Close'])
                result["open"] = float(latest['Open'])
                result["high"] = float(latest['High'])
                result["low"] = float(latest['Low'])
                result["volume"] = int(latest['Volume'])

                if len(hist) > 1:
                    prev_close = hist.iloc[-2]['Close']
                    change = latest['Close'] - prev_close
                    change_percent = (change / prev_close) * 100
                    result["change"] = f"{change:+.2f}"
                    result["change_percent"] = f"{change_percent:+.2f}%"

            # 추가 정보
            result["market_cap"] = info.get("marketCap")
            result["pe_ratio"] = info.get("trailingPE")
            result["dividend_yield"] = info.get("dividendYield")
            result["52week_high"] = info.get("fiftyTwoWeekHigh")
            result["52week_low"] = info.get("fiftyTwoWeekLow")
            result["average_volume"] = info.get("averageVolume")

            # 재무제표 정보 조회
            financial_data = await self._get_financial_statements(ticker, stock)
            if financial_data:
                result["financial_statements"] = financial_data

            return result

        except Exception as e:
            return {"error": f"Failed to fetch stock data for {ticker}: {str(e)}"}

    async def _call_financialdatasets_api(self, ticker: str) -> Dict[str, Any]:
        """FinancialDatasets.ai API를 사용한 주식 정보 조회"""
        if not settings.FINANCIALDATASETS_API_KEY:
            return {"error": "FinancialDatasets API key not configured"}

        try:
            async with httpx.AsyncClient() as client:
                # 주식 가격 정보
                response = await client.get(
                    f"https://api.financialdatasets.ai/stock/price/{ticker}",
                    headers={"X-API-KEY": settings.FINANCIALDATASETS_API_KEY},
                    timeout=10.0
                )

                if response.status_code == 200:
                    data = response.json()
                    result = {
                        "ticker": ticker,
                        "current_price": data.get("price"),
                        "change": data.get("change"),
                        "change_percent": data.get("change_percent"),
                        "volume": data.get("volume"),
                        "market_cap": data.get("market_cap"),
                        "source": "financialdatasets.ai"
                    }

                    # 재무제표 정보
                    financials_response = await client.get(
                        f"https://api.financialdatasets.ai/stock/financials/{ticker}",
                        headers={"X-API-KEY": settings.FINANCIALDATASETS_API_KEY},
                        timeout=10.0
                    )

                    if financials_response.status_code == 200:
                        result["financial_statements"] = financials_response.json()

                    return result
                else:
                    return {"error": f"API returned status {response.status_code}"}

        except Exception as e:
            return {"error": f"Failed to fetch stock data: {str(e)}"}

    async def _get_financial_statements(self, ticker: str, stock: Optional[yf.Ticker] = None) -> Optional[Dict[str, Any]]:
        """재무제표 정보 조회 (Yahoo Finance 사용)"""
        try:
            if stock is None:
                stock = yf.Ticker(ticker)

            financials = {}

            # 손익계산서
            if hasattr(stock, 'financials') and stock.financials is not None and not stock.financials.empty:
                income_stmt = stock.financials.iloc[:, 0].to_dict()
                financials["income_statement"] = {
                    "total_revenue": income_stmt.get("Total Revenue"),
                    "gross_profit": income_stmt.get("Gross Profit"),
                    "operating_income": income_stmt.get("Operating Income"),
                    "net_income": income_stmt.get("Net Income"),
                    "ebitda": income_stmt.get("EBITDA"),
                }

            # 대차대조표
            if hasattr(stock, 'balance_sheet') and stock.balance_sheet is not None and not stock.balance_sheet.empty:
                balance_sheet = stock.balance_sheet.iloc[:, 0].to_dict()
                financials["balance_sheet"] = {
                    "total_assets": balance_sheet.get("Total Assets"),
                    "total_liabilities": balance_sheet.get("Total Liabilities Net Minority Interest"),
                    "stockholders_equity": balance_sheet.get("Stockholders Equity"),
                    "cash": balance_sheet.get("Cash And Cash Equivalents"),
                    "total_debt": balance_sheet.get("Total Debt"),
                }

            # 현금흐름표
            if hasattr(stock, 'cashflow') and stock.cashflow is not None and not stock.cashflow.empty:
                cashflow = stock.cashflow.iloc[:, 0].to_dict()
                financials["cash_flow"] = {
                    "operating_cash_flow": cashflow.get("Operating Cash Flow"),
                    "investing_cash_flow": cashflow.get("Investing Cash Flow"),
                    "financing_cash_flow": cashflow.get("Financing Cash Flow"),
                    "free_cash_flow": cashflow.get("Free Cash Flow"),
                }

            return financials if financials else None

        except Exception:
            # 재무제표 조회 실패는 전체 결과를 망치지 않도록 None 반환
            return None


class FileProcessingAgent(GenerationAgent):
    """파일 처리 에이전트"""
    
    def __init__(self):
        super().__init__(
            name="file_processing",
            generation_type="file",
            role="File Processing Specialist",
            goal="Process, analyze, and manipulate various types of files",
            backstory="You are expert at handling different file formats and extracting meaningful information from documents."
        )
    
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}
        
        try:
            # 파일 처리 요청인지 확인
            file_requirements = self._analyze_file_requirements(query)
            
            if not file_requirements["needs_file_processing"]:
                return {
                    "success": False,
                    "error": "Query does not require file processing"
                }
            
            # 파일 처리 실행
            processing_result = await self._process_files(file_requirements, context)
            
            return self.format_output(processing_result, {"generation_type": "file"})
            
        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    def _analyze_file_requirements(self, query: str) -> Dict[str, Any]:
        """파일 처리 요구사항 분석"""
        file_keywords = [
            "파일", "문서", "엑셀", "pdf", "csv", "분석",
            "file", "document", "excel", "spreadsheet", "analyze"
        ]
        
        processing_types = {
            "analysis": ["분석", "analyze", "analysis", "통계"],
            "conversion": ["변환", "convert", "transformation"],
            "extraction": ["추출", "extract", "parsing"],
            "summary": ["요약", "summary", "summarize"]
        }
        
        needs_processing = any(keyword in query.lower() for keyword in file_keywords)
        
        detected_types = []
        for proc_type, keywords in processing_types.items():
            if any(keyword in query.lower() for keyword in keywords):
                detected_types.append(proc_type)
        
        return {
            "needs_file_processing": needs_processing,
            "processing_types": detected_types,
            "priority": detected_types[0] if detected_types else "analysis"
        }
    
    async def _process_files(self, requirements: Dict[str, Any], context: Dict[str, Any]) -> GenerationResult:
        """파일 처리 실행"""
        # 실제 구현에서는 업로드된 파일을 처리
        # 여기서는 예시 결과 반환
        
        processing_results = []
        
        for proc_type in requirements["processing_types"]:
            if proc_type == "analysis":
                result = {
                    "type": "data_analysis",
                    "summary": "파일 데이터 분석 완료",
                    "statistics": {"rows": 1000, "columns": 15}
                }
            elif proc_type == "extraction":
                result = {
                    "type": "data_extraction",
                    "extracted_data": {"key_fields": ["name", "date", "value"]},
                    "success_rate": 0.95
                }
            else:
                result = {
                    "type": proc_type,
                    "message": f"{proc_type} 처리 완료"
                }
            
            processing_results.append(result)

        return GenerationResult(
            content_type="file_processing",
            content={"processing_results": processing_results},
            metadata={
                "total_operations": len(processing_results),
                "processing_types": requirements["processing_types"]
            }
        )


class TaskCreationAgent(GenerationAgent):
    """작업 생성 에이전트"""
    
    def __init__(self):
        super().__init__(
            name="task_creation",
            generation_type="task",
            role="Task Creation Specialist",
            goal="Create structured tasks, workflows, and action plans based on user requirements",
            backstory="You excel at breaking down complex requirements into actionable tasks and creating organized workflows."
        )
    
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}
        
        try:
            # 작업 생성 요청인지 확인
            task_requirements = self._analyze_task_requirements(query)
            
            if not task_requirements["needs_task_creation"]:
                return {
                    "success": False,
                    "error": "Query does not require task creation"
                }
            
            # 작업 생성 실행
            task_result = await self._create_tasks(task_requirements, context)
            
            return self.format_output(task_result, {"generation_type": "task"})
            
        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    def _analyze_task_requirements(self, query: str) -> Dict[str, Any]:
        """작업 생성 요구사항 분석"""
        task_keywords = [
            "작업", "계획", "할일", "단계", "프로세스",
            "task", "plan", "todo", "step", "process", "workflow"
        ]
        
        task_types = {
            "project": ["프로젝트", "project"],
            "research": ["연구", "조사", "research", "study"],
            "analysis": ["분석", "analysis", "analyze"],
            "development": ["개발", "development", "build", "create"]
        }
        
        needs_tasks = any(keyword in query.lower() for keyword in task_keywords)
        
        detected_types = []
        for task_type, keywords in task_types.items():
            if any(keyword in query.lower() for keyword in keywords):
                detected_types.append(task_type)
        
        return {
            "needs_task_creation": needs_tasks,
            "task_types": detected_types,
            "complexity": self._assess_complexity(query)
        }
    
    def _assess_complexity(self, query: str) -> str:
        """작업 복잡도 평가"""
        complex_indicators = ["복잡", "상세", "완전", "comprehensive", "detailed", "complex"]
        simple_indicators = ["간단", "빠른", "기본", "simple", "quick", "basic"]
        
        if any(indicator in query.lower() for indicator in complex_indicators):
            return "high"
        elif any(indicator in query.lower() for indicator in simple_indicators):
            return "low"
        else:
            return "medium"
    
    async def _create_tasks(self, requirements: Dict[str, Any], context: Dict[str, Any]) -> GenerationResult:
        """작업 생성 실행"""
        complexity = requirements["complexity"]
        task_types = requirements["task_types"]

        # 복잡도에 따른 작업 생성
        if complexity == "high":
            tasks = self._generate_detailed_tasks(task_types)
        elif complexity == "low":
            tasks = self._generate_simple_tasks(task_types)
        else:
            tasks = self._generate_standard_tasks(task_types)

        return GenerationResult(
            content_type="task_list",
            content={
                "tasks": tasks,
                "total_tasks": len(tasks),
                "estimated_duration": self._estimate_duration(tasks)
            },
            metadata={
                "complexity": complexity,
                "task_types": task_types
            }
        )

    def _generate_detailed_tasks(self, task_types: List[str]) -> List[Dict[str, Any]]:
        """상세 작업 목록 생성"""
        return [
            {
                "id": 1,
                "title": "요구사항 분석 및 정의",
                "description": "프로젝트의 상세 요구사항을 분석하고 명확히 정의합니다.",
                "priority": "high",
                "estimated_hours": 8,
                "dependencies": []
            },
            {
                "id": 2,
                "title": "리서치 및 조사",
                "description": "관련 기술, 도구, 방법론에 대한 심층 조사를 진행합니다.",
                "priority": "high", 
                "estimated_hours": 16,
                "dependencies": [1]
            },
            {
                "id": 3,
                "title": "설계 및 계획 수립",
                "description": "전체 시스템 설계와 구현 계획을 수립합니다.",
                "priority": "medium",
                "estimated_hours": 12,
                "dependencies": [1, 2]
            }
        ]
    
    def _generate_simple_tasks(self, task_types: List[str]) -> List[Dict[str, Any]]:
        """간단한 작업 목록 생성"""
        return [
            {
                "id": 1,
                "title": "기본 조사",
                "description": "필요한 정보를 빠르게 조사합니다.",
                "priority": "medium",
                "estimated_hours": 2,
                "dependencies": []
            },
            {
                "id": 2,
                "title": "실행 및 완료",
                "description": "조사한 내용을 바탕으로 작업을 실행합니다.",
                "priority": "high",
                "estimated_hours": 4,
                "dependencies": [1]
            }
        ]

    def _generate_standard_tasks(self, task_types: List[str]) -> List[Dict[str, Any]]:
        """표준 작업 목록 생성"""
        return [
            {
                "id": 1,
                "title": "계획 수립",
                "description": "작업 계획을 수립합니다.",
                "priority": "high",
                "estimated_hours": 4,
                "dependencies": []
            },
            {
                "id": 2,
                "title": "자료 수집",
                "description": "필요한 자료와 정보를 수집합니다.",
                "priority": "medium",
                "estimated_hours": 6,
                "dependencies": [1]
            },
            {
                "id": 3,
                "title": "분석 및 실행",
                "description": "수집한 자료를 분석하고 작업을 실행합니다.",
                "priority": "high",
                "estimated_hours": 8,
                "dependencies": [2]
            }
        ]
    
    def _estimate_duration(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """소요 시간 추정"""
        total_hours = sum(task.get("estimated_hours", 0) for task in tasks)
        
        return {
            "total_hours": total_hours,
            "total_days": total_hours // 8,
            "working_weeks": total_hours // 40
        }
