"""Web content lookup agent - fetches and analyzes specific URLs"""

from typing import Dict, Any, List, TYPE_CHECKING, Optional
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from langchain_core.messages import HumanMessage

from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm
from neos.utils.url_detector import extract_urls, is_valid_url

from ..base import SearchAgent

if TYPE_CHECKING:
    from neos.workflow.state import SearchResult

# Playwright는 선택적 의존성
try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("[WARNING] Playwright not installed. Dynamic page rendering will not be available.")


class WebLookUpAgent(SearchAgent):
    """웹 콘텐츠 조회 에이전트

    사용자가 제공한 특정 URL들을 방문하여 내용을 추출하고 분석합니다.
    """

    def __init__(self, use_playwright: bool = False):
        super().__init__(
            name="web_lookup",
            search_type="web_content",
            role="Web Content Analyzer",
            goal="Fetch and analyze content from specific URLs provided by the user",
            backstory="You specialize in extracting and analyzing web page content from user-provided URLs."
        )
        self.session = None
        self.use_playwright = use_playwright and PLAYWRIGHT_AVAILABLE

        if use_playwright and not PLAYWRIGHT_AVAILABLE:
            print("[WARNING] Playwright requested but not available. Falling back to static HTML fetching.")
            print("[INFO] Install Playwright: pip install playwright && playwright install")

    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """URL에서 콘텐츠를 추출하고 분석합니다.

        Args:
            query: 사용자 쿼리 (URL 포함)
            context: 실행 컨텍스트

        Returns:
            실행 결과
        """
        print(f"[DEBUG] WebLookUpAgent.execute called with query: {query[:100]}...")

        if not self.validate_input(query, context):
            print("[ERROR] WebLookUpAgent: Invalid input")
            return {"success": False, "error": "Invalid input"}

        # URL 추출
        urls = extract_urls(query)
        if not urls:
            print("[WARNING] No URLs found in query")
            return self.format_output([], {
                "search_type": "web_lookup",
                "warning": "No URLs found in query"
            })

        print(f"[DEBUG] Found {len(urls)} URLs to look up: {urls}")

        # 유효한 URL만 필터링
        valid_urls = [url for url in urls if is_valid_url(url)]
        if not valid_urls:
            print("[WARNING] No valid URLs found")
            return self.format_output([], {
                "search_type": "web_lookup",
                "warning": "No valid URLs found"
            })

        print(f"[DEBUG] Processing {len(valid_urls)} valid URLs")

        try:
            # 컨텍스트에서 렌더링 방식 확인
            use_dynamic = context.get("use_playwright", self.use_playwright) if context else self.use_playwright

            # 각 URL에서 콘텐츠 추출
            if use_dynamic:
                print("[DEBUG] Using Playwright for dynamic rendering")
                contents = await self._fetch_urls_with_playwright(valid_urls)
            else:
                print("[DEBUG] Using static HTML fetching")
                contents = await self._fetch_urls(valid_urls)

            print(f"[DEBUG] Fetched content from {len(contents)} URLs")

            # 컨텍스트에서 메타정보 추출
            session_id = context.get("session_id", "") if context else ""
            user_id = context.get("user_id", "") if context else ""
            detected_language = context.get("detected_language", "ko") if context else "ko"

            # LLM으로 콘텐츠 분석
            processed_results = await self._process_with_llm(
                query, contents, valid_urls,
                session_id=session_id,
                user_id=user_id,
                detected_language=detected_language
            )
            print(f"[DEBUG] LLM processing returned {len(processed_results)} results")

            result = self.format_output(processed_results, {
                "search_type": "web_lookup",
                "urls_processed": len(valid_urls)
            })
            print("[DEBUG] WebLookUpAgent execution completed successfully")
            return result

        except Exception as e:
            print(f"[ERROR] WebLookUpAgent execution failed: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e), "agent": self.name}

    async def _fetch_urls(self, urls: List[str]) -> List[Dict[str, Any]]:
        """여러 URL에서 콘텐츠를 병렬로 가져옵니다.

        Args:
            urls: 가져올 URL 리스트

        Returns:
            URL별 콘텐츠 정보 리스트
        """
        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch_single_url(session, url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 성공한 결과만 반환
            valid_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"[ERROR] Failed to fetch {urls[i]}: {result}")
                elif result:
                    valid_results.append(result)

            return valid_results

    async def _fetch_single_url(
        self,
        session: aiohttp.ClientSession,
        url: str
    ) -> Dict[str, Any]:
        """단일 URL에서 콘텐츠를 가져옵니다.

        Args:
            session: aiohttp 세션
            url: 가져올 URL

        Returns:
            URL 콘텐츠 정보
        """
        try:
            print(f"[DEBUG] Fetching content from: {url}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            async with session.get(url, headers=headers, timeout=30) as response:
                if response.status != 200:
                    print(f"[WARNING] HTTP {response.status} for {url}")
                    return None

                content_type = response.headers.get('Content-Type', '')

                # HTML 콘텐츠만 처리
                if 'text/html' not in content_type:
                    print(f"[WARNING] Non-HTML content type for {url}: {content_type}")
                    return None

                html = await response.text()

                # BeautifulSoup으로 파싱
                soup = BeautifulSoup(html, 'html.parser')

                # 메타데이터 추출
                title = self._extract_title(soup)
                description = self._extract_description(soup)
                main_content = self._extract_main_content(soup)

                print(f"[DEBUG] Successfully extracted content from {url}")
                print(f"[DEBUG] Title: {title}")
                print(f"[DEBUG] Content length: {len(main_content)} characters")

                return {
                    'url': url,
                    'title': title,
                    'description': description,
                    'content': main_content,
                    'status': 'success'
                }

        except asyncio.TimeoutError:
            print(f"[ERROR] Timeout fetching {url}")
            return None
        except Exception as e:
            print(f"[ERROR] Error fetching {url}: {e}")
            return None

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """HTML에서 제목 추출"""
        # <title> 태그
        if soup.title and soup.title.string:
            return soup.title.string.strip()

        # og:title 메타 태그
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title['content'].strip()

        # <h1> 태그
        h1 = soup.find('h1')
        if h1:
            return h1.get_text().strip()

        return "제목 없음"

    def _extract_description(self, soup: BeautifulSoup) -> str:
        """HTML에서 설명 추출"""
        # meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return meta_desc['content'].strip()

        # og:description
        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return og_desc['content'].strip()

        return ""

    def _extract_main_content(self, soup: BeautifulSoup) -> str:
        """HTML에서 주요 콘텐츠 추출"""
        # 불필요한 태그 제거
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            tag.decompose()

        # main, article, content 영역 우선 추출
        main_content = None
        for selector in ['main', 'article', '[role="main"]', '#content', '.content']:
            main_content = soup.select_one(selector)
            if main_content:
                break

        # 찾지 못했으면 body 사용
        if not main_content:
            main_content = soup.body

        if not main_content:
            return ""

        # 텍스트 추출 및 정리
        text = main_content.get_text(separator='\n', strip=True)

        # 연속된 빈 줄 제거
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)

        # 너무 길면 자르기 (최대 10,000자)
        if len(text) > 10000:
            text = text[:10000] + "..."

        return text

    async def _fetch_urls_with_playwright(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Playwright를 사용하여 동적 페이지를 렌더링하고 콘텐츠를 가져옵니다.

        Args:
            urls: 가져올 URL 리스트

        Returns:
            URL별 콘텐츠 정보 리스트
        """
        if not PLAYWRIGHT_AVAILABLE:
            print("[ERROR] Playwright not available")
            return []

        print("[DEBUG] Using Playwright for dynamic page rendering")
        results = []

        async with async_playwright() as p:
            # 브라우저 실행 (headless 모드)
            browser = await p.chromium.launch(headless=True)

            try:
                # 각 URL에 대해 순차 처리 (병렬 처리 시 리소스 문제 가능)
                for url in urls:
                    try:
                        result = await self._fetch_single_url_with_playwright(browser, url)
                        if result:
                            results.append(result)
                    except Exception as e:
                        print(f"[ERROR] Failed to fetch {url} with Playwright: {e}")

            finally:
                await browser.close()

        return results

    async def _fetch_single_url_with_playwright(
        self,
        browser: "Browser",
        url: str
    ) -> Optional[Dict[str, Any]]:
        """Playwright를 사용하여 단일 URL을 렌더링하고 콘텐츠를 가져옵니다.

        Args:
            browser: Playwright 브라우저 인스턴스
            url: 가져올 URL

        Returns:
            URL 콘텐츠 정보
        """
        print(f"[DEBUG] Fetching (Playwright): {url}")

        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )

        try:
            page = await context.new_page()

            # 페이지 로드 (네트워크 idle 대기)
            await page.goto(url, wait_until='networkidle', timeout=30000)

            # JavaScript 실행 완료를 위한 추가 대기
            await page.wait_for_timeout(2000)

            # 페이지 내용 가져오기
            html = await page.content()

            # BeautifulSoup으로 파싱
            soup = BeautifulSoup(html, 'html.parser')

            # 메타데이터 추출
            title = self._extract_title(soup)
            description = self._extract_description(soup)
            main_content = self._extract_main_content(soup)

            # 스크린샷 캡처 (선택사항, 디버깅용)
            # await page.screenshot(path=f'screenshot_{hash(url)}.png')

            await page.close()

            print(f"[DEBUG] Successfully extracted content from {url} (Playwright)")
            print(f"[DEBUG] Title: {title}")
            print(f"[DEBUG] Content length: {len(main_content)} characters")

            return {
                'url': url,
                'title': title,
                'description': description,
                'content': main_content,
                'status': 'success',
                'rendering_method': 'playwright'
            }

        except asyncio.TimeoutError:
            print(f"[ERROR] Timeout fetching {url} with Playwright")
            return None
        except Exception as e:
            print(f"[ERROR] Error fetching {url} with Playwright: {e}")
            return None
        finally:
            await context.close()

    async def _process_with_llm(
        self,
        query: str,
        contents: List[Dict[str, Any]],
        urls: List[str],
        session_id: str = "",
        user_id: str = "",
        detected_language: str = "ko"
    ) -> List["SearchResult"]:
        """LLM을 사용하여 웹 콘텐츠를 분석합니다.

        Args:
            query: 사용자 쿼리
            contents: 추출된 콘텐츠 리스트
            urls: URL 리스트
            session_id: 세션 ID
            user_id: 사용자 ID
            detected_language: 감지된 언어

        Returns:
            분석된 SearchResult 리스트
        """
        try:
            if not contents:
                print("[WARNING] No content to process with LLM")
                return []

            print(f"[DEBUG] Processing {len(contents)} web contents with LLM...")

            # LLM 인스턴스 생성
            base_llm = create_llm(temperature=0.1, max_tokens=4000)

            # 추적 래퍼 적용
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="web_lookup",
                agent_name=self.name,
                tags=["web_content", "analysis"]
            )

            # 콘텐츠 컨텍스트 준비
            content_context = self._prepare_content_context(contents)

            # 분석 프롬프트 생성
            prompt = self._create_analysis_prompt(query, content_context, detected_language)

            print("[DEBUG] Sending request to LLM for content analysis...")
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            llm_response = response.content

            print(f"[DEBUG] LLM response length: {len(llm_response)} characters")

            from neos.workflow.state import SearchResult

            # LLM 분석 결과를 SearchResult로 변환
            processed_result = SearchResult(
                source="llm_processed_web_lookup",
                title=f"웹 콘텐츠 분석: {query}",
                content=llm_response,
                url="",  # 여러 URL을 종합한 결과
                score=0.95,
                metadata={
                    "processing_type": "llm_web_content_analysis",
                    "source_count": len(contents),
                    "sources": [
                        {
                            "title": content.get("title", ""),
                            "url": content.get("url", ""),
                            "description": content.get("description", "")
                        }
                        for content in contents
                    ]
                }
            )

            print("[DEBUG] LLM processing completed successfully")
            return [processed_result]

        except Exception as e:
            print(f"[ERROR] LLM processing failed: {e}")
            import traceback
            print(f"[ERROR] LLM processing traceback: {traceback.format_exc()}")

            # 실패 시 원본 콘텐츠 반환
            from neos.workflow.state import SearchResult

            results = []
            for content in contents:
                result = SearchResult(
                    source="web_lookup",
                    title=content.get("title", ""),
                    content=content.get("content", "")[:1000],  # 요약
                    url=content.get("url", ""),
                    score=0.7,
                    metadata={
                        "description": content.get("description", ""),
                        "fallback": True
                    }
                )
                results.append(result)
            return results

    def _prepare_content_context(self, contents: List[Dict[str, Any]]) -> str:
        """웹 콘텐츠를 LLM이 처리할 수 있는 형태로 준비"""
        context_parts = []

        for i, content in enumerate(contents, 1):
            title = content.get("title", "제목 없음")
            url = content.get("url", "")
            description = content.get("description", "")
            text = content.get("content", "")

            # 콘텐츠 길이 제한 (각각 최대 2000자)
            if len(text) > 2000:
                text = text[:2000] + "..."

            context_parts.append(f"""
웹 페이지 {i}:
제목: {title}
URL: {url}
설명: {description}
내용:
{text}
""")

        return "\n---\n".join(context_parts)

    def _create_analysis_prompt(
        self,
        query: str,
        content_context: str,
        detected_language: str = "ko"
    ) -> str:
        """LLM 분석을 위한 프롬프트 생성"""
        language_instructions = {
            "ko": """
사용자 질문: {query}

다음은 사용자가 제공한 URL들에서 추출한 웹 페이지 내용입니다:

{content_context}

위 웹 페이지 내용들을 바탕으로 사용자의 질문에 대해 종합적이고 정확한 답변을 **한국어로** 작성해주세요.

요구사항:
1. 각 웹 페이지의 내용을 명확히 구분하여 설명하세요
2. 각 정보의 출처 URL을 인용하세요
3. 중요한 정보나 핵심 내용을 강조하세요
4. 웹 페이지들 간의 관계나 공통점/차이점이 있다면 설명하세요
5. 정확한 정보만 제공하고, 추측하지 마세요
6. **한국어로 작성하되**, 전문적이고 객관적인 톤을 유지하세요
7. **중요**: 답변을 완전히 작성하세요. 문장이나 문단 중간에 끊지 마세요

답변:""",

            "en": """
User Question: {query}

The following are web page contents extracted from the URLs provided by the user:

{content_context}

Based on the above web page contents, please write a comprehensive and accurate answer to the user's question **in English**.

Requirements:
1. Clearly distinguish and explain the content from each web page
2. Cite the source URL for each piece of information
3. Highlight important information or key points
4. If there are relationships, commonalities, or differences between the web pages, explain them
5. Provide only accurate information, do not speculate
6. **Write in English** while maintaining a professional and objective tone
7. **Important**: Complete your answer fully. Do not stop in the middle of sentences or paragraphs

Answer:""",

            "ja": """
ユーザーの質問: {query}

以下は、ユーザーが提供したURLから抽出されたWebページの内容です:

{content_context}

上記のWebページの内容に基づいて、ユーザーの質問に対する包括的で正確な回答を**日本語で**作成してください。

要件:
1. 各Webページの内容を明確に区別して説明してください
2. 各情報のソースURLを引用してください
3. 重要な情報や核心的な内容を強調してください
4. Webページ間の関係や共通点/相違点があれば説明してください
5. 正確な情報のみを提供し、推測しないでください
6. **日本語で作成し**、プロフェッショナルで客観的なトーンを維持してください
7. **重要**: 回答を完全に作成してください。文章や段落の途中で止めないでください

回答:""",

            "zh": """
用户问题: {query}

以下是从用户提供的URL中提取的网页内容:

{content_context}

基于上述网页内容，请用**中文**撰写对用户问题的全面准确的回答。

要求:
1. 清楚地区分和说明每个网页的内容
2. 引用每条信息的来源URL
3. 突出重要信息或关键点
4. 如果网页之间存在关系、共同点或差异，请说明
5. 仅提供准确的信息，不要推测
6. **用中文撰写**，保持专业客观的语气
7. **重要**: 完整撰写答案。不要在句子或段落中途停止

回答:"""
        }

        template = language_instructions.get(detected_language, language_instructions["ko"])
        return template.format(query=query, content_context=content_context)
