"""
ApiCallAgent 사용 예제

이 스크립트는 ApiCallAgent의 날씨, 환율, 주식 API 통합 기능을 시연합니다.
"""

import asyncio
import json
from neos.agents.generation_agents import ApiCallAgent


async def test_weather_api():
    """날씨 API 테스트"""
    print("\n" + "="*60)
    print("1. Weather API Test")
    print("="*60)
    
    agent = ApiCallAgent()
    
    queries = [
        "서울 날씨 알려줘",
        "What's the weather in Tokyo?",
        "뉴욕의 기온은?"
    ]
    
    for query in queries:
        print(f"\nQuery: {query}")
        result = await agent.execute(query)
        print(f"Result: {json.dumps(result, indent=2, ensure_ascii=False)}")


async def test_currency_api():
    """환율 API 테스트"""
    print("\n" + "="*60)
    print("2. Currency Exchange API Test")
    print("="*60)
    
    agent = ApiCallAgent()
    
    queries = [
        "USD to KRW 환율",
        "달러 원화 환율은?",
        "What's the exchange rate from EUR to JPY?"
    ]
    
    for query in queries:
        print(f"\nQuery: {query}")
        result = await agent.execute(query)
        print(f"Result: {json.dumps(result, indent=2, ensure_ascii=False)}")


async def test_stock_api():
    """주식 API 테스트"""
    print("\n" + "="*60)
    print("3. Stock Market API Test")
    print("="*60)
    
    agent = ApiCallAgent()
    
    queries = [
        "AAPL 주식 가격",
        "Tell me about Tesla stock",
        "엔비디아 주가는?",
        "애플 재무제표 보여줘"
    ]
    
    for query in queries:
        print(f"\nQuery: {query}")
        result = await agent.execute(query)
        
        # 재무제표는 너무 길어서 요약만 표시
        if "financial_statements" in str(result):
            result_copy = result.copy()
            if "content" in result_copy and "api_calls" in result_copy["content"]:
                for api_call in result_copy["content"]["api_calls"]:
                    if "financial_statements" in api_call.get("result", {}):
                        api_call["result"]["financial_statements"] = "[Financial data available]"
            print(f"Result: {json.dumps(result_copy, indent=2, ensure_ascii=False)}")
        else:
            print(f"Result: {json.dumps(result, indent=2, ensure_ascii=False)}")


async def test_mixed_queries():
    """복합 쿼리 테스트"""
    print("\n" + "="*60)
    print("4. Mixed Query Test")
    print("="*60)
    
    agent = ApiCallAgent()
    
    # 여러 API 타입을 동시에 감지하는 쿼리
    query = "오늘 서울 날씨와 달러 환율 알려줘"
    print(f"\nQuery: {query}")
    result = await agent.execute(query)
    print(f"Result: {json.dumps(result, indent=2, ensure_ascii=False)}")


async def main():
    """메인 함수"""
    print("\n")
    print("*" * 60)
    print(" ApiCallAgent Example - API Integration Demo")
    print("*" * 60)
    print("\nNote: Make sure you have set up your API keys in .env file")
    print("See .env.template for configuration options")
    
    try:
        # 날씨 API 테스트
        await test_weather_api()
        
        # 환율 API 테스트
        await test_currency_api()
        
        # 주식 API 테스트
        await test_stock_api()
        
        # 복합 쿼리 테스트
        await test_mixed_queries()
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*60)
    print("✅ All tests completed!")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
