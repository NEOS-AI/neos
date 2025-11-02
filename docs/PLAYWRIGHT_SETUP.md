# Playwright 설치 및 설정 가이드

## 📋 개요

Playwright는 동적 웹 페이지 렌더링을 위한 브라우저 자동화 라이브러리입니다. WebLookUp Agent에서 JavaScript로 렌더링되는 페이지를 처리할 때 사용됩니다.

## 🚀 설치

### 1. Playwright 패키지 설치

```bash
pip install playwright
```

또는

```bash
uv pip install playwright
```

### 2. 브라우저 설치

Playwright는 실제 브라우저 바이너리를 다운로드해야 합니다:

```bash
playwright install chromium
```

전체 브라우저 설치 (선택사항):

```bash
playwright install
```

### 3. 설치 확인

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto('https://www.example.com')
    print(page.title())
    browser.close()
```

## 📦 시스템 요구사항

### macOS
```bash
# 추가 시스템 의존성 불필요
playwright install chromium
```

### Linux (Ubuntu/Debian)
```bash
# 시스템 의존성 설치
sudo playwright install-deps

# 브라우저 설치
playwright install chromium
```

### Windows
```bash
# PowerShell에서 실행
playwright install chromium
```

## 🔧 WebLookUp Agent에서 사용

### 기본 사용법 (정적 HTML)

```bash
# Playwright 없이 사용 (기본)
uv run python -m neos.cli workflow web-lookup https://www.example.com
```

### 동적 페이지 렌더링

```bash
# Playwright로 동적 렌더링
uv run python -m neos.cli workflow web-lookup https://spa-app.com --dynamic
```

### Python 코드에서 사용

```python
from neos.agents.search_agents import WebLookUpAgent

# 정적 HTML 페칭 (기본)
static_agent = WebLookUpAgent(use_playwright=False)

# 동적 페이지 렌더링
dynamic_agent = WebLookUpAgent(use_playwright=True)

# 실행
result = await dynamic_agent.execute(
    query="https://spa-application.com 분석해줘",
    context={
        "session_id": "session_123",
        "user_id": "user_456",
        "detected_language": "ko",
        "use_playwright": True  # Context에서도 제어 가능
    }
)
```

## ⚙️ 설정 옵션

### 브라우저 선택

기본적으로 Chromium을 사용하지만 다른 브라우저도 가능합니다:

```python
# web_lookup.py에서 수정
browser = await p.chromium.launch(headless=True)  # 기본
# browser = await p.firefox.launch(headless=True)
# browser = await p.webkit.launch(headless=True)
```

### Headless 모드

```python
# Headless (백그라운드 실행, 기본)
browser = await p.chromium.launch(headless=True)

# Headed (브라우저 UI 표시, 디버깅용)
browser = await p.chromium.launch(headless=False)
```

### 타임아웃 설정

```python
# 페이지 로드 타임아웃 (기본: 30초)
await page.goto(url, wait_until='networkidle', timeout=30000)

# JavaScript 실행 대기 (기본: 2초)
await page.wait_for_timeout(2000)
```

## 🎯 사용 시나리오

### 정적 HTML만으로 충분한 경우
- 전통적인 서버 렌더링 웹사이트
- 블로그, 뉴스 사이트
- 문서 페이지

```bash
# --dynamic 플래그 없이 실행 (빠름)
uv run python -m neos.cli workflow web-lookup https://blog.example.com
```

### Playwright가 필요한 경우
- React, Vue, Angular 등 SPA (Single Page Application)
- 무한 스크롤이 있는 페이지
- JavaScript로 콘텐츠를 동적 로드하는 페이지
- AJAX로 데이터를 가져오는 페이지

```bash
# --dynamic 플래그 사용 (느리지만 완전한 렌더링)
uv run python -m neos.cli workflow web-lookup https://spa-app.com --dynamic
```

## 🔍 디버깅

### 스크린샷 캡처

`web_lookup.py`에서 스크린샷 기능 활성화:

```python
# 343번 라인 주석 해제
await page.screenshot(path=f'screenshot_{hash(url)}.png')
```

### 브라우저 UI 표시

디버깅 시 브라우저 창을 보고 싶다면:

```python
# web_lookup.py 286번 라인
browser = await p.chromium.launch(headless=False)  # True를 False로 변경
```

### Verbose 로그

```bash
# CLI에서 상세 로그 활성화
uv run python -m neos.cli workflow web-lookup https://example.com --dynamic -v
```

## ⚠️ 주의사항

### 성능
- Playwright는 전체 브라우저를 실행하므로 느립니다
- 정적 HTML 페칭보다 5-10배 느릴 수 있습니다
- 필요한 경우에만 `--dynamic` 플래그 사용

### 리소스
- 메모리 사용량이 높습니다 (URL당 ~100-200MB)
- 동시에 많은 URL 처리 시 주의

### 제한사항
- CAPTCHA가 있는 페이지는 처리 불가
- 로그인이 필요한 페이지는 처리 불가
- 일부 봇 감지 시스템에 차단될 수 있음

## 🆘 문제 해결

### "Executable doesn't exist" 에러

```bash
# 브라우저 재설치
playwright install chromium
```

### Linux에서 의존성 에러

```bash
# 시스템 의존성 설치
sudo playwright install-deps chromium
```

### ImportError: No module named 'playwright'

```bash
# Playwright 재설치
pip install --upgrade playwright
```

### Timeout 에러

```python
# web_lookup.py에서 타임아웃 증가
await page.goto(url, wait_until='networkidle', timeout=60000)  # 60초
```

## 📊 성능 비교

| 방식 | 속도 | 메모리 | 지원 범위 |
|------|------|--------|----------|
| **Static HTML** | ⚡ 빠름 (1-3초) | 💾 적음 (~10MB) | 📄 정적 페이지만 |
| **Playwright** | 🐢 느림 (10-30초) | 💾 많음 (~200MB) | 🎭 모든 페이지 |

## 🔗 참고 자료

- [Playwright 공식 문서](https://playwright.dev/python/)
- [Playwright API Reference](https://playwright.dev/python/docs/api/class-playwright)
- [WebLookUp Agent 가이드](./WEB_LOOKUP_AGENT.md)
