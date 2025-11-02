"""WebLookUp CLI 명령어 테스트 스크립트"""

print("=" * 80)
print("WebLookUp CLI 명령어 사용 가이드")
print("=" * 80)

print("""
1. 단일 URL 분석:
   uv run python -m neos.cli workflow web-lookup https://www.example.com

2. 다중 URL 비교:
   uv run python -m neos.cli workflow web-lookup https://github.com https://gitlab.com

3. 특정 질문과 함께:
   uv run python -m neos.cli workflow web-lookup https://blog.openai.com/chatgpt --query "이 글의 핵심 내용은?"

4. JSON 출력:
   uv run python -m neos.cli workflow web-lookup https://www.anthropic.com/claude --output json

5. 자세한 출력 (verbose):
   uv run python -m neos.cli workflow web-lookup https://example.com -v

6. 커스텀 사용자/세션:
   uv run python -m neos.cli workflow web-lookup https://example.com --user-id my_user --session-id my_session
""")

print("=" * 80)
print("주요 기능")
print("=" * 80)

print("""
✅ TrackedLLM 통합:
   - WebLookUp 에이전트는 이미 TrackedLLM을 사용하고 있습니다
   - LLM 호출이 자동으로 추적되어 데이터셋에 저장됩니다
   - workflow_step: "web_lookup"
   - tags: ["web_content", "analysis"]

✅ CLI 명령어 추가:
   - workflow web-lookup 명령어 추가됨
   - 다중 URL 지원 (nargs=-1)
   - 선택적 질문 파라미터 (--query)
   - JSON/Text 출력 형식 선택
   - Progress bar와 상세한 결과 표시

✅ 결과 표시:
   - URL 목록 테이블
   - 소스 상세 정보 테이블
   - Rich Markdown 형식의 분석 결과
   - 실행 시간 및 품질 점수

✅ 에러 처리:
   - 타임아웃 설정 (URL당 30초)
   - 상세한 에러 메시지
   - Verbose 모드에서 Traceback 표시
""")

print("=" * 80)
print("테스트 예시")
print("=" * 80)

print("""
# example.com은 항상 접근 가능한 테스트 사이트입니다
uv run python -m neos.cli workflow web-lookup https://www.example.com

# Wikipedia 페이지 분석
uv run python -m neos.cli workflow web-lookup https://en.wikipedia.org/wiki/Artificial_intelligence --query "AI의 역사를 간단히 요약해줘"
""")

print("\n" + "=" * 80)
print("구현 완료!")
print("=" * 80)
