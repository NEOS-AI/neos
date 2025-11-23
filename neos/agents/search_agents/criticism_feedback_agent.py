"""Criticism Feedback Sub-Agent - 중간 보고서 비판 및 피드백 에이전트"""

from typing import Dict, Any, List
from neos.utils.llm_factory import create_llm


class CriticismFeedbackAgent:
    """중간 보고서에 대한 비판적 피드백을 생성하는 서브 에이전트

    역할:
    - 생성된 중간 조사 결과의 논리적 타당성 검증
    - 누락된 관점이나 추가 조사가 필요한 영역 식별
    - 잠재적 편향이나 약점 지적
    - 더 깊은 조사를 유도하는 질문 생성
    - 필요시 방향 전환 제안
    """

    def __init__(self):
        self.name = "criticism_feedback"
        self.role = "Critical Reviewer & Research Quality Auditor"

    async def generate_feedback(
        self,
        topic: str,
        section_type: str,
        section_content: str,
        research_context: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str = "ko"
    ) -> Dict[str, Any]:
        """중간 보고서에 대한 비판적 피드백 생성

        Args:
            topic: 연구 주제
            section_type: 섹션 타입 (예: topic_analysis, methodology, etc.)
            section_content: 섹션 내용
            research_context: 연구 맥락 정보 (이전 분석, 수집된 소스 수 등)
            session_id: 세션 ID
            user_id: 사용자 ID
            language: 언어 설정

        Returns:
            피드백 결과 딕셔너리:
            {
                "has_issues": bool,  # 문제가 있는지 여부
                "severity": str,  # "critical", "moderate", "minor", "none"
                "feedback": str,  # 피드백 텍스트
                "suggested_queries": List[str],  # 추가 조사 쿼리
                "redirect_suggestion": str,  # 방향 전환 제안 (있는 경우)
                "missing_perspectives": List[str]  # 누락된 관점들
            }
        """
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            from langchain_core.messages import HumanMessage

            base_llm = create_llm(temperature=0.4, max_tokens=2500)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.name,
                tags=["criticism_feedback", section_type]
            )

            # 맥락 정보 정리
            sources_count = research_context.get("sources_count", 0)
            previous_sections = research_context.get("previous_sections", [])
            research_questions = research_context.get("research_questions", [])

            prompts = {
                "ko": f"""다음 연구 섹션을 비판적으로 검토하고 건설적인 피드백을 제공해주세요:

**연구 주제:** {topic}

**섹션 타입:** {section_type}

**섹션 내용:**
{section_content[:2000]}

**연구 맥락:**
- 수집된 소스 수: {sources_count}
- 원래 연구 질문: {', '.join(research_questions[:5]) if research_questions else 'N/A'}

다음 기준으로 비판적으로 검토해주세요:

1. **논리적 타당성**
   - 논리적 비약이나 근거 부족한 주장이 있는가?
   - 인과관계가 명확하게 설명되었는가?

2. **완전성 (Completeness)**
   - 중요한 관점이나 측면이 누락되었는가?
   - 핵심 질문에 충분히 답변했는가?

3. **균형성 (Balance)**
   - 한쪽으로 치우친 시각은 없는가?
   - 반대 의견이나 대안적 관점이 고려되었는가?

4. **깊이 (Depth)**
   - 피상적인 분석에 그치지 않았는가?
   - 더 깊이 파고들어야 할 영역이 있는가?

5. **증거의 질**
   - 충분한 근거와 데이터로 뒷받침되는가?
   - 더 강력한 증거가 필요한 부분이 있는가?

**응답 형식:**

SEVERITY: [critical/moderate/minor/none]

FEEDBACK:
[상세한 피드백 내용]

SUGGESTED_QUERIES:
- [추가 조사가 필요한 쿼리 1]
- [추가 조사가 필요한 쿼리 2]
- [추가 조사가 필요한 쿼리 3]

MISSING_PERSPECTIVES:
- [누락된 관점 1]
- [누락된 관점 2]

REDIRECT_SUGGESTION:
[방향 전환이 필요한 경우에만 작성, 없으면 'N/A']

**참고:**
- 사소한 문제는 지적하지 마세요
- 정말 중요하고 연구 품질에 영향을 주는 부분만 지적하세요
- 내용이 합리적이고 충분하면 "none" 또는 "minor"로 평가하세요
- 건설적이고 구체적인 피드백을 제공하세요""",

                "en": f"""Critically review the following research section and provide constructive feedback:

**Research Topic:** {topic}

**Section Type:** {section_type}

**Section Content:**
{section_content[:2000]}

**Research Context:**
- Sources collected: {sources_count}
- Original research questions: {', '.join(research_questions[:5]) if research_questions else 'N/A'}

Critically evaluate based on:

1. **Logical Validity**
   - Are there logical leaps or unsupported claims?
   - Are causal relationships clearly explained?

2. **Completeness**
   - Are important perspectives or aspects missing?
   - Are key questions sufficiently answered?

3. **Balance**
   - Is there bias toward one perspective?
   - Are opposing views or alternative perspectives considered?

4. **Depth**
   - Is the analysis superficial?
   - Are there areas requiring deeper investigation?

5. **Evidence Quality**
   - Is it backed by sufficient evidence and data?
   - Are there parts needing stronger evidence?

**Response Format:**

SEVERITY: [critical/moderate/minor/none]

FEEDBACK:
[Detailed feedback]

SUGGESTED_QUERIES:
- [Additional query 1]
- [Additional query 2]
- [Additional query 3]

MISSING_PERSPECTIVES:
- [Missing perspective 1]
- [Missing perspective 2]

REDIRECT_SUGGESTION:
[Only if redirection needed, otherwise 'N/A']

**Note:**
- Don't point out trivial issues
- Focus on important aspects affecting research quality
- If content is reasonable and sufficient, rate as "none" or "minor"
- Provide constructive and specific feedback"""
            }

            response = await llm.ainvoke([
                HumanMessage(content=prompts.get(language, prompts["ko"]))
            ])

            # 응답 파싱
            result = self._parse_feedback_response(response.content.strip())

            return result

        except Exception as e:
            print(f"[ERROR] Failed to generate criticism feedback: {e}")
            import traceback
            print(f"[DEBUG] Traceback: {traceback.format_exc()}")

            # 에러 발생 시 기본 응답
            return {
                "has_issues": False,
                "severity": "none",
                "feedback": f"Feedback generation failed: {str(e)}",
                "suggested_queries": [],
                "redirect_suggestion": "",
                "missing_perspectives": []
            }

    def _parse_feedback_response(self, response_text: str) -> Dict[str, Any]:
        """LLM 응답을 파싱하여 구조화된 피드백으로 변환"""
        result = {
            "has_issues": False,
            "severity": "none",
            "feedback": "",
            "suggested_queries": [],
            "redirect_suggestion": "",
            "missing_perspectives": []
        }

        lines = response_text.split('\n')
        current_section = None

        for line in lines:
            line = line.strip()

            if line.startswith("SEVERITY:"):
                severity = line.replace("SEVERITY:", "").strip().lower()
                result["severity"] = severity
                result["has_issues"] = severity in ["critical", "moderate", "minor"]

            elif line.startswith("FEEDBACK:"):
                current_section = "feedback"

            elif line.startswith("SUGGESTED_QUERIES:"):
                current_section = "queries"

            elif line.startswith("MISSING_PERSPECTIVES:"):
                current_section = "perspectives"

            elif line.startswith("REDIRECT_SUGGESTION:"):
                current_section = "redirect"

            elif line and current_section:
                # 내용 추가
                if current_section == "feedback":
                    result["feedback"] += line + "\n"

                elif current_section == "queries":
                    if line.startswith("-"):
                        query = line.lstrip("- ").strip()
                        if query and len(query) > 5:
                            result["suggested_queries"].append(query)

                elif current_section == "perspectives":
                    if line.startswith("-"):
                        perspective = line.lstrip("- ").strip()
                        if perspective and len(perspective) > 5:
                            result["missing_perspectives"].append(perspective)

                elif current_section == "redirect":
                    if line.upper() != "N/A":
                        result["redirect_suggestion"] += line + " "

        # 정리
        result["feedback"] = result["feedback"].strip()
        result["redirect_suggestion"] = result["redirect_suggestion"].strip()

        return result

    def should_trigger_additional_research(self, feedback: Dict[str, Any]) -> bool:
        """피드백을 기반으로 추가 조사가 필요한지 판단

        Args:
            feedback: generate_feedback()의 반환값

        Returns:
            추가 조사가 필요하면 True
        """
        if feedback["severity"] in ["critical", "moderate"]:
            return True

        if len(feedback["suggested_queries"]) >= 3:
            return True

        if feedback["redirect_suggestion"]:
            return True

        return False
