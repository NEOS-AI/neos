"""Research Continuation Processor (Phase 2.2)

"더 깊이 파고들어줘", "X에 대해 추가 조사해줘" 같은 후속 연구 요청을 처리합니다.
이전 세션의 accumulated_knowledge를 로드하여 이미 탐색한 주제를 건너뛰고
남은 질문에 집중합니다.
"""

import logging
from typing import Dict, Any, List, Optional

from neos.config.settings import settings
from ..state import AgentState

logger = logging.getLogger(__name__)


class ResearchContinuationProcessor:
    """후속 연구 세션 처리

    워크플로우 흐름:
    1. 이전 세션 ID로 accumulated_knowledge 로드
    2. 이미 탐색한 subtopic 식별
    3. 새 쿼리 기반으로 remaining_questions 생성
    4. 다운스트림 노드에 컨텍스트 주입
    """

    async def process(self, state: AgentState) -> Dict[str, Any]:
        """후속 연구 컨텍스트 로드 및 상태 업데이트"""
        session_id = state.get("research_session_id")
        user_id = state.get("user_id", "")
        query = state.get("original_query", "")

        logger.info(f"Research continuation: loading prior session {session_id}")

        # 1. 이전 세션 데이터 로드
        prior_knowledge = await self._load_prior_knowledge(user_id, session_id)

        if prior_knowledge:
            state["accumulated_knowledge"] = prior_knowledge
            state["explored_subtopics"] = prior_knowledge.get("explored_subtopics", [])

            # 2. 남은 질문 생성 (LLM 기반)
            remaining = await self._generate_remaining_questions(
                query, prior_knowledge
            )
            state["remaining_questions"] = remaining

            # 3. 대화 컨텍스트에 이전 연구 요약 추가
            prior_summary = prior_knowledge.get("summary", "")
            if prior_summary:
                existing_ctx = state.get("conversation_context") or ""
                state["conversation_context"] = (
                    f"이전 연구 요약:\n{prior_summary}\n\n{existing_ctx}"
                ).strip()

            logger.info(
                f"Continuation loaded: {len(state['explored_subtopics'])} subtopics explored, "
                f"{len(remaining)} remaining questions"
            )
        else:
            logger.info("No prior knowledge found, treating as new research")
            state["accumulated_knowledge"] = {}
            state["explored_subtopics"] = []
            state["remaining_questions"] = []

        return state

    async def _load_prior_knowledge(
        self, user_id: str, session_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """이전 세션의 축적된 지식 로드"""
        if not session_id:
            return None

        try:
            # Memory system에서 에피소드 메모리 로드
            from neos.memory.manager import memory_manager

            episodes = await memory_manager.episodic.retrieve(user_id, "", limit=5)

            # 해당 session_id의 에피소드 찾기
            for ep in episodes:
                if ep.key == session_id:
                    content = ep.content if isinstance(ep.content, dict) else {}
                    return {
                        "summary": content.get("key_findings", ""),
                        "explored_subtopics": content.get("explored_subtopics", []),
                        "sources_used": content.get("sources_used", []),
                        "quality_score": content.get("quality_score", 0.0),
                    }

            # session_id를 못 찾으면 DB에서 직접 조회
            from neos.api.services.research_session_service import research_session_service
            session = await research_session_service.get_session(session_id)
            if session:
                metadata = session.get("metadata", {}) if isinstance(session, dict) else {}
                return {
                    "summary": metadata.get("key_findings", session.get("original_query", "")),
                    "explored_subtopics": metadata.get("explored_subtopics", []),
                    "sources_used": [],
                    "quality_score": metadata.get("quality_score", 0.0),
                }

        except Exception as e:
            logger.warning(f"Failed to load prior knowledge: {e}")

        return None

    async def _generate_remaining_questions(
        self, query: str, prior_knowledge: Dict[str, Any]
    ) -> List[str]:
        """새 쿼리와 이전 지식 기반으로 남은 질문 생성"""
        explored = prior_knowledge.get("explored_subtopics", [])
        summary = prior_knowledge.get("summary", "")

        if not explored and not summary:
            return [query]

        try:
            from neos.utils.llm_factory import create_llm

            llm = create_llm(
                model=getattr(settings, "QUERY_CLASSIFIER_LLM_MODEL", "claude-haiku-4-5-20251001"),
                temperature=0.0,
                max_tokens=500,
                request_timeout=10,
            )

            prompt = f"""Given a follow-up research query and prior research context, identify 2-4 specific questions that haven't been answered yet.

Prior research summary:
{summary[:1000]}

Already explored topics: {', '.join(explored[:10])}

New follow-up query: {query}

Return ONLY a numbered list of remaining questions (2-4 items):"""

            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            # 번호 리스트 파싱
            questions = []
            for line in content.strip().split("\n"):
                line = line.strip()
                if line and (line[0].isdigit() or line.startswith("-")):
                    # "1. question" 또는 "- question" 형태 파싱
                    cleaned = line.lstrip("0123456789.-) ").strip()
                    if cleaned:
                        questions.append(cleaned)

            return questions[:4] if questions else [query]

        except Exception as e:
            logger.warning(f"Remaining questions generation failed: {e}")
            return [query]
