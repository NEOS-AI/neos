"""YouTube video search and analysis agent"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import asyncio
import logging
import math
from langchain_core.messages import HumanMessage
from langchain_openai import OpenAIEmbeddings

from neos.config.settings import settings
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm
from neos.workflow.state import SearchResult
from neos.tools.manager import mcp_manager

from ..base import SearchAgent


logger = logging.getLogger(__name__)


class ComparisonFocus(Enum):
    """비교 분석 초점"""
    TECHNICAL_DEPTH = "technical_depth"  # 기술적 깊이 중심
    TEACHING_STYLE = "teaching_style"  # 교수법 중심
    PRACTICAL_APPLICATION = "practical_application"  # 실용성 중심
    BEGINNER_FRIENDLY = "beginner_friendly"  # 초보자 친화성
    COMPREHENSIVE = "comprehensive"  # 종합적 비교


class PlaylistOrderStrategy(Enum):
    """플레이리스트 정렬 전략"""
    ORIGINAL = "original"  # 원본 순서 유지
    DIFFICULTY = "difficulty"  # 난이도 순
    POPULARITY = "popularity"  # 인기도 순
    DURATION = "duration"  # 길이 순
    OPTIMAL_LEARNING = "optimal_learning"  # 학습 최적화
    TOPIC_CLUSTERED = "topic_clustered"  # 토픽별 클러스터링
    PREREQUISITE_CHAIN = "prerequisite_chain"  # 선수 학습 순서


@dataclass
class ComparisonConfig:
    """비디오 비교 설정

    USER CONTRIBUTION POINT: 비교 분석의 우선순위와 스타일을 조정할 수 있습니다.
    """
    focus: ComparisonFocus = ComparisonFocus.COMPREHENSIVE
    include_timestamps: bool = False  # 주요 타임스탬프 포함 여부
    emphasize_differences: bool = True  # 차이점 강조
    include_production_quality: bool = True  # 제작 품질 평가
    max_summary_length: str = "medium"  # short, medium, long

    def to_prompt_instructions(self) -> str:
        """설정을 프롬프트 지침으로 변환"""
        instructions = []

        if self.focus == ComparisonFocus.TECHNICAL_DEPTH:
            instructions.append("Focus on technical accuracy, depth of explanation, and complexity level.")
        elif self.focus == ComparisonFocus.TEACHING_STYLE:
            instructions.append("Emphasize teaching methodology, pacing, and pedagogical approach.")
        elif self.focus == ComparisonFocus.PRACTICAL_APPLICATION:
            instructions.append("Prioritize practical examples, real-world applications, and hands-on demonstrations.")
        elif self.focus == ComparisonFocus.BEGINNER_FRIENDLY:
            instructions.append("Evaluate clarity for beginners, prerequisite requirements, and learning curve.")

        if self.emphasize_differences:
            instructions.append("Clearly highlight key differences and unique approaches.")

        if self.include_production_quality:
            instructions.append("Comment on video/audio quality, editing, and presentation style.")

        if self.max_summary_length == "short":
            instructions.append("Keep analysis concise (2-3 sentences per section).")
        elif self.max_summary_length == "long":
            instructions.append("Provide detailed analysis with specific examples.")

        return " ".join(instructions)


@dataclass
class PlaylistAnalysisConfig:
    """플레이리스트 분석 설정

    USER CONTRIBUTION POINT: 플레이리스트 분석의 깊이와 초점을 조정할 수 있습니다.
    """
    detect_duplicates: bool = True  # 중복 비디오 감지
    use_semantic_similarity: bool = False  # 임베딩 기반 의미론적 중복 감지 (API 호출 필요)
    semantic_similarity_threshold: float = 0.85  # 의미론적 유사도 임계값 (0.0-1.0)
    suggest_order: PlaylistOrderStrategy = PlaylistOrderStrategy.OPTIMAL_LEARNING
    analyze_progression: bool = True  # 학습 진행 분석
    identify_gaps: bool = True  # 지식 갭 식별
    max_videos_to_analyze: int = 20  # 분석할 최대 비디오 수
    include_prerequisites: bool = True  # 선수 지식 분석

    def to_prompt_instructions(self) -> str:
        """설정을 프롬프트 지침으로 변환"""
        instructions = []

        if self.analyze_progression:
            instructions.append("Analyze how the playlist builds knowledge progressively.")

        if self.identify_gaps:
            instructions.append("Identify any missing topics or logical gaps in the curriculum.")

        if self.include_prerequisites:
            instructions.append("Clearly state what background knowledge is required.")

        if self.suggest_order != PlaylistOrderStrategy.ORIGINAL:
            instructions.append(f"Suggest an optimal viewing order based on {self.suggest_order.value}.")

        return " ".join(instructions)


class YouTubeSearchAgent(SearchAgent):
    """YouTube 비디오 검색 및 분석 에이전트

    YouTube에서 관련 비디오를 찾고, 트랜스크립트를 분석하여
    가장 유용한 비디오를 추천합니다.
    """

    def __init__(self):
        super().__init__(
            name="youtube_search",
            search_type="video",
            role="YouTube Content Discovery Specialist",
            goal="Find and analyze relevant YouTube videos based on user queries, "
            "providing summaries and recommendations",
            backstory="You are an expert at discovering valuable YouTube content. "
            "You analyze video transcripts, metadata, and quality signals to "
            "recommend the most relevant and helpful videos for any topic."
        )
        self.youtube_tool = None
        self.tool_available = False

    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """YouTube 검색 및 분석 실행

        Args:
            query: 검색 쿼리
            context: 실행 컨텍스트 (session_id, user_id, detected_language 등)

        Returns:
            검색 결과 딕셔너리
        """
        logger.info(f"YouTubeSearchAgent executing query: {query[:50]}...")

        if not self.validate_input(query, context):
            logger.error("YouTubeSearchAgent: Invalid input")
            return {"success": False, "error": "Invalid input"}

        # YouTube 도구 초기화
        if not self.tool_available:
            await self._initialize_tool()

        if not self.tool_available:
            logger.warning("YouTube tool not available, returning empty results")
            return self.format_output(
                [],
                {
                    "search_type": "video",
                    "warning": "YouTube tool not available"
                }
            )

        try:
            # Context 정보 추출
            session_id = context.get("session_id", "") if context else ""
            user_id = context.get("user_id", "") if context else ""
            detected_language = context.get("detected_language", "ko") if context else "ko"
            max_videos = context.get("max_videos", 5) if context else 5

            # 1단계: YouTube 비디오 검색
            logger.info("Step 1: Searching YouTube videos...")
            search_results = await self._search_videos(query, max_videos=max_videos * 2)

            if not search_results:
                logger.warning("No videos found")
                return self.format_output(
                    [],
                    {
                        "search_type": "video",
                        "query": query,
                        "message": "No relevant videos found"
                    }
                )

            logger.info(f"Found {len(search_results)} videos")

            # 2단계: 병렬로 트랜스크립트 가져오기
            logger.info("Step 2: Fetching transcripts...")
            videos_with_transcripts = await self._fetch_transcripts_parallel(
                search_results
            )

            logger.info(
                f"Successfully fetched {len(videos_with_transcripts)} transcripts"
            )

            # 3단계: 관련성 분석 및 랭킹
            logger.info("Step 3: Analyzing relevance...")
            ranked_videos = await self._analyze_and_rank_videos(
                query=query,
                videos=videos_with_transcripts,
                session_id=session_id,
                user_id=user_id,
                detected_language=detected_language
            )

            # 상위 N개 선택
            top_videos = ranked_videos[:max_videos]

            # 4단계: 선택된 비디오 요약 생성
            logger.info("Step 4: Generating summaries...")
            final_results = await self._generate_summaries(
                query=query,
                videos=top_videos,
                session_id=session_id,
                user_id=user_id,
                detected_language=detected_language
            )

            logger.info(f"YouTubeSearchAgent completed with {len(final_results)} results")

            return self.format_output(
                final_results,
                {
                    "search_type": "video",
                    "query": query,
                    "total_videos_analyzed": len(search_results),
                    "videos_with_transcripts": len(videos_with_transcripts),
                    "top_recommendations": len(final_results)
                }
            )

        except Exception as e:
            logger.error(f"YouTubeSearchAgent execution failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "agent": self.name
            }

    async def _initialize_tool(self):
        """YouTube 도구 초기화"""
        try:
            # MCPManager에서 YouTube 도구 가져오기
            youtube_tools = mcp_manager.get_available_tools(tool_type=None)
            self.youtube_tool = next(
                (tool for tool in youtube_tools if tool.name == "youtube_mcp"),
                None
            )

            if self.youtube_tool and self.youtube_tool.is_available:
                self.tool_available = True
                logger.info("YouTube tool initialized successfully")
            else:
                logger.warning("YouTube tool not found or not available")
                self.tool_available = False

        except Exception as e:
            logger.error(f"Failed to initialize YouTube tool: {e}")
            self.tool_available = False

    async def _search_videos(
        self,
        query: str,
        max_videos: int = 10
    ) -> List[Dict[str, Any]]:
        """YouTube에서 비디오 검색

        Args:
            query: 검색 쿼리
            max_videos: 최대 비디오 수

        Returns:
            비디오 목록
        """
        try:
            result = await mcp_manager.execute_tool(
                tool_name="youtube_mcp",
                params={
                    "operation": "search_videos",
                    "query": query,
                    "max_results": max_videos,
                    "order": "relevance"
                }
            )

            if result.success and result.data:
                return result.data.get("videos", [])
            else:
                logger.error(f"Video search failed: {result.error}")
                return []

        except Exception as e:
            logger.error(f"Error searching videos: {e}")
            return []

    async def _fetch_transcripts_parallel(
        self,
        videos: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """병렬로 여러 비디오의 트랜스크립트 가져오기

        Args:
            videos: 비디오 목록

        Returns:
            트랜스크립트가 포함된 비디오 목록
        """
        async def fetch_single_transcript(video: Dict[str, Any]) -> Dict[str, Any]:
            """단일 비디오 트랜스크립트 가져오기"""
            try:
                result = await mcp_manager.execute_tool(
                    tool_name="youtube_mcp",
                    params={
                        "operation": "get_transcript",
                        "video_id": video["video_id"],
                        "languages": settings.YOUTUBE_TRANSCRIPT_LANGUAGES
                    }
                )

                if result.success and result.data:
                    video["transcript"] = result.data
                    video["has_transcript"] = True
                else:
                    video["has_transcript"] = False
                    video["transcript_error"] = result.error
                    logger.debug(
                        f"No transcript for {video['video_id']}: {result.error}"
                    )

            except Exception as e:
                video["has_transcript"] = False
                video["transcript_error"] = str(e)
                logger.debug(f"Error fetching transcript for {video['video_id']}: {e}")

            return video

        # 병렬 실행
        tasks = [fetch_single_transcript(video) for video in videos]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 성공한 결과만 필터링
        videos_with_transcripts = [
            result for result in results
            if not isinstance(result, Exception) and result.get("has_transcript", False)
        ]

        return videos_with_transcripts

    async def _analyze_and_rank_videos(
        self,
        query: str,
        videos: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        detected_language: str = "ko"
    ) -> List[Dict[str, Any]]:
        """비디오 관련성 분석 및 랭킹

        USER CONTRIBUTION POINT: 여기서 relevance scoring 로직을 구현합니다.

        Args:
            query: 검색 쿼리
            videos: 트랜스크립트가 포함된 비디오 목록
            session_id: 세션 ID
            user_id: 사용자 ID
            detected_language: 감지된 언어

        Returns:
            관련성 점수로 정렬된 비디오 목록
        """
        # TODO: USER CONTRIBUTION - Implement relevance scoring logic
        # 여러 신호를 조합하여 관련성 점수를 계산하세요:
        # - 트랜스크립트에서 키워드 매칭
        # - 의미론적 유사도 (LLM 임베딩 사용)
        # - 메타데이터 신호 (제목/설명 매칭)
        # - 품질 신호 (조회수, 좋아요, 최신성)
        #
        # Trade-offs to consider:
        # - Precision vs. Recall: 정확도를 높일지, 더 많은 결과를 포함할지
        # - Recency vs. Popularity: 최신 영상 vs. 인기 영상
        # - Transcript quality: 자동 생성 자막의 가중치를 어떻게 할지

        # 기본 구현: LLM을 사용한 관련성 분석
        scored_videos = []

        for video in videos:
            try:
                # 관련성 점수 계산
                relevance_score = await self._calculate_relevance_score(
                    query=query,
                    video=video,
                    session_id=session_id,
                    user_id=user_id,
                    detected_language=detected_language
                )

                video["relevance_score"] = relevance_score
                scored_videos.append(video)

            except Exception as e:
                logger.error(f"Error scoring video {video['video_id']}: {e}")
                video["relevance_score"] = 0.0
                scored_videos.append(video)

        # 관련성 점수로 정렬
        ranked_videos = sorted(
            scored_videos,
            key=lambda v: v.get("relevance_score", 0.0),
            reverse=True
        )

        # 최소 임계값 필터링
        filtered_videos = [
            video for video in ranked_videos
            if video.get("relevance_score", 0.0) >= settings.YOUTUBE_MIN_RELEVANCE_SCORE
        ]

        return filtered_videos if filtered_videos else ranked_videos[:3]

    async def _calculate_relevance_score(
        self,
        query: str,
        video: Dict[str, Any],
        session_id: str,
        user_id: str,
        detected_language: str = "ko"
    ) -> float:
        """단일 비디오의 관련성 점수 계산

        USER CONTRIBUTION POINT: 여기서 점수 계산 로직을 커스터마이즈할 수 있습니다.

        Args:
            query: 검색 쿼리
            video: 비디오 데이터 (메타데이터 + 트랜스크립트)
            session_id: 세션 ID
            user_id: 사용자 ID
            detected_language: 감지된 언어

        Returns:
            관련성 점수 (0.0 ~ 1.0)
        """
        # TODO: USER CONTRIBUTION - Customize relevance scoring
        # 현재 구현: LLM을 사용한 의미론적 유사도 평가
        #
        # 다른 접근 방식을 고려할 수 있습니다:
        # 1. 키워드 기반: TF-IDF, BM25
        # 2. 임베딩 기반: 코사인 유사도
        # 3. 하이브리드: 여러 신호 조합
        #
        # 가중치 조정:
        # - transcript_match: 0.4
        # - metadata_match: 0.3
        # - quality_signals: 0.3

        try:
            transcript_text = video.get("transcript", {}).get("full_text", "")
            title = video.get("title", "")
            description = video.get("description", "")

            # LLM을 사용하여 관련성 평가
            llm = create_tracked_llm(
                session_id=session_id,
                user_id=user_id,
                task_type="youtube_relevance_analysis"
            )

            prompt = f"""Analyze the relevance of this YouTube video to the user's query.

Query: {query}

Video Information:
- Title: {title}
- Description: {description[:500]}
- Transcript Preview: {transcript_text[:1000]}

Evaluate how well this video answers the query on a scale of 0.0 to 1.0.
Consider:
1. Content relevance: Does the transcript directly address the query?
2. Title/description match: Do they indicate relevant content?
3. Depth: Does it provide comprehensive information?

Respond with ONLY a number between 0.0 and 1.0, no explanation.
"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            score_text = response.content.strip()

            # 숫자 추출
            try:
                score = float(score_text)
                return max(0.0, min(1.0, score))  # 0.0 ~ 1.0 범위로 제한
            except ValueError:
                logger.warning(f"Failed to parse relevance score: {score_text}")
                return 0.5  # 기본값

        except Exception as e:
            logger.error(f"Error calculating relevance score: {e}")
            return 0.5  # 기본값

    async def _generate_summaries(
        self,
        query: str,
        videos: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        detected_language: str = "ko"
    ) -> List[SearchResult]:
        """선택된 비디오의 요약 생성

        USER CONTRIBUTION POINT: 여기서 요약 전략을 구현합니다.

        Args:
            query: 검색 쿼리
            videos: 요약할 비디오 목록
            session_id: 세션 ID
            user_id: 사용자 ID
            detected_language: 감지된 언어

        Returns:
            SearchResult 목록
        """
        # TODO: USER CONTRIBUTION - Implement summarization strategy
        # 요약 전략 옵션:
        # - 간결한 요약 (2-3 문장)
        # - 상세한 요약 (단락 형식)
        # - 구조화된 요약 (키 포인트 리스트)
        # - 타임스탬프 포함 요약
        #
        # Trade-offs:
        # - Brevity vs. Detail: 간결함 vs. 상세함
        # - Technical depth: 기술적 깊이 수준
        # - User experience: 읽기 쉬움 vs. 정보 밀도

        results = []

        for i, video in enumerate(videos):
            try:
                # 비디오 요약 생성
                summary = await self._generate_single_summary(
                    query=query,
                    video=video,
                    rank=i + 1,
                    session_id=session_id,
                    user_id=user_id,
                    detected_language=detected_language
                )

                # SearchResult 생성
                search_result = SearchResult(
                    title=video.get("title", ""),
                    content=summary,
                    url=video.get("url", ""),
                    source=f"YouTube - {video.get('channel_title', 'Unknown')}",
                    relevance_score=video.get("relevance_score", 0.0),
                    timestamp=video.get("published_at", ""),
                    metadata={
                        "video_id": video.get("video_id"),
                        "duration": video.get("duration_formatted"),
                        "view_count": video.get("view_count"),
                        "like_count": video.get("like_count"),
                        "channel": video.get("channel_title"),
                        "thumbnail": video.get("thumbnail_url"),
                        "has_transcript": video.get("has_transcript", False),
                        "transcript_language": video.get("transcript", {}).get("language"),
                    }
                )

                results.append(search_result)

            except Exception as e:
                logger.error(f"Error generating summary for video {video.get('video_id')}: {e}")
                continue

        return results

    async def _generate_single_summary(
        self,
        query: str,
        video: Dict[str, Any],
        rank: int,
        session_id: str,
        user_id: str,
        detected_language: str = "ko"
    ) -> str:
        """단일 비디오 요약 생성

        USER CONTRIBUTION POINT: 요약 스타일을 커스터마이즈할 수 있습니다.

        Args:
            query: 검색 쿼리
            video: 비디오 데이터
            rank: 순위
            session_id: 세션 ID
            user_id: 사용자 ID
            detected_language: 감지된 언어

        Returns:
            비디오 요약 텍스트
        """
        # TODO: USER CONTRIBUTION - Customize summary style
        # 현재 구현: 쿼리 관련 내용 중심의 중간 길이 요약
        #
        # 커스터마이즈 옵션:
        # - Summary length: 짧게 (2-3문장) vs. 길게 (여러 단락)
        # - Focus: 쿼리 관련 부분만 vs. 전체 내용
        # - Style: 객관적 vs. 추천 톤
        # - Timestamps: 포함 여부

        try:
            transcript_text = video.get("transcript", {}).get("full_text", "")
            title = video.get("title", "")
            duration = video.get("duration_formatted", "")

            llm = create_tracked_llm(
                session_id=session_id,
                user_id=user_id,
                task_type="youtube_summary_generation"
            )

            language_instruction = "in Korean" if detected_language == "ko" else "in English"

            prompt = f"""Summarize this YouTube video {language_instruction}, focusing on how it answers the user's query.

Query: {query}

Video: {title}
Duration: {duration}

Transcript:
{transcript_text[:3000]}

Provide a 3-4 sentence summary that:
1. Explains what the video covers
2. Highlights the most relevant parts for the query
3. Mentions any unique insights or perspectives

Keep it concise and actionable for someone deciding whether to watch."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            summary = response.content.strip()

            return summary

        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            # Fallback: 기본 요약
            return (
                f"이 비디오는 '{video.get('title', '')}'에 대해 다룹니다. "
                f"({video.get('duration_formatted', '')})"
            )

    async def compare_videos(
        self,
        video_ids: List[str],
        comparison_context: str,
        session_id: str = "",
        user_id: str = "",
        detected_language: str = "ko",
        config: Optional[ComparisonConfig] = None
    ) -> Dict[str, Any]:
        """여러 비디오를 비교 분석

        USER CONTRIBUTION POINT: 비교 분석 로직을 커스터마이즈할 수 있습니다.

        Args:
            video_ids: 비교할 비디오 ID 목록 (2-5개)
            comparison_context: 비교 컨텍스트 (예: "Python tutorial comparison")
            session_id: 세션 ID
            user_id: 사용자 ID
            detected_language: 감지된 언어
            config: 비교 설정 (None이면 기본 설정 사용)

        Returns:
            비교 분석 결과
        """
        # 기본 설정 사용
        if config is None:
            config = ComparisonConfig()
        logger.info(f"Comparing {len(video_ids)} videos...")

        try:
            # 도구 초기화
            if not self.tool_available:
                await self._initialize_tool()

            if not self.tool_available:
                return {
                    "success": False,
                    "error": "YouTube tool not available"
                }

            # 비디오 데이터 수집
            result = await mcp_manager.execute_tool(
                tool_name="youtube_mcp",
                params={
                    "operation": "compare_videos",
                    "video_ids": video_ids,
                    "include_transcripts": True,
                }
            )

            if not result.success:
                return {
                    "success": False,
                    "error": result.error
                }

            videos = result.data.get("videos", [])

            # LLM을 사용하여 비교 분석 수행
            llm = create_tracked_llm(
                session_id=session_id,
                user_id=user_id,
                task_type="youtube_video_comparison"
            )

            # 비디오 정보 요약
            video_summaries = []
            for i, video in enumerate(videos):
                metadata = video.get("metadata", {})
                transcript = video.get("transcript", {})

                summary = f"""Video {i+1}: {metadata.get('title', 'Unknown')}
- Channel: {metadata.get('channel_title', 'Unknown')}
- Duration: {metadata.get('duration_formatted', 'Unknown')}
- Views: {metadata.get('view_count', 0):,}
- Transcript: {transcript.get('text_length', 0)} characters
"""
                if transcript.get("full_text"):
                    summary += f"- Content Preview: {transcript['full_text'][:500]}...\n"

                video_summaries.append(summary)

            language_instruction = "in Korean" if detected_language == "ko" else "in English"
            config_instructions = config.to_prompt_instructions()

            prompt = f"""Compare these YouTube videos {language_instruction} based on the context: {comparison_context}

{chr(10).join(video_summaries)}

Provide a comprehensive comparison that includes:
1. **Overview**: What each video covers
2. **Unique Strengths**: What makes each video valuable
3. **Target Audience**: Who should watch each video
4. **Depth & Quality**: Technical depth and production quality
5. **Recommendation**: Which video(s) to watch first and why

Additional instructions: {config_instructions}

Format your response in clear sections with headers."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            comparison_analysis = response.content.strip()

            return {
                "success": True,
                "comparison_context": comparison_context,
                "videos": videos,
                "analysis": comparison_analysis,
                "video_count": len(videos),
            }

        except Exception as e:
            logger.error(f"Error comparing videos: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    async def analyze_playlist(
        self,
        playlist_id: str,
        session_id: str = "",
        user_id: str = "",
        detected_language: str = "ko",
        config: Optional[PlaylistAnalysisConfig] = None
    ) -> Dict[str, Any]:
        """플레이리스트 분석 및 학습 경로 생성

        USER CONTRIBUTION POINT: 플레이리스트 분석 전략을 커스터마이즈할 수 있습니다.

        Args:
            playlist_id: 플레이리스트 ID
            session_id: 세션 ID
            user_id: 사용자 ID
            detected_language: 감지된 언어
            config: 플레이리스트 분석 설정 (None이면 기본 설정 사용)

        Returns:
            플레이리스트 분석 결과
        """
        # 기본 설정 사용
        if config is None:
            config = PlaylistAnalysisConfig()
        logger.info(f"Analyzing playlist: {playlist_id}")

        try:
            # 도구 초기화
            if not self.tool_available:
                await self._initialize_tool()

            if not self.tool_available:
                return {
                    "success": False,
                    "error": "YouTube tool not available"
                }

            # 플레이리스트 정보 가져오기
            playlist_info_result = await mcp_manager.execute_tool(
                tool_name="youtube_mcp",
                params={
                    "operation": "get_playlist_info",
                    "playlist_id": playlist_id,
                }
            )

            if not playlist_info_result.success:
                return {
                    "success": False,
                    "error": f"Failed to get playlist info: {playlist_info_result.error}"
                }

            playlist_info = playlist_info_result.data

            # 플레이리스트 비디오 가져오기
            videos_result = await mcp_manager.execute_tool(
                tool_name="youtube_mcp",
                params={
                    "operation": "get_playlist_videos",
                    "playlist_id": playlist_id,
                    "max_results": 20,  # 처음 20개 비디오 분석
                }
            )

            if not videos_result.success:
                return {
                    "success": False,
                    "error": f"Failed to get playlist videos: {videos_result.error}"
                }

            videos = videos_result.data.get("videos", [])

            # 중복 감지 (설정된 경우)
            duplicate_info = None
            if config.detect_duplicates:
                if config.use_semantic_similarity:
                    # 임베딩 기반 의미론적 중복 감지 (비동기)
                    duplicate_info = await self._detect_duplicate_videos_semantic(
                        videos,
                        threshold=config.semantic_similarity_threshold
                    )
                else:
                    # 빠른 제목 기반 중복 감지
                    duplicate_info = self._detect_duplicate_videos(videos)

                logger.info(
                    f"Duplicate detection: {duplicate_info['duplicate_count']} exact, "
                    f"{duplicate_info['similar_count']} similar"
                    + (f", {duplicate_info.get('semantic_count', 0)} semantic" if config.use_semantic_similarity else "")
                )

            # 최적 순서 계산 (설정된 경우)
            ordered_videos = videos
            if config.suggest_order != PlaylistOrderStrategy.ORIGINAL:
                if config.suggest_order in (PlaylistOrderStrategy.TOPIC_CLUSTERED, PlaylistOrderStrategy.PREREQUISITE_CHAIN):
                    # 토픽/선수학습 기반 정렬은 LLM 분석 필요
                    ordered_videos = await self._calculate_advanced_order(
                        videos,
                        config.suggest_order,
                        session_id,
                        user_id
                    )
                else:
                    ordered_videos = self._calculate_optimal_order(videos, config.suggest_order)
                logger.info(f"Reordered videos using strategy: {config.suggest_order.value}")
            else:
                ordered_videos = videos.copy()

            # LLM을 사용하여 플레이리스트 분석
            llm = create_tracked_llm(
                session_id=session_id,
                user_id=user_id,
                task_type="youtube_playlist_analysis"
            )

            # 분석할 비디오 제한
            videos_to_analyze = ordered_videos[:config.max_videos_to_analyze]

            # 비디오 목록 요약
            video_list = []
            total_duration = 0

            for i, video in enumerate(videos_to_analyze):
                order_indicator = ""
                if config.suggest_order != PlaylistOrderStrategy.ORIGINAL and "original_index" in video:
                    order_indicator = f" [원본: #{video['original_index'] + 1}]"

                video_list.append(
                    f"{i+1}. {video['title']} ({video['duration_formatted']}) - {video['view_count']:,} views{order_indicator}"
                )
                total_duration += video.get("duration_seconds", 0)

            language_instruction = "in Korean" if detected_language == "ko" else "in English"
            config_instructions = config.to_prompt_instructions()

            # 중복 정보 추가
            duplicate_note = ""
            if duplicate_info and (duplicate_info['duplicate_count'] > 0 or duplicate_info['similar_count'] > 0):
                duplicate_note = f"\n\n**Note**: Detected {duplicate_info['duplicate_count']} exact duplicates and {duplicate_info['similar_count']} similar videos."

            prompt = f"""Analyze this YouTube playlist {language_instruction} and create a learning path recommendation.

**Playlist**: {playlist_info['title']}
**Channel**: {playlist_info['channel_title']}
**Total Videos**: {playlist_info['video_count']}
**Total Duration**: {self._format_duration_from_seconds(total_duration)} (first {len(videos_to_analyze)} videos){duplicate_note}

**Videos** (viewing order: {config.suggest_order.value}):
{chr(10).join(video_list)}

Provide a comprehensive analysis:
1. **Overview**: What this playlist teaches
2. **Structure**: How the content is organized
3. **Learning Path**: Recommended order and approach
4. **Key Videos**: Must-watch videos and why
5. **Time Commitment**: Estimated learning time
6. **Prerequisites**: What viewers should know beforehand
7. **Gaps**: Any missing topics or areas for additional study

Additional instructions: {config_instructions}

Format your response with clear sections."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            analysis = response.content.strip()

            result = {
                "success": True,
                "playlist_info": playlist_info,
                "videos": videos,  # 원본 순서
                "video_count": len(videos),
                "total_duration_seconds": total_duration,
                "total_duration_formatted": self._format_duration_from_seconds(total_duration),
                "analysis": analysis,
            }

            # 중복 정보 추가
            if duplicate_info:
                result["duplicates"] = duplicate_info

            # 최적 순서 정보 추가
            if config.suggest_order != PlaylistOrderStrategy.ORIGINAL:
                result["suggested_order"] = ordered_videos
                result["order_strategy"] = config.suggest_order.value

            return result

        except Exception as e:
            logger.error(f"Error analyzing playlist: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def _detect_duplicate_videos(
        self,
        videos: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """플레이리스트에서 중복 또는 매우 유사한 비디오 감지

        Args:
            videos: 비디오 목록

        Returns:
            중복 감지 결과
        """
        duplicates = []
        similar_groups = []

        # 제목 기반 중복 감지 (정확히 같은 제목)
        title_map = {}
        for i, video in enumerate(videos):
            title = video.get("title", "").lower().strip()
            if title in title_map:
                duplicates.append({
                    "video1_index": title_map[title],
                    "video2_index": i,
                    "video1_title": videos[title_map[title]]["title"],
                    "video2_title": video["title"],
                    "reason": "Identical title"
                })
            else:
                title_map[title] = i

        # 유사한 제목 감지 (간단한 토큰 기반)
        for i in range(len(videos)):
            for j in range(i + 1, len(videos)):
                title1_tokens = set(videos[i].get("title", "").lower().split())
                title2_tokens = set(videos[j].get("title", "").lower().split())

                # 공통 토큰이 70% 이상이면 유사한 것으로 간주
                if len(title1_tokens) > 0 and len(title2_tokens) > 0:
                    common_tokens = title1_tokens & title2_tokens
                    similarity = len(common_tokens) / max(len(title1_tokens), len(title2_tokens))

                    if similarity > 0.7 and (i, j) not in [(d["video1_index"], d["video2_index"]) for d in duplicates]:
                        similar_groups.append({
                            "video1_index": i,
                            "video2_index": j,
                            "video1_title": videos[i]["title"],
                            "video2_title": videos[j]["title"],
                            "similarity_score": round(similarity, 2)
                        })

        return {
            "exact_duplicates": duplicates,
            "similar_videos": similar_groups,
            "duplicate_count": len(duplicates),
            "similar_count": len(similar_groups)
        }

    async def _detect_duplicate_videos_semantic(
        self,
        videos: List[Dict[str, Any]],
        threshold: float = 0.85
    ) -> Dict[str, Any]:
        """임베딩을 사용한 의미론적 중복 비디오 감지

        제목뿐만 아니라 개념적으로 유사한 비디오를 찾습니다.

        Args:
            videos: 비디오 목록
            threshold: 유사도 임계값 (0.0-1.0)

        Returns:
            중복 감지 결과 (기본 + 의미론적 중복)
        """
        # 먼저 기본 중복 감지 수행
        base_result = self._detect_duplicate_videos(videos)

        # 임베딩 모델 초기화
        try:
            embeddings = OpenAIEmbeddings(
                model=settings.EMBEDDING_MODEL,
                openai_api_key=settings.OPENAI_API_KEY
            )
        except Exception as e:
            logger.warning(f"Failed to initialize embeddings, skipping semantic detection: {e}")
            return base_result

        # 비디오 텍스트 준비 (제목 + 설명 일부)
        video_texts = []
        for video in videos:
            title = video.get("title", "")
            description = video.get("description", "")[:200]  # 설명의 처음 200자
            video_texts.append(f"{title}. {description}")

        try:
            # 임베딩 생성
            logger.info(f"Generating embeddings for {len(video_texts)} videos...")
            video_embeddings = await asyncio.to_thread(
                embeddings.embed_documents, video_texts
            )

            # 코사인 유사도 계산
            semantic_duplicates = []
            already_found = set()

            # 이미 찾은 중복/유사 쌍 추가
            for dup in base_result["exact_duplicates"]:
                already_found.add((dup["video1_index"], dup["video2_index"]))
            for sim in base_result["similar_videos"]:
                already_found.add((sim["video1_index"], sim["video2_index"]))

            for i in range(len(videos)):
                for j in range(i + 1, len(videos)):
                    if (i, j) in already_found:
                        continue

                    # 코사인 유사도 계산
                    similarity = self._cosine_similarity(
                        video_embeddings[i],
                        video_embeddings[j]
                    )

                    if similarity >= threshold:
                        semantic_duplicates.append({
                            "video1_index": i,
                            "video2_index": j,
                            "video1_title": videos[i]["title"],
                            "video2_title": videos[j]["title"],
                            "semantic_similarity": round(similarity, 3),
                            "detection_type": "semantic"
                        })

            # 결과 병합
            base_result["semantic_duplicates"] = semantic_duplicates
            base_result["semantic_count"] = len(semantic_duplicates)

            logger.info(f"Semantic detection found {len(semantic_duplicates)} additional similar videos")

            return base_result

        except Exception as e:
            logger.error(f"Error in semantic duplicate detection: {e}")
            return base_result

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """두 벡터의 코사인 유사도 계산

        Args:
            vec1: 첫 번째 벡터
            vec2: 두 번째 벡터

        Returns:
            코사인 유사도 (0.0-1.0)
        """
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    async def _calculate_advanced_order(
        self,
        videos: List[Dict[str, Any]],
        strategy: PlaylistOrderStrategy,
        session_id: str,
        user_id: str
    ) -> List[Dict[str, Any]]:
        """LLM 기반 고급 정렬 (토픽 클러스터링, 선수학습 체인)

        USER CONTRIBUTION POINT: 고급 정렬 로직을 커스터마이즈할 수 있습니다.

        Args:
            videos: 비디오 목록
            strategy: 정렬 전략
            session_id: 세션 ID
            user_id: 사용자 ID

        Returns:
            정렬된 비디오 목록
        """
        if len(videos) <= 2:
            # 2개 이하면 그냥 반환
            return videos.copy()

        # LLM을 사용하여 분석
        llm = create_tracked_llm(
            session_id=session_id,
            user_id=user_id,
            task_type="youtube_playlist_ordering"
        )

        # 비디오 목록 준비
        video_list = []
        for i, video in enumerate(videos[:20]):  # 최대 20개만 분석
            video_list.append(f"{i}. {video['title']} ({video.get('duration_formatted', 'unknown')})")

        video_list_str = "\n".join(video_list)

        if strategy == PlaylistOrderStrategy.TOPIC_CLUSTERED:
            prompt = f"""Analyze these YouTube videos and group them by topic/theme.

Videos:
{video_list_str}

Return the optimal viewing order where videos about the same topic are grouped together.
Format: Return ONLY a comma-separated list of video indices in the recommended order.
Example: 0,3,5,1,2,4

Consider:
1. Group related topics together
2. Within each group, order from overview to detail
3. Put foundational topics before advanced ones

Return ONLY the comma-separated indices, nothing else."""

        elif strategy == PlaylistOrderStrategy.PREREQUISITE_CHAIN:
            prompt = f"""Analyze these YouTube videos and determine the prerequisite learning order.

Videos:
{video_list_str}

Determine which videos should be watched before others based on:
1. Concept dependencies (basics before advanced)
2. Skill building (fundamentals before applications)
3. Knowledge prerequisites

Return ONLY a comma-separated list of video indices in the recommended order.
Example: 0,3,5,1,2,4

The first videos should be foundational, later ones should build on earlier concepts.
Return ONLY the comma-separated indices, nothing else."""

        else:
            return self._calculate_optimal_order(videos, strategy)

        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            order_str = response.content.strip()

            # 인덱스 파싱
            indices = []
            for part in order_str.split(","):
                try:
                    idx = int(part.strip())
                    if 0 <= idx < len(videos) and idx not in indices:
                        indices.append(idx)
                except ValueError:
                    continue

            # 누락된 인덱스 추가
            for i in range(len(videos)):
                if i not in indices:
                    indices.append(i)

            # 정렬된 비디오 목록 생성
            sorted_videos = []
            for new_order, original_idx in enumerate(indices):
                video = videos[original_idx].copy()
                video["original_index"] = original_idx
                video["suggested_order"] = new_order + 1
                sorted_videos.append(video)

            logger.info(f"Advanced ordering with {strategy.value}: generated order for {len(sorted_videos)} videos")
            return sorted_videos

        except Exception as e:
            logger.error(f"Error in advanced ordering: {e}")
            # 폴백: 기본 정렬
            return self._calculate_optimal_order(videos, PlaylistOrderStrategy.OPTIMAL_LEARNING)

    def _calculate_optimal_order(
        self,
        videos: List[Dict[str, Any]],
        strategy: PlaylistOrderStrategy
    ) -> List[Dict[str, Any]]:
        """비디오의 최적 시청 순서 계산

        USER CONTRIBUTION POINT: 정렬 로직을 커스터마이즈할 수 있습니다.

        Args:
            videos: 비디오 목록
            strategy: 정렬 전략

        Returns:
            정렬된 비디오 목록 (원본은 수정하지 않음)
        """
        if strategy == PlaylistOrderStrategy.ORIGINAL:
            return videos.copy()

        sorted_videos = videos.copy()

        if strategy == PlaylistOrderStrategy.POPULARITY:
            # 조회수 기준 내림차순
            sorted_videos.sort(key=lambda v: v.get("view_count", 0), reverse=True)

        elif strategy == PlaylistOrderStrategy.DURATION:
            # 짧은 것부터
            sorted_videos.sort(key=lambda v: v.get("duration_seconds", 0))

        elif strategy == PlaylistOrderStrategy.DIFFICULTY:
            # 간단한 휴리스틱: 짧고 조회수 많은 것이 쉬운 것으로 가정
            # 실제로는 LLM이나 더 복잡한 로직 필요
            sorted_videos.sort(key=lambda v: (
                v.get("duration_seconds", 0),  # 짧은 것 먼저
                -v.get("view_count", 0)  # 인기있는 것 먼저
            ))

        elif strategy == PlaylistOrderStrategy.OPTIMAL_LEARNING:
            # 학습 최적화: 짧은 개요 → 중간 길이 → 심화
            # 1단계: 10분 이하 (개요)
            # 2단계: 10-30분 (기본)
            # 3단계: 30분 이상 (심화)
            def learning_order_key(video):
                duration = video.get("duration_seconds", 0)
                if duration < 600:  # < 10분
                    return (0, duration)
                elif duration < 1800:  # 10-30분
                    return (1, duration)
                else:  # > 30분
                    return (2, duration)

            sorted_videos.sort(key=learning_order_key)

        # 원본 인덱스 정보 추가
        for i, video in enumerate(sorted_videos):
            original_index = videos.index(video)
            video["original_index"] = original_index
            video["suggested_order"] = i + 1

        return sorted_videos

    def _format_duration_from_seconds(self, seconds: int) -> str:
        """초를 읽기 쉬운 형식으로 변환

        Args:
            seconds: 초

        Returns:
            포맷된 시간 문자열 (예: "2 hours 15 minutes")
        """
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60

        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

        return " ".join(parts) if parts else "0 minutes"

    async def search(self, query: str, **kwargs) -> Dict[str, Any]:
        """SearchAgent의 추상 메서드 구현

        Args:
            query: 검색 쿼리
            **kwargs: 추가 파라미터

        Returns:
            검색 결과
        """
        # execute()로 위임
        context = kwargs.get("context", {})
        return await self.execute(query, context)
