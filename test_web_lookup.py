"""WebLookUpAgent 테스트 스크립트"""

import asyncio
from neos.utils.url_detector import extract_urls, has_urls, is_valid_url


def test_url_detection():
    """URL 감지 테스트"""
    print("=" * 80)
    print("URL 감지 테스트")
    print("=" * 80)

    test_cases = [
        "https://www.example.com에 대해 설명해줘",
        "이 두 사이트를 비교해줘: https://github.com, https://gitlab.com",
        "www.naver.com 내용을 요약해줘",
        "URL이 없는 일반 쿼리입니다",
        "https://blog.openai.com/chatgpt 이 글 분석해줘",
    ]

    for i, query in enumerate(test_cases, 1):
        print(f"\n테스트 {i}: {query}")
        print(f"  URL 포함 여부: {has_urls(query)}")
        urls = extract_urls(query)
        print(f"  추출된 URL: {urls}")
        for url in urls:
            print(f"    - {url} (유효: {is_valid_url(url)})")


def test_classifier_integration():
    """쿼리 분류기 통합 테스트"""
    print("\n" + "=" * 80)
    print("쿼리 분류기 통합 테스트")
    print("=" * 80)

    from neos.workflow.utils.query_classifier import QueryClassifier
    from neos.workflow.state import WorkflowConfig

    config = WorkflowConfig()
    classifier = QueryClassifier(config)

    test_queries = [
        "https://www.anthropic.com/claude에 대해 설명해줘",
        "최신 AI 뉴스를 검색해줘",  # URL 없음 - 일반 검색
    ]

    for query in test_queries:
        print(f"\n쿼리: {query}")
        agents = classifier._determine_required_agents(query, "information_seeking", 0.3)
        print(f"  선택된 에이전트: {agents}")


async def test_web_lookup_agent():
    """WebLookUpAgent 실행 테스트"""
    print("\n" + "=" * 80)
    print("WebLookUpAgent 실행 테스트")
    print("=" * 80)

    from neos.agents.search_agents import WebLookUpAgent

    agent = WebLookUpAgent()

    # 테스트 쿼리 (실제 존재하는 URL)
    test_query = "https://www.example.com 이 사이트에 대해 설명해줘"

    print(f"\n쿼리: {test_query}")
    print("에이전트 실행 중...")

    context = {
        "session_id": "test_session",
        "user_id": "test_user",
        "detected_language": "ko"
    }

    try:
        result = await agent.execute(test_query, context)
        print(f"\n실행 결과:")
        print(f"  성공 여부: {result.get('success')}")
        if result.get('success'):
            print(f"  결과 개수: {len(result.get('result', []))}")
            for i, item in enumerate(result.get('result', [])[:2], 1):
                print(f"\n  결과 {i}:")
                print(f"    제목: {item.title}")
                print(f"    URL: {item.url}")
                print(f"    내용 길이: {len(item.content)} 자")
                print(f"    점수: {item.score}")
        else:
            print(f"  에러: {result.get('error')}")
    except Exception as e:
        print(f"\n에러 발생: {e}")
        import traceback
        traceback.print_exc()


def main():
    """메인 테스트 함수"""
    # 1. URL 감지 테스트
    test_url_detection()

    # 2. 쿼리 분류기 통합 테스트
    test_classifier_integration()

    # 3. WebLookUpAgent 실행 테스트
    print("\n" + "=" * 80)
    print("WebLookUpAgent 실행 테스트를 시작하시겠습니까? (y/n)")
    print("참고: 실제 HTTP 요청과 LLM 호출이 발생합니다.")
    print("=" * 80)

    # asyncio.run(test_web_lookup_agent())
    print("\nWebLookUpAgent 실행 테스트는 주석 처리되어 있습니다.")
    print("실행하려면 test_web_lookup.py 파일에서 주석을 해제하세요.")


if __name__ == "__main__":
    main()
