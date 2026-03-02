"""YouTube search and transcript analysis MCP tool implementation"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import asyncio
import logging
import re

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import isodate

from neos.config.settings import settings
from neos.tools.base import MCPTool, MCPToolResult, MCPToolType


logger = logging.getLogger(__name__)


class YouTubeMCPTool(MCPTool):
    """YouTube 검색 및 트랜스크립트 분석 MCP 도구

    YouTube Data API v3와 youtube-transcript-api를 사용하여
    비디오 검색, 트랜스크립트 추출, 콘텐츠 분석 기능을 제공합니다.

    Capabilities:
        - video_search: YouTube 비디오 검색
        - transcript_extraction: 비디오 트랜스크립트 추출
        - metadata_extraction: 비디오 메타데이터 추출
        - multi_language_support: 다국어 트랜스크립트 지원
    """

    def __init__(self):
        super().__init__(
            name="youtube_mcp",
            tool_type=MCPToolType.API_INTEGRATION,
            description="YouTube 비디오 검색 및 트랜스크립트 분석 도구",
            capabilities=[
                "video_search",
                "transcript_extraction",
                "metadata_extraction",
                "multi_language_support",
            ],
        )
        self.youtube_client = None
        self._disabled_reason: Optional[str] = None

    async def initialize(self) -> bool:
        """YouTube 클라이언트 초기화

        Returns:
            초기화 성공 여부
        """
        try:
            # YouTube API 키 확인 (선택사항 - 트랜스크립트만 사용 시 불필요)
            if settings.YOUTUBE_API_KEY:
                # YouTube Data API v3 클라이언트 초기화
                self.youtube_client = build(
                    "youtube",
                    "v3",
                    developerKey=settings.YOUTUBE_API_KEY,
                    cache_discovery=False,
                )
                logger.info("YouTube MCP tool initialized with API key")
            else:
                logger.warning(
                    "YOUTUBE_API_KEY not configured. "
                    "Video search will not be available, but transcript extraction will work."
                )

            self.is_available = True
            return True

        except Exception as e:
            logger.error(f"Failed to initialize YouTube MCP tool: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> MCPToolResult:
        """YouTube 도구 실행

        Args:
            params: 실행 파라미터
                - operation (str, required): 실행할 작업
                    - "search_videos": 비디오 검색
                    - "get_transcript": 트랜스크립트 가져오기
                    - "get_video_info": 비디오 메타데이터 가져오기
                    - "analyze_video": 비디오 전체 분석 (검색 + 트랜스크립트)
                    - "get_playlist_info": 플레이리스트 정보 가져오기
                    - "get_playlist_videos": 플레이리스트의 모든 비디오 가져오기
                    - "compare_videos": 여러 비디오 비교 분석

        Returns:
            MCPToolResult: 실행 결과
        """
        start_time = datetime.now()

        # 비활성화 상태 체크 (API 에러로 자동 비활성화된 경우)
        if self._disabled_reason:
            return MCPToolResult.from_error(
                error=f"YouTube tool disabled: {self._disabled_reason}",
                tool_name=self.name,
            )

        try:
            operation = params.get("operation", "")
            if not operation:
                return MCPToolResult.from_error(
                    error="Operation parameter is required",
                    tool_name=self.name,
                )

            # Operation dispatcher
            operations = {
                "search_videos": self._search_videos,
                "get_transcript": self._get_transcript,
                "get_video_info": self._get_video_info,
                "analyze_video": self._analyze_video,
                "get_playlist_info": self._get_playlist_info,
                "get_playlist_videos": self._get_playlist_videos,
                "compare_videos": self._compare_videos,
            }

            if operation not in operations:
                return MCPToolResult.from_error(
                    error=f"Unknown operation: {operation}. "
                    f"Available: {list(operations.keys())}",
                    tool_name=self.name,
                )

            # 작업 실행
            result = await operations[operation](params)

            execution_time = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )

            if isinstance(result, MCPToolResult):
                return result

            return MCPToolResult.from_success(
                data=result,
                tool_name=self.name,
                execution_time_ms=execution_time,
                metadata={"operation": operation},
            )

        except HttpError as e:
            execution_time = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )
            # API key 무효 또는 quota 초과 시 자동 비활성화
            if e.resp.status in (401, 403):
                self.is_available = False
                self._disabled_reason = (
                    "API key invalid" if e.resp.status == 401
                    else "API quota exceeded"
                )
                logger.error(
                    f"YouTube tool auto-disabled: {self._disabled_reason} "
                    f"(HTTP {e.resp.status})"
                )
            else:
                logger.error(f"YouTube API error: {e}", exc_info=True)
            return MCPToolResult.from_error(
                error=str(e),
                tool_name=self.name,
                execution_time_ms=execution_time,
            )

        except Exception as e:
            execution_time = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )
            logger.error(f"YouTube tool execution error: {e}", exc_info=True)
            return MCPToolResult.from_error(
                error=str(e),
                tool_name=self.name,
                execution_time_ms=execution_time,
            )

    async def _search_videos(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """YouTube 비디오 검색

        Args:
            params:
                - query (str, required): 검색 쿼리
                - max_results (int, optional): 최대 결과 수 (default: 10)
                - order (str, optional): 정렬 방법 (relevance/date/viewCount/rating)

        Returns:
            검색 결과 딕셔너리
        """
        if not self.youtube_client:
            raise ValueError(
                "YouTube API key not configured. Cannot perform video search."
            )

        query = params.get("query", "")
        if not query:
            raise ValueError("Query parameter is required for video search")

        max_results = params.get("max_results", settings.YOUTUBE_MAX_RESULTS)
        order = params.get("order", "relevance")

        # YouTube Data API v3 검색 실행
        search_response = await asyncio.to_thread(
            self.youtube_client.search().list(
                q=query,
                part="id,snippet",
                maxResults=max_results,
                order=order,
                type="video",
                relevanceLanguage="en",  # 언어 우선순위
            ).execute
        )

        # 비디오 ID 추출
        video_ids = [
            item["id"]["videoId"]
            for item in search_response.get("items", [])
            if item["id"]["kind"] == "youtube#video"
        ]

        if not video_ids:
            return {"videos": [], "total_results": 0}

        # 비디오 상세 정보 가져오기
        videos_response = await asyncio.to_thread(
            self.youtube_client.videos().list(
                part="snippet,contentDetails,statistics",
                id=",".join(video_ids),
            ).execute
        )

        # 결과 포맷팅
        videos = []
        for item in videos_response.get("items", []):
            video_id = item["id"]
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            content_details = item.get("contentDetails", {})

            # Duration 파싱
            duration_iso = content_details.get("duration", "PT0S")
            duration_seconds = int(isodate.parse_duration(duration_iso).total_seconds())

            videos.append({
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "channel_id": snippet.get("channelId", ""),
                "published_at": snippet.get("publishedAt", ""),
                "thumbnail_url": snippet.get("thumbnails", {})
                .get("high", {})
                .get("url", ""),
                "duration_seconds": duration_seconds,
                "duration_formatted": self._format_duration(duration_seconds),
                "view_count": int(statistics.get("viewCount", 0)),
                "like_count": int(statistics.get("likeCount", 0)),
                "comment_count": int(statistics.get("commentCount", 0)),
                "url": f"https://www.youtube.com/watch?v={video_id}",
            })

        return {
            "videos": videos,
            "total_results": len(videos),
            "query": query,
        }

    async def _get_transcript(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """YouTube 비디오 트랜스크립트 추출

        Args:
            params:
                - video_id (str, required): YouTube 비디오 ID
                - languages (List[str], optional): 선호 언어 목록

        Returns:
            트랜스크립트 데이터
        """
        video_id = params.get("video_id", "")
        if not video_id:
            # URL에서 video_id 추출 시도
            video_url = params.get("video_url", "")
            if video_url:
                video_id = self._extract_video_id(video_url)

        if not video_id:
            raise ValueError("video_id or video_url parameter is required")

        # 언어 설정
        languages = params.get("languages", settings.YOUTUBE_TRANSCRIPT_LANGUAGES)
        if isinstance(languages, str):
            languages = [lang.strip() for lang in languages.split(",")]

        try:
            # 트랜스크립트 목록 가져오기
            transcript_list = await asyncio.to_thread(
                YouTubeTranscriptApi.list_transcripts, video_id
            )

            # 수동 생성 트랜스크립트 우선 시도
            transcript = None
            selected_language = None
            is_auto_generated = False

            try:
                # 선호 언어로 수동 트랜스크립트 찾기
                for lang in languages:
                    try:
                        transcript = await asyncio.to_thread(
                            transcript_list.find_manually_created_transcript(lang).fetch
                        )
                        selected_language = lang
                        break
                    except:
                        continue

            except Exception as e:
                logger.debug(f"No manual transcript found: {e}")

            # 자동 생성 트랜스크립트 fallback
            if not transcript and settings.YOUTUBE_ENABLE_AUTO_CAPTIONS:
                try:
                    for lang in languages:
                        try:
                            transcript = await asyncio.to_thread(
                                transcript_list.find_generated_transcript(lang).fetch
                            )
                            selected_language = lang
                            is_auto_generated = True
                            break
                        except:
                            continue
                except Exception as e:
                    logger.debug(f"No auto-generated transcript found: {e}")

            # 어떤 언어라도 사용 가능한 트랜스크립트 찾기
            if not transcript:
                try:
                    available_transcripts = await asyncio.to_thread(
                        transcript_list.find_transcript, languages
                    )
                    transcript = await asyncio.to_thread(available_transcripts.fetch)
                    selected_language = available_transcripts.language_code
                    is_auto_generated = available_transcripts.is_generated
                except Exception as e:
                    raise ValueError(
                        f"No transcript available for video {video_id} "
                        f"in languages: {languages}. Error: {e}"
                    )

            # 트랜스크립트 텍스트 조합
            segments = []
            full_text_parts = []

            for entry in transcript:
                text = entry["text"]
                start = entry["start"]
                duration = entry.get("duration", 0)

                segments.append({
                    "start": start,
                    "duration": duration,
                    "text": text,
                })
                full_text_parts.append(text)

            full_text = " ".join(full_text_parts)

            # 최대 길이 제한
            if len(full_text) > settings.YOUTUBE_MAX_TRANSCRIPT_LENGTH:
                full_text = full_text[: settings.YOUTUBE_MAX_TRANSCRIPT_LENGTH] + "..."
                logger.warning(
                    f"Transcript truncated to {settings.YOUTUBE_MAX_TRANSCRIPT_LENGTH} characters"
                )

            return {
                "video_id": video_id,
                "language": selected_language,
                "is_auto_generated": is_auto_generated,
                "full_text": full_text,
                "segments": segments,
                "segment_count": len(segments),
                "text_length": len(full_text),
            }

        except TranscriptsDisabled:
            raise ValueError(f"Transcripts are disabled for video {video_id}")
        except NoTranscriptFound:
            raise ValueError(f"No transcript found for video {video_id}")
        except VideoUnavailable:
            raise ValueError(f"Video {video_id} is unavailable")
        except Exception as e:
            raise ValueError(f"Error fetching transcript: {str(e)}")

    async def _get_video_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """비디오 메타데이터 가져오기

        Args:
            params:
                - video_id (str, required): YouTube 비디오 ID

        Returns:
            비디오 메타데이터
        """
        if not self.youtube_client:
            raise ValueError(
                "YouTube API key not configured. Cannot get video info."
            )

        video_id = params.get("video_id", "")
        if not video_id:
            video_url = params.get("video_url", "")
            if video_url:
                video_id = self._extract_video_id(video_url)

        if not video_id:
            raise ValueError("video_id or video_url parameter is required")

        # 비디오 정보 가져오기
        response = await asyncio.to_thread(
            self.youtube_client.videos().list(
                part="snippet,contentDetails,statistics",
                id=video_id,
            ).execute
        )

        items = response.get("items", [])
        if not items:
            raise ValueError(f"Video not found: {video_id}")

        item = items[0]
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        content_details = item.get("contentDetails", {})

        # Duration 파싱
        duration_iso = content_details.get("duration", "PT0S")
        duration_seconds = int(isodate.parse_duration(duration_iso).total_seconds())

        return {
            "video_id": video_id,
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "channel_title": snippet.get("channelTitle", ""),
            "channel_id": snippet.get("channelId", ""),
            "published_at": snippet.get("publishedAt", ""),
            "thumbnail_url": snippet.get("thumbnails", {})
            .get("high", {})
            .get("url", ""),
            "duration_seconds": duration_seconds,
            "duration_formatted": self._format_duration(duration_seconds),
            "view_count": int(statistics.get("viewCount", 0)),
            "like_count": int(statistics.get("likeCount", 0)),
            "comment_count": int(statistics.get("commentCount", 0)),
            "tags": snippet.get("tags", []),
            "category_id": snippet.get("categoryId", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}",
        }

    async def _analyze_video(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """비디오 전체 분석 (메타데이터 + 트랜스크립트)

        Args:
            params:
                - video_id or video_url (str, required)
                - languages (List[str], optional)

        Returns:
            완전한 비디오 분석 결과
        """
        # 비디오 ID 추출
        video_id = params.get("video_id", "")
        if not video_id:
            video_url = params.get("video_url", "")
            if video_url:
                video_id = self._extract_video_id(video_url)

        if not video_id:
            raise ValueError("video_id or video_url parameter is required")

        # 병렬로 메타데이터와 트랜스크립트 가져오기
        results = {}

        # 메타데이터 가져오기 (API 키 있는 경우)
        if self.youtube_client:
            try:
                metadata = await self._get_video_info({"video_id": video_id})
                results["metadata"] = metadata
            except Exception as e:
                logger.error(f"Failed to get video metadata: {e}")
                results["metadata"] = None
                results["metadata_error"] = str(e)

        # 트랜스크립트 가져오기
        try:
            transcript = await self._get_transcript(params)
            results["transcript"] = transcript
        except Exception as e:
            logger.error(f"Failed to get transcript: {e}")
            results["transcript"] = None
            results["transcript_error"] = str(e)

        results["video_id"] = video_id
        results["analysis_complete"] = bool(
            results.get("metadata") or results.get("transcript")
        )

        return results

    def _extract_video_id(self, url: str) -> Optional[str]:
        """YouTube URL에서 비디오 ID 추출

        Args:
            url: YouTube URL

        Returns:
            비디오 ID 또는 None
        """
        # 다양한 YouTube URL 패턴 지원
        patterns = [
            r"(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)",
            r"youtube\.com\/embed\/([^&\n?#]+)",
            r"youtube\.com\/v\/([^&\n?#]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        # URL이 이미 비디오 ID인 경우
        if re.match(r"^[A-Za-z0-9_-]{11}$", url):
            return url

        return None

    def _format_duration(self, seconds: int) -> str:
        """초를 시:분:초 형식으로 변환

        Args:
            seconds: 초

        Returns:
            포맷된 시간 문자열
        """
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"

    def _extract_playlist_id(self, url: str) -> Optional[str]:
        """YouTube URL에서 플레이리스트 ID 추출

        Args:
            url: YouTube playlist URL

        Returns:
            플레이리스트 ID 또는 None
        """
        # 플레이리스트 URL 패턴
        patterns = [
            r"[?&]list=([^&\n?#]+)",
            r"youtube\.com/playlist\?list=([^&\n?#]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        # URL이 이미 플레이리스트 ID인 경우
        if re.match(r"^[A-Za-z0-9_-]+$", url) and len(url) > 11:
            return url

        return None

    async def _get_playlist_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """플레이리스트 정보 가져오기

        Args:
            params:
                - playlist_id (str, required): 플레이리스트 ID
                - playlist_url (str, optional): 플레이리스트 URL

        Returns:
            플레이리스트 메타데이터
        """
        if not self.youtube_client:
            raise ValueError(
                "YouTube API key not configured. Cannot get playlist info."
            )

        playlist_id = params.get("playlist_id", "")
        if not playlist_id:
            playlist_url = params.get("playlist_url", "")
            if playlist_url:
                playlist_id = self._extract_playlist_id(playlist_url)

        if not playlist_id:
            raise ValueError("playlist_id or playlist_url parameter is required")

        # 플레이리스트 정보 가져오기
        response = await asyncio.to_thread(
            self.youtube_client.playlists().list(
                part="snippet,contentDetails",
                id=playlist_id,
            ).execute
        )

        items = response.get("items", [])
        if not items:
            raise ValueError(f"Playlist not found: {playlist_id}")

        item = items[0]
        snippet = item.get("snippet", {})
        content_details = item.get("contentDetails", {})

        return {
            "playlist_id": playlist_id,
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "channel_title": snippet.get("channelTitle", ""),
            "channel_id": snippet.get("channelId", ""),
            "published_at": snippet.get("publishedAt", ""),
            "thumbnail_url": snippet.get("thumbnails", {})
            .get("high", {})
            .get("url", ""),
            "video_count": content_details.get("itemCount", 0),
            "url": f"https://www.youtube.com/playlist?list={playlist_id}",
        }

    async def _get_playlist_videos(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """플레이리스트의 모든 비디오 가져오기

        Args:
            params:
                - playlist_id (str, required): 플레이리스트 ID
                - max_results (int, optional): 최대 비디오 수 (default: 50)

        Returns:
            비디오 목록
        """
        if not self.youtube_client:
            raise ValueError(
                "YouTube API key not configured. Cannot get playlist videos."
            )

        playlist_id = params.get("playlist_id", "")
        if not playlist_id:
            playlist_url = params.get("playlist_url", "")
            if playlist_url:
                playlist_id = self._extract_playlist_id(playlist_url)

        if not playlist_id:
            raise ValueError("playlist_id or playlist_url parameter is required")

        max_results = params.get("max_results", 50)

        # 플레이리스트 아이템 가져오기 (페이지네이션 처리)
        all_video_ids = []
        next_page_token = None

        while len(all_video_ids) < max_results:
            request_params = {
                "part": "snippet,contentDetails",
                "playlistId": playlist_id,
                "maxResults": min(50, max_results - len(all_video_ids)),
            }

            if next_page_token:
                request_params["pageToken"] = next_page_token

            response = await asyncio.to_thread(
                self.youtube_client.playlistItems().list(**request_params).execute
            )

            items = response.get("items", [])
            for item in items:
                video_id = item.get("contentDetails", {}).get("videoId")
                if video_id:
                    all_video_ids.append(video_id)

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        # 비디오 상세 정보 가져오기 (배치 처리)
        videos = []
        batch_size = 50

        for i in range(0, len(all_video_ids), batch_size):
            batch_ids = all_video_ids[i : i + batch_size]

            videos_response = await asyncio.to_thread(
                self.youtube_client.videos().list(
                    part="snippet,contentDetails,statistics",
                    id=",".join(batch_ids),
                ).execute
            )

            for item in videos_response.get("items", []):
                video_id = item["id"]
                snippet = item.get("snippet", {})
                statistics = item.get("statistics", {})
                content_details = item.get("contentDetails", {})

                # Duration 파싱
                duration_iso = content_details.get("duration", "PT0S")
                duration_seconds = int(
                    isodate.parse_duration(duration_iso).total_seconds()
                )

                videos.append({
                    "video_id": video_id,
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "channel_title": snippet.get("channelTitle", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "thumbnail_url": snippet.get("thumbnails", {})
                    .get("high", {})
                    .get("url", ""),
                    "duration_seconds": duration_seconds,
                    "duration_formatted": self._format_duration(duration_seconds),
                    "view_count": int(statistics.get("viewCount", 0)),
                    "like_count": int(statistics.get("likeCount", 0)),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                })

        return {
            "playlist_id": playlist_id,
            "videos": videos,
            "total_videos": len(videos),
        }

    async def _compare_videos(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """여러 비디오 비교 분석 준비

        트랜스크립트와 메타데이터를 수집하여 비교 분석을 위한 데이터 제공

        Args:
            params:
                - video_ids (List[str], required): 비교할 비디오 ID 목록 (2-5개)
                - include_transcripts (bool, optional): 트랜스크립트 포함 여부 (default: True)

        Returns:
            비교 분석용 비디오 데이터
        """
        video_ids = params.get("video_ids", [])
        if not video_ids or len(video_ids) < 2:
            raise ValueError("At least 2 video IDs are required for comparison")

        if len(video_ids) > 5:
            raise ValueError("Maximum 5 videos can be compared at once")

        include_transcripts = params.get("include_transcripts", True)

        # 병렬로 비디오 분석 수행
        async def analyze_single_video(video_id: str) -> Dict[str, Any]:
            """단일 비디오 분석"""
            analysis_params = {
                "video_id": video_id,
                "languages": settings.YOUTUBE_TRANSCRIPT_LANGUAGES,
            }

            return await self._analyze_video(analysis_params)

        # 모든 비디오 병렬 분석
        tasks = [analyze_single_video(vid) for vid in video_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 결과 정리
        compared_videos = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error analyzing video {video_ids[i]}: {result}")
                compared_videos.append({
                    "video_id": video_ids[i],
                    "error": str(result),
                    "analysis_complete": False,
                })
            else:
                compared_videos.append(result)

        # 트랜스크립트 제외 옵션 처리
        if not include_transcripts:
            for video in compared_videos:
                if "transcript" in video:
                    # 트랜스크립트 메타데이터만 유지
                    transcript_meta = video["transcript"]
                    video["transcript"] = {
                        "language": transcript_meta.get("language"),
                        "is_auto_generated": transcript_meta.get("is_auto_generated"),
                        "segment_count": transcript_meta.get("segment_count"),
                        "text_length": transcript_meta.get("text_length"),
                    }

        return {
            "videos": compared_videos,
            "comparison_count": len(compared_videos),
            "successful_analyses": sum(
                1 for v in compared_videos if v.get("analysis_complete", False)
            ),
        }

    async def cleanup(self) -> None:
        """리소스 정리"""
        try:
            if self.youtube_client:
                # YouTube API 클라이언트는 명시적 cleanup 불필요
                self.youtube_client = None
                logger.info("YouTube MCP tool cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up YouTube MCP tool: {e}")
