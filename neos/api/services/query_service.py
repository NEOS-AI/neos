"""Query service layer - handles business logic"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from neos.workflow.graph import multi_agent_workflow
from neos.database.connection import db_manager
from neos.database.models import User, QueryHistory
from neos.database.repositories.query_repository import QueryRepository
from neos.utils.cache import cache_manager
from neos.utils.embeddings import embedding_manager


class QueryService:
    """Service layer for query processing"""

    @staticmethod
    async def get_or_create_user(user_id: str) -> User:
        """사용자 조회 또는 생성"""
        async with await db_manager.get_session() as session:
            # 사용자 조회
            result = await session.execute(
                select(User).where(User.user_id == user_id)
            )
            user = result.scalar_one_or_none()

            if not user:
                # 새 사용자 생성
                user = User(user_id=user_id)
                session.add(user)
                try:
                    await session.commit()
                    await session.refresh(user)
                except IntegrityError:
                    await session.rollback()
                    # 동시성 문제로 이미 생성된 경우 재조회
                    result = await session.execute(
                        select(User).where(User.user_id == user_id)
                    )
                    user = result.scalar_one_or_none()

            return user

    @staticmethod
    async def save_query_history(
        user_id: str,
        session_id: str,
        original_query: str,
        query_embedding: List[float],
        query_intent: str,
        search_results: List[Any],
        execution_time_ms: int,
        quality_score: float,
        tools_used: List[str]
    ) -> int:
        """쿼리 히스토리 저장"""
        async with await db_manager.get_session() as session:
            query_history = QueryHistory(
                user_id=user_id,
                original_query=original_query,
                query_vector=query_embedding,
                query_intent=query_intent,
                search_results=search_results,
                response_quality_score=quality_score,
                execution_time_ms=execution_time_ms,
                tools_used=tools_used
            )

            session.add(query_history)
            await session.commit()
            await session.refresh(query_history)

            return query_history.id

    @staticmethod
    async def save_query_history_background(
        user_id: str,
        session_id: str,
        original_query: str,
        result: Dict[str, Any],
        execution_time_ms: int
    ):
        """백그라운드에서 쿼리 히스토리 저장"""
        try:
            # 임베딩 생성
            query_embedding = await embedding_manager.get_embedding(original_query)

            # 사용된 도구들 추출
            tools_used = []
            if "metadata" in result and "agent_types" in result["metadata"]:
                tools_used = result["metadata"]["agent_types"]

            # DB에 저장
            await QueryService.save_query_history(
                user_id=user_id,
                session_id=session_id,
                original_query=original_query,
                query_embedding=query_embedding,
                query_intent="unknown",  # 실제로는 워크플로우 결과에서 추출
                search_results=result.get("metadata", {}),
                execution_time_ms=execution_time_ms,
                quality_score=result.get("quality_score", 0.0),
                tools_used=tools_used
            )

        except Exception as e:
            print(f"Failed to save query history: {e}")

    @staticmethod
    async def process_query_workflow(
        user_id: str,
        session_id: str,
        query: str,
        bypass_cache: bool = False
    ) -> Dict[str, Any]:
        """워크플로우 실행"""
        # 캐시 키 생성
        cache_key = cache_manager.make_key("query_cache", user_id, query)

        # 캐시에서 확인
        cached_response = await cache_manager.get(cache_key)
        if cached_response and not bypass_cache:
            return cached_response

        # 워크플로우 실행
        workflow_input = {
            "user_id": user_id,
            "session_id": session_id,
            "query": query
        }

        start_time = datetime.now()
        result = await multi_agent_workflow.execute_workflow(workflow_input)
        end_time = datetime.now()

        execution_time = int((end_time - start_time).total_seconds() * 1000)

        if not result["success"]:
            raise Exception(result.get("error", "Unknown error"))

        response_data = {
            "success": True,
            "response": result["response"],
            "session_id": session_id,
            "metadata": result["metadata"],
            "execution_time_ms": result["execution_time_ms"],
            "quality_score": result["quality_score"],
            "errors": result["errors"]
        }

        # 성공한 응답 캐싱 (1시간)
        if result["quality_score"] > 0.7:
            await cache_manager.set(cache_key, response_data, ttl=3600)

        return response_data

    @staticmethod
    async def check_system_health() -> Dict[str, Any]:
        """시스템 헬스 체크"""
        # 각 서비스 상태 확인
        db_healthy = await db_manager.health_check()
        cache_healthy = await cache_manager.health_check()

        # OpenAI API 간단 체크
        try:
            await embedding_manager.get_embedding("test", use_cache=False)
            openai_healthy = True
        except Exception as e:
            openai_healthy = False
            print(f"OpenAI API health check failed: {e}")

        services = {
            "database": db_healthy,
            "cache": cache_healthy,
            "openai": openai_healthy
        }

        overall_status = "healthy" if all(services.values()) else "degraded"

        return {
            "status": overall_status,
            "timestamp": datetime.now().isoformat(),
            "services": services
        }

    @staticmethod
    async def get_trending_queries(time_period: str = "daily", limit: int = 10) -> List[Dict[str, Any]]:
        """인기 검색어 조회"""
        async with await db_manager.get_session() as session:
            from neos.database.models import TrendingQuery as TrendingQueryModel

            result = await session.execute(
                select(TrendingQueryModel)
                .where(TrendingQueryModel.time_period == time_period)
                .order_by(TrendingQueryModel.search_count.desc())
                .limit(limit)
            )

            trending_queries = result.scalars().all()

            return [
                {
                    "query_text": tq.query_text,
                    "search_count": tq.search_count,
                    "last_searched": tq.last_searched.isoformat(),
                    "category": tq.category
                }
                for tq in trending_queries
            ]

    @staticmethod
    async def get_related_queries(query_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """연관 검색어 조회"""
        async with await db_manager.get_session() as session:
            from neos.database.models import RelatedQuery as RelatedQueryModel

            # 연관 쿼리 조회
            result = await session.execute(
                select(RelatedQueryModel, QueryHistory)
                .join(QueryHistory, RelatedQueryModel.related_query_id == QueryHistory.id)
                .where(RelatedQueryModel.source_query_id == query_id)
                .order_by(RelatedQueryModel.similarity_score.desc())
                .limit(limit)
            )

            rows = result.all()

            return [
                {
                    "query_text": row.QueryHistory.original_query,
                    "similarity_score": row.RelatedQuery.similarity_score,
                    "relation_type": row.RelatedQuery.relation_type
                }
                for row in rows
            ]

    @staticmethod
    async def get_user_query_history(user_id: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """사용자 쿼리 히스토리 조회"""
        async with await db_manager.get_session() as session:
            result = await session.execute(
                select(QueryHistory)
                .where(QueryHistory.user_id == user_id)
                .order_by(QueryHistory.created_at.desc())
                .offset(offset)
                .limit(limit)
            )

            histories = result.scalars().all()

            return [
                {
                    "id": h.id,
                    "query": h.original_query,
                    "intent": h.query_intent,
                    "quality_score": h.response_quality_score,
                    "execution_time_ms": h.execution_time_ms,
                    "tools_used": h.tools_used,
                    "created_at": h.created_at.isoformat()
                }
                for h in histories
            ]

    @staticmethod
    async def get_system_stats() -> Dict[str, Any]:
        """시스템 통계"""
        async with await db_manager.get_session() as session:
            # 총 쿼리 수
            total_queries = await session.execute(
                select(QueryHistory.id).count()
            )
            total_count = total_queries.scalar()

            # 오늘의 쿼리 수
            today = datetime.now().date()
            today_queries = await session.execute(
                select(QueryHistory.id)
                .where(QueryHistory.created_at >= today)
                .count()
            )
            today_count = today_queries.scalar()

            # 평균 실행 시간
            avg_execution_time = await session.execute(
                select(QueryHistory.execution_time_ms).avg()
            )
            avg_time = avg_execution_time.scalar() or 0

            # 평균 품질 점수
            avg_quality = await session.execute(
                select(QueryHistory.response_quality_score).avg()
            )
            avg_quality_score = avg_quality.scalar() or 0

            return {
                "total_queries": total_count,
                "today_queries": today_count,
                "avg_execution_time_ms": round(avg_time, 2),
                "avg_quality_score": round(avg_quality_score, 3),
                "timestamp": datetime.now().isoformat()
            }

    @staticmethod
    async def get_hyper_research_report(report_uuid: str) -> Dict[str, Any]:
        """HyperDeepResearch 보고서 조회"""
        # report_id 구성
        report_id = f"hyper_report_{report_uuid}"

        # 보고서 메타데이터 조회
        report = await QueryRepository.get_hyper_research_report(report_id)

        if not report:
            return None

        # 섹션 데이터 조회
        sections = await QueryRepository.get_hyper_research_sections(report_id)

        # 마크다운 생성
        markdown_parts = []

        # 헤더
        markdown_parts.append(f"# {report.research_topic}\n")
        markdown_parts.append(f"**Status:** {report.research_status}\n")
        markdown_parts.append(f"**Created:** {report.created_at}\n")
        if report.completed_at:
            markdown_parts.append(f"**Completed:** {report.completed_at}\n")
        markdown_parts.append("\n---\n")

        # 통계
        markdown_parts.append("\n## 📊 Research Statistics\n")
        markdown_parts.append(f"- **Total Sections:** {report.total_sections}\n")
        markdown_parts.append(f"- **Total Sources:** {report.total_sources}\n")
        markdown_parts.append(f"- **Total Queries:** {report.total_queries}\n")
        if report.quality_score:
            markdown_parts.append(f"- **Quality Score:** {report.quality_score:.2f}\n")

        # 메타데이터에서 추가 정보
        if report.metadata:
            if 'unique_domains' in report.metadata:
                markdown_parts.append(f"- **Unique Domains:** {report.metadata['unique_domains']}\n")
            if 'multi_query_searches' in report.metadata:
                markdown_parts.append(f"- **Complex Searches:** {report.metadata['multi_query_searches']}\n")
            if 'analysis_iterations' in report.metadata:
                markdown_parts.append(f"- **Analysis Iterations:** {report.metadata['analysis_iterations']}\n")

        markdown_parts.append("\n---\n")

        # 섹션들
        for section in sections:
            markdown_parts.append(f"\n## {section.section_title}\n")

            if section.section_content:
                markdown_parts.append(f"\n{section.section_content}\n")

            if section.sources_count and section.sources_count > 0:
                markdown_parts.append(f"\n*Sources: {section.sources_count}*\n")

        markdown_content = "".join(markdown_parts)

        # 응답 메타데이터
        response_metadata = {
            "user_id": report.user_id,
            "session_id": report.session_id,
            "research_topic": report.research_topic,
            "research_status": report.research_status,
            "created_at": str(report.created_at),
            "completed_at": str(report.completed_at) if report.completed_at else None,
            "total_sections": report.total_sections,
            "total_sources": report.total_sources,
            "total_queries": report.total_queries,
            "quality_score": report.quality_score,
            "sections_count": len(sections),
            "custom_metadata": report.metadata
        }

        return {
            "success": True,
            "report_id": report_id,
            "markdown_content": markdown_content,
            "metadata": response_metadata
        }

    @staticmethod
    async def list_hyper_research_reports(
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """HyperDeepResearch 보고서 목록 조회"""
        # 보고서 목록 조회
        reports, total_count = await QueryRepository.list_hyper_research_reports(
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset
        )

        # 응답 데이터 구성
        report_summaries = []
        for report in reports:
            # UUID 추출 (hyper_report_{UUID} 형식)
            report_uuid = report.report_id.replace("hyper_report_", "")

            report_summaries.append({
                "report_id": report.report_id,
                "report_uuid": report_uuid,
                "research_topic": report.research_topic,
                "research_status": report.research_status,
                "created_at": str(report.created_at),
                "completed_at": str(report.completed_at) if report.completed_at else None,
                "total_sections": report.total_sections,
                "total_sources": report.total_sources,
                "total_queries": report.total_queries,
                "quality_score": report.quality_score
            })

        return {
            "success": True,
            "reports": report_summaries,
            "total_count": total_count
        }
