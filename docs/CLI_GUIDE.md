# NEOS CLI 가이드

## 📋 개요

NEOS CLI는 에이전트와 워크플로우를 테스트하고 관리하는 강력한 명령줄 도구입니다.

## 🚀 기본 사용법

```bash
python -m neos.cli [COMMAND] [OPTIONS]
```

## 📚 주요 명령어

### 1. 시스템 상태 확인

```bash
# 전체 시스템 상태 체크
python neos/cli.py status

# 설정 확인
python neos/cli.py config
```

### 2. 워크플로우 테스트

#### 기본 테스트
```bash
python neos/cli.py workflow test "2025년 AI 트렌드를 분석해주세요"
```

#### 옵션 사용
```bash
# JSON 출력
python neos/cli.py workflow test "쿼리" --output json

# 커스텀 사용자/세션
python neos/cli.py workflow test "쿼리" --user-id my_user --session-id my_session
```

### 3. WebLookUp Agent

#### 단일 URL 분석
```bash
python -m neos.cli workflow web-lookup https://www.example.com
```

#### 다중 URL 비교
```bash
python -m neos.cli workflow web-lookup https://github.com https://gitlab.com
```

#### 특정 질문과 함께
```bash
python -m neos.cli workflow web-lookup https://blog.openai.com/chatgpt \
  --query "이 글의 핵심 내용은?"
```

#### 동적 페이지 렌더링 (Playwright)
```bash
python -m neos.cli workflow web-lookup https://spa-app.com --dynamic
```

#### JSON 출력
```bash
python -m neos.cli workflow web-lookup https://example.com --output json
```

### 4. Deep Research

```bash
python -m neos.cli workflow deep-research "AI 반도체 시장 전망"
```

### 5. HyperDeepResearch

```bash
python -m neos.cli workflow hyper-deep-research "2025년 글로벌 AI 시장 전망"
```

### 6. 개별 에이전트 테스트

```bash
# 검색 에이전트
python neos/cli.py agent test-agent knowledge_search "AI 최신 트렌드"
python neos/cli.py agent test-agent realtime_info_search "2024년 기술 뉴스"

# 분석 에이전트
python neos/cli.py agent test-agent data_analysis "시장 데이터 분석"

# 결과를 JSON으로
python neos/cli.py agent test-agent knowledge_search "AI 트렌드" --output json
```

### 7. 에이전트 벤치마크

```bash
# 카테고리별 벤치마크
python neos/cli.py agent benchmark-agent --category search
python neos/cli.py agent benchmark-agent --category analysis
python neos/cli.py agent benchmark-agent --category all

# 병렬 실행
python neos/cli.py agent benchmark-agent --category all --concurrent
```

### 8. 워크플로우 벤치마크

```bash
# 기본 쿼리들로 벤치마크
python neos/cli.py workflow benchmark

# 특정 쿼리들로
python neos/cli.py workflow benchmark \
  -q "AI 트렌드" \
  -q "스마트폰 비교" \
  -q "이미지 생성"

# 파일에서 쿼리 로드
python neos/cli.py workflow benchmark --file tests/sample_queries.txt

# 병렬 실행
python neos/cli.py workflow benchmark --concurrent
```

### 9. 대화형 모드

```bash
python neos/cli.py interactive
```

대화형 모드 명령어:
- `쿼리 입력` - 워크플로우 실행
- `agent [agent_name] [query]` - 특정 에이전트 테스트
- `status` - 상태 확인
- `help` - 도움말
- `exit` - 종료

### 10. MCP 테스트

```bash
# MCP 서버 및 도구 상태 확인
python neos/cli.py mcp status

# 웹 검색 테스트
python -m neos.cli mcp test-tool web_search_mcp \
  -p '{"query":"Python 최신 기능","max_results":5}'

# 모든 도구 일괄 테스트
python -m neos.cli mcp test-all

# 새 도구 템플릿 생성
python -m neos.cli mcp register custom_api api_integration \
  -d "커스텀 API 도구"
```

### 11. 데이터셋 관리

```bash
# 수집 상태 확인
python -m neos.cli dataset status

# 데이터셋 내보내기
python -m neos.cli dataset export -f jsonl
python -m neos.cli dataset export -f openai    # OpenAI fine-tuning
python -m neos.cli dataset export -f anthropic # Anthropic

# 특정 세션/에이전트 데이터만
python -m neos.cli dataset export --session <session_id>
python -m neos.cli dataset export --agent realtime_info_search

# 수집 활성화/비활성화
python -m neos.cli dataset enable
python -m neos.cli dataset disable

# 데이터 초기화
python -m neos.cli dataset clear

# 저장된 파일 목록
python -m neos.cli dataset list-files
```

## 🎯 API 호출 에이전트 사용법

### 날씨 API
```bash
python -m neos.cli workflow test "서울 날씨 알려줘"
python -m neos.cli workflow test "뉴욕의 현재 기온과 습도 알려줘"
```

### 환율 API
```bash
python -m neos.cli workflow test "달러 원화 환율"
python -m neos.cli workflow test "EUR to JPY 환율"
```

### 주식 API
```bash
# 주가 조회
python -m neos.cli workflow test "AAPL 주식 가격"
python -m neos.cli workflow test "애플 주가는?"
python -m neos.cli workflow test "삼성전자 주가"

# 재무제표
python -m neos.cli workflow test "애플 재무제표 보여줘"
python -m neos.cli workflow test "엔비디아의 매출과 순이익은?"
```

## ⚙️ 전역 옵션

```bash
# Verbose 모드
python -m neos.cli -v workflow test "쿼리"

# 성능 프로파일링
python -m neos.cli -p workflow test "쿼리"

# 버전 확인
python -m neos.cli --version
```

## 🔧 환경 변수

CLI는 다음 환경 변수를 사용합니다:

```bash
# 필수
export OPENAI_API_KEY="your-key"
export TAVILY_API_KEY="your-key"

# 선택사항
export OPENWEATHER_API_KEY="your-key"
export EXCHANGERATE_API_KEY="your-key"
export DATABASE_URL="postgresql://..."
export REDIS_URL="redis://..."
```

## 📊 테스트 마커

pytest를 사용한 테스트:

```bash
# 마커별 실행
pytest -m unit          # 단위 테스트
pytest -m integration   # 통합 테스트
pytest -m agents        # 에이전트 테스트
pytest -m workflow      # 워크플로우 테스트
pytest -m api           # API 테스트
pytest -m slow          # 느린 테스트

# 마커 제외
pytest -m "not slow"    # 느린 테스트 제외
```

## 🐛 문제 해결

### 테스트 실패 시
```bash
# 상세한 에러 정보
pytest -vvv --tb=long --no-header

# 특정 테스트만 디버깅
pytest tests/test_agents.py::TestSearchAgents::test_knowledge_search_agent_creation -vvs

# 로그 출력 포함
pytest --log-cli-level=DEBUG
```

### 환경 문제 시
```bash
# 의존성 재설치
make clean install

# Docker 환경 재시작
make docker-restart

# 전체 환경 정리 후 재구성
make dev-clean dev-setup
```

## 💡 팁

1. **탭 완성**: 일부 셸에서 명령어 자동완성 지원
2. **별칭 설정**: 자주 사용하는 명령어는 alias 설정
   ```bash
   alias neos="python -m neos.cli"
   alias neos-web="python -m neos.cli workflow web-lookup"
   ```
3. **출력 리다이렉션**: JSON 출력을 파일로 저장
   ```bash
   python -m neos.cli workflow test "쿼리" --output json > result.json
   ```

## 🔗 관련 문서

- [WebLookUp Agent 가이드](./WEB_LOOKUP_AGENT.md)
- [Playwright 설정](./PLAYWRIGHT_SETUP.md)
- [API 문서](./API_REFERENCE.md)
