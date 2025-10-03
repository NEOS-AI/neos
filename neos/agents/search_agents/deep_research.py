"""Deep research agent - conducts comprehensive multi-phase research"""

from typing import Dict, Any, List, TYPE_CHECKING
import asyncio
import concurrent.futures
from tavily import TavilyClient
from langchain.schema import HumanMessage
from datetime import datetime

from neos.config.settings import settings
from neos.utils.llm_factory import create_llm
from ..base import SearchAgent
from ..planning_agent import PlanningAgent

if TYPE_CHECKING:
    from neos.workflow.state import SearchResult


class DeepResearchAgent(SearchAgent):
    """심층 조사 에이전트 - 장시간 다단계 탐색 및 고품질 리포트 생성"""

    def __init__(self):
        super().__init__(
            name="deep_research",
            search_type="deep_research",
            role="Deep Research Specialist",
            goal="Conduct comprehensive deep research through iterative exploration and produce expert-level reports",
            backstory="You are a world-class research analyst who excels at conducting thorough investigations, synthesizing information from multiple sources, and producing comprehensive, well-structured reports."
        )

        # Deep Research 설정
        self.config = {
            "max_queries_per_phase": 10,  # 각 단계별 최대 쿼리 수
            "results_per_query": 5,  # 각 쿼리당 결과 수
            "max_phases": 4,  # 최대 탐색 단계
            "timeout_per_phase": 300,  # 각 단계당 5분 타임아웃
            "min_sources": 30,  # 최소 소스 수
            "quality_threshold": 0.7  # 품질 임계값
        }

        # Tavily client 초기화
        self.tavily_client = None
        self.api_available = False

        if settings.TAVILY_API_KEY and settings.TAVILY_API_KEY.strip():
            try:
                print("[DEBUG] Creating TavilyClient for deep research...")
                self.tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
                self.api_available = True
                print("[DEBUG] TavilyClient created successfully for deep research")
            except Exception as e:
                print(f"[WARNING] Failed to create TavilyClient for deep research: {e}")
                self.tavily_client = None
                self.api_available = False
        else:
            print("[WARNING] TAVILY_API_KEY not set, DeepResearchAgent will return empty results")

        # 체크포인트 저장용
        self.checkpoints = []

        # Planning agent 초기화
        self.planning_agent = PlanningAgent()

    def _get_language_instruction(self, language: str) -> str:
        """언어별 리포트 생성 지침 반환"""
        templates = {
            "ko": """위 정보를 바탕으로 전문가 수준의 종합 리포트를 **한국어로** 작성해주세요.

리포트 구조:
# {query} - Deep Research Report

## 📋 Executive Summary
[주제의 핵심 내용을 5-8문장으로 포괄적으로 요약. 가장 중요한 발견사항과 결론을 명확히 제시]

## 🔍 상세 분석
### 1. 주요 발견사항
[핵심 내용을 5-7개 섹션으로 구조화하여 상세히 설명. 각 섹션은 충분한 내용과 근거를 포함]

### 2. 심층 인사이트
[데이터 기반 분석 및 해석을 풍부하게 제공. 트렌드, 패턴, 인과관계 등을 깊이 있게 분석]

### 3. 비교 분석
[관련 주제들 간의 비교와 대조. 장단점, 차이점, 공통점 등을 명확히 제시]

## 💡 핵심 인사이트
[10-15개의 상세한 bullet points. 각 포인트는 구체적이고 실행 가능한 인사이트 제공]

## 📊 데이터 및 통계
[수집된 주요 데이터와 통계를 정리하여 제시. 출처를 명확히 표기]

## 🔮 전망 및 예측
[미래 전망과 예측. 가능한 시나리오와 그에 따른 영향 분석]

## ⚠️ 주의사항 및 제한사항
[정보의 한계, 상충되는 의견, 불확실성 등을 솔직하게 제시]

## 📚 참고 정보
- 총 소스 개수와 분석 완료 시각 명시
- 주요 출처 및 참고 자료 목록

## 📝 결론
[리포트의 핵심 메시지를 3-5문장으로 정리하여 마무리]

---

**중요 요구사항:**
1. **한국어 작성**: 모든 내용을 한국어로 작성하세요.
2. **완전성**: 모든 섹션을 빠짐없이 작성하세요.
3. **충분한 길이**: 각 섹션은 충분히 상세하게 작성하세요.
4. **구체성**: 구체적인 데이터, 사례, 분석을 제공하세요.
5. **객관성**: 전문적이고 객관적인 톤을 유지하세요.""",

            "en": """Based on the information above, please write a professional comprehensive report **in English**.

Report Structure:
# {query} - Deep Research Report

## 📋 Executive Summary
[Provide a comprehensive 5-8 sentence summary of the topic. Clearly present the most important findings and conclusions]

## 🔍 Detailed Analysis
### 1. Key Findings
[Structure core content into 5-7 sections with detailed explanations. Each section should include sufficient content and evidence]

### 2. In-Depth Insights
[Provide rich data-driven analysis and interpretation. Analyze trends, patterns, and causal relationships in depth]

### 3. Comparative Analysis
[Compare and contrast related topics. Clearly present strengths, weaknesses, differences, and commonalities]

## 💡 Key Insights
[10-15 detailed bullet points. Each point should provide specific and actionable insights]

## 📊 Data and Statistics
[Present collected key data and statistics. Clearly cite sources]

## 🔮 Outlook and Predictions
[Future outlook and predictions. Analyze possible scenarios and their impacts]

## ⚠️ Limitations and Caveats
[Honestly present information limitations, conflicting opinions, and uncertainties]

## 📚 References
- Total number of sources and analysis completion time
- List of main sources and references

## 📝 Conclusion
[Summarize the report's key message in 3-5 sentences]

---

**Important Requirements:**
1. **English Writing**: Write all content in English.
2. **Completeness**: Write all sections without omission.
3. **Sufficient Length**: Write each section in detail.
4. **Specificity**: Provide specific data, examples, and analysis.
5. **Objectivity**: Maintain a professional and objective tone.""",

            "ja": """上記の情報に基づいて、プロフェッショナルレベルの総合レポートを**日本語で**作成してください。

レポート構造:
# {query} - Deep Research Report

## 📋 エグゼクティブサマリー
[トピックの核心内容を5-8文で包括的に要約。最も重要な発見と結論を明確に提示]

## 🔍 詳細分析
### 1. 主要な発見
[核心内容を5-7つのセクションに構造化して詳しく説明。各セクションは十分な内容と根拠を含む]

### 2. 深層インサイト
[データに基づく分析と解釈を豊富に提供。トレンド、パターン、因果関係などを深く分析]

### 3. 比較分析
[関連トピック間の比較と対照。長所、短所、違い、共通点を明確に提示]

## 💡 主要インサイト
[10-15個の詳細な箇条書き。各ポイントは具体的で実行可能なインサイトを提供]

## 📊 データと統計
[収集した主要データと統計を整理して提示。出典を明確に記載]

## 🔮 展望と予測
[将来の展望と予測。可能なシナリオとその影響を分析]

## ⚠️ 注意事項と制限事項
[情報の限界、相反する意見、不確実性などを正直に提示]

## 📚 参考情報
- 総ソース数と分析完了時刻を明記
- 主要な出典と参考資料のリスト

## 📝 結論
[レポートの核心メッセージを3-5文でまとめて締めくくり]

---

**重要な要件:**
1. **日本語作成**: すべての内容を日本語で作成してください。
2. **完全性**: すべてのセクションを漏れなく作成してください。
3. **十分な長さ**: 各セクションは十分に詳しく作成してください。
4. **具体性**: 具体的なデータ、事例、分析を提供してください。
5. **客観性**: プロフェッショナルで客観的なトーンを維持してください。""",

            "zh": """基于以上信息，请撰写一份专业水平的综合报告（**使用中文**）。

报告结构：
# {query} - Deep Research Report

## 📋 执行摘要
[用5-8句话全面总结主题的核心内容。清晰呈现最重要的发现和结论]

## 🔍 详细分析
### 1. 主要发现
[将核心内容结构化为5-7个部分并详细说明。每个部分应包含充足的内容和依据]

### 2. 深度洞察
[提供丰富的数据驱动分析和解读。深入分析趋势、模式、因果关系等]

### 3. 对比分析
[比较和对照相关主题。清晰呈现优缺点、差异和共同点]

## 💡 关键洞察
[10-15个详细要点。每个要点应提供具体且可执行的洞察]

## 📊 数据和统计
[整理并呈现收集的关键数据和统计信息。明确标注来源]

## 🔮 展望与预测
[未来展望和预测。分析可能的情景及其影响]

## ⚠️ 注意事项和局限性
[诚实呈现信息的局限、冲突观点和不确定性]

## 📚 参考信息
- 说明总来源数量和分析完成时间
- 主要来源和参考资料列表

## 📝 结论
[用3-5句话总结报告的核心信息]

---

**重要要求：**
1. **中文撰写**：所有内容使用中文撰写。
2. **完整性**：完整撰写所有部分，不遗漏。
3. **充分长度**：每个部分都要详细撰写。
4. **具体性**：提供具体的数据、案例和分析。
5. **客观性**：保持专业客观的语气。"""
        }

        return templates.get(language, templates["en"])  # 기본값은 영어


    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """심층 조사 실행"""
        print(f"[DEBUG] DeepResearchAgent.execute called with query: {query[:50]}...")

        if not self.validate_input(query, context):
            print("[ERROR] DeepResearchAgent: Invalid input")
            return {"success": False, "error": "Invalid input"}

        if not self.api_available:
            print("[WARNING] TAVILY_API_KEY not available, returning empty results")
            return self.format_output([], {"search_type": "deep_research", "warning": "API key not available"})

        try:
            # Extract session_id and user_id from context
            session_id = context.get("session_id", "") if context else ""
            user_id = context.get("user_id", "") if context else ""

            # 전체 프로세스 실행
            report = await self._run_deep_research(query, session_id, user_id, context)

            # SearchResult 형태로 반환
            from neos.workflow.state import SearchResult
            result = SearchResult(
                source="deep_research_report",
                title=f"Deep Research: {query}",
                content=report,
                url="",
                score=0.95,
                metadata={
                    "processing_type": "deep_research",
                    "phases_completed": len(self.checkpoints),
                    "total_sources": sum(cp.get("data", {}).get("sources_count", 0) for cp in self.checkpoints),
                    "checkpoints": self.checkpoints
                }
            )

            print("[DEBUG] DeepResearchAgent execution completed successfully")
            return self.format_output([result], {"search_type": "deep_research"})

        except Exception as e:
            print(f"[ERROR] DeepResearchAgent execution failed: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e), "agent": self.name}


    async def _run_deep_research(self, query: str, session_id: str, user_id: str, context: Dict[str, Any]) -> str:
        """4단계 심층 조사 프로세스"""
        print("[INFO] ==================== Deep Research Process Started ====================")

        # Get detected language
        detected_language = context.get("detected_language", "ko")

        # Create research plan using planning agent
        print("[INFO] Creating comprehensive research plan...")
        research_plan = await self.planning_agent.create_research_plan(
            query=query,
            research_type="deep_research",
            session_id=session_id,
            user_id=user_id,
            detected_language=detected_language
        )
        print(f"[INFO] Research plan created with {len(research_plan)} tasks")
        print(f"[INFO] Plan:\n{self.planning_agent.get_task_summary(research_plan)}")

        all_search_results = []
        all_summaries = []

        # Phase 1: 초기 탐색 (광범위한 검색)
        if research_plan and len(research_plan) > 0:
            self.planning_agent.update_task_status(research_plan, 1, "in_progress")
            print(f"[INFO] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

        print("[INFO] Phase 1/4: Initial Exploration - Broad search across multiple perspectives")
        phase1_queries = await self._generate_initial_queries(query, session_id, user_id, detected_language)
        phase1_results = await self._execute_parallel_searches(phase1_queries)
        all_search_results.extend(phase1_results)

        phase1_summaries = await self._summarize_results_batch(phase1_queries, phase1_results, session_id, user_id, detected_language)
        all_summaries.extend(phase1_summaries)

        # 체크포인트 저장
        await self._save_checkpoint("phase1", {
            "queries": phase1_queries,
            "sources_count": sum(len(r) for r in phase1_results),
            "summaries": phase1_summaries
        })

        # Mark Phase 1 complete
        if research_plan and len(research_plan) > 0:
            self.planning_agent.update_task_status(
                research_plan, 1, "completed",
                result=f"Explored {len(phase1_queries)} queries, collected {sum(len(r) for r in phase1_results)} sources"
            )
            print(f"[INFO] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

        # Phase 2: Gap 분석 및 심화 탐색
        if research_plan and len(research_plan) > 1:
            self.planning_agent.update_task_status(research_plan, 2, "in_progress")
            print(f"[INFO] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

        print("[INFO] Phase 2/4: Gap Analysis - Identifying and filling knowledge gaps")
        gaps = await self._identify_gaps(query, all_summaries, session_id, user_id, detected_language)
        phase2_queries = await self._generate_targeted_queries(gaps, session_id, user_id, detected_language)
        phase2_results = await self._execute_parallel_searches(phase2_queries)
        all_search_results.extend(phase2_results)

        phase2_summaries = await self._summarize_results_batch(phase2_queries, phase2_results, session_id, user_id, detected_language)
        all_summaries.extend(phase2_summaries)

        # 체크포인트 저장
        await self._save_checkpoint("phase2", {
            "gaps": gaps,
            "queries": phase2_queries,
            "sources_count": sum(len(r) for r in phase2_results),
            "summaries": phase2_summaries
        })

        # Mark Phase 2 complete
        if research_plan and len(research_plan) > 1:
            self.planning_agent.update_task_status(
                research_plan, 2, "completed",
                result=f"Filled {len(gaps)} gaps with {len(phase2_queries)} targeted queries"
            )
            print(f"[INFO] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

        # Phase 3: 크로스 레퍼런스 및 검증
        if research_plan and len(research_plan) > 2:
            self.planning_agent.update_task_status(research_plan, 3, "in_progress")
            print(f"[INFO] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

        print("[INFO] Phase 3/4: Verification - Cross-referencing and fact-checking")
        verification_insights = await self._cross_reference_sources(all_summaries, session_id, user_id, detected_language)

        # 체크포인트 저장
        await self._save_checkpoint("phase3", {
            "verification_insights": verification_insights,
            "total_sources": sum(len(r) for r in all_search_results)
        })

        # Mark Phase 3 complete
        if research_plan and len(research_plan) > 2:
            self.planning_agent.update_task_status(
                research_plan, 3, "completed",
                result=f"Verified information from {sum(len(r) for r in all_search_results)} sources"
            )
            print(f"[INFO] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

        # Phase 4: 종합 리포트 생성
        if research_plan and len(research_plan) > 3:
            self.planning_agent.update_task_status(research_plan, 4, "in_progress")
            print(f"[INFO] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

        print("[INFO] Phase 4/4: Report Generation - Synthesizing comprehensive report")
        final_report = await self._generate_comprehensive_report(
            query,
            all_summaries,
            verification_insights,
            all_search_results,
            session_id,
            user_id,
            context
        )

        # 체크포인트 저장
        await self._save_checkpoint("phase4", {
            "report_length": len(final_report),
            "total_phases": 4
        })

        # Mark Phase 4 complete
        if research_plan and len(research_plan) > 3:
            self.planning_agent.update_task_status(
                research_plan, 4, "completed",
                result=f"Generated comprehensive report ({len(final_report)} characters)"
            )
            print(f"[INFO] Final plan:\n{self.planning_agent.get_task_summary(research_plan)}")

        print("[INFO] ==================== Deep Research Completed ====================")
        print(f"[INFO] Total Sources: {sum(len(r) for r in all_search_results)}")
        print(f"[INFO] Total Queries: {len(phase1_queries) + len(phase2_queries)}")
        print(f"[INFO] Report Length: {len(final_report)} characters")

        return final_report

    async def _generate_initial_queries(self, original_query: str, session_id: str, user_id: str, detected_language: str = "ko") -> List[str]:
        """초기 광범위 검색 쿼리 생성 (8-10개)"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            base_llm = create_llm(temperature=0.4, max_tokens=2000)

            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="deep_research",
                agent_name=self.name,
                tags=["initial_query_generation", f"language:{detected_language}"]
            )

            # Language-specific prompts
            prompts = {
                "ko": f"""사용자 질문: {original_query}

위 질문에 대한 포괄적인 심층 조사를 위해 8-10개의 다각도 검색 쿼리를 **한국어로** 생성해주세요.

요구사항:
1. 각 쿼리는 서로 다른 관점이나 측면을 다뤄야 합니다
2. 기술적, 시장적, 역사적, 미래 전망 등 다양한 각도 포함
3. 구체적이고 검색 가능한 쿼리로 작성
4. 각 쿼리는 한 줄로 작성

검색 쿼리:""",

                "en": f"""User Question: {original_query}

Generate 8-10 multi-perspective search queries for comprehensive deep research on the above question **in English**.

Requirements:
1. Each query should cover different perspectives or aspects
2. Include technical, market, historical, and future outlook angles
3. Write specific and searchable queries
4. Write each query on a single line

Search Queries:""",

                "ja": f"""ユーザーの質問: {original_query}

上記の質問に関する包括的な詳細調査のために、8-10個の多角的な検索クエリを**日本語で**生成してください。

要件:
1. 各クエリは異なる観点や側面をカバーする必要があります
2. 技術的、市場的、歴史的、将来の見通しなど、さまざまな角度を含めてください
3. 具体的で検索可能なクエリを作成してください
4. 各クエリは1行で記述してください

検索クエリ:""",

                "zh": f"""用户问题: {original_query}

针对上述问题进行全面深入研究，请生成8-10个多角度搜索查询（**用中文**）。

要求:
1. 每个查询应涵盖不同的观点或方面
2. 包括技术、市场、历史和未来展望等多种角度
3. 编写具体且可搜索的查询
4. 每个查询写在一行

搜索查询:"""
            }

            prompt = prompts.get(detected_language, prompts["en"])

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            query_text = response.content.strip()

            # 쿼리 파싱
            queries = [q.strip() for q in query_text.split('\n') if q.strip() and not q.strip().startswith('#')]
            queries = queries[:10]  # 최대 10개

            # 최소 8개 보장
            if len(queries) < 8:
                queries.extend([
                    f"{original_query} overview",
                    f"{original_query} latest trends",
                    f"{original_query} market analysis",
                    f"{original_query} technical details",
                    f"{original_query} future outlook",
                    f"{original_query} case studies",
                    f"{original_query} expert opinions",
                    f"{original_query} comparative analysis"
                ])
                queries = queries[:10]

            print(f"[DEBUG] Generated {len(queries)} initial queries")
            return queries

        except Exception as e:
            print(f"[ERROR] Failed to generate initial queries: {e}")
            return [original_query]

    async def _identify_gaps(self, original_query: str, summaries: List[str], session_id: str, user_id: str, detected_language: str = "ko") -> List[str]:
        """수집된 정보에서 부족한 부분 식별"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            base_llm = create_llm(temperature=0.3, max_tokens=1500)

            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="deep_research",
                agent_name=self.name,
                tags=["gap_analysis", f"language:{detected_language}"]
            )

            summaries_text = "\n\n".join([f"정보 {i+1}: {s[:300]}" for i, s in enumerate(summaries[:5])])

            # Language-specific prompts
            prompts = {
                "ko": f"""원래 질문: {original_query}

현재까지 수집된 정보:
{summaries_text}

위 정보를 분석하여 아직 답변되지 않은 중요한 질문이나 부족한 측면을 3-5개 **한국어로** 식별해주세요.

각 gap은 한 줄로 작성하고, 번호를 붙이지 마세요.""",

                "en": f"""Original Question: {original_query}

Information collected so far:
{summaries_text}

Analyze the above information and identify 3-5 important questions or missing aspects that have not been answered yet **in English**.

Write each gap on one line without numbering.""",

                "ja": f"""元の質問: {original_query}

これまでに収集された情報:
{summaries_text}

上記の情報を分析し、まだ回答されていない重要な質問や不足している側面を3-5個**日本語で**特定してください。

各ギャップは1行で記述し、番号を付けないでください。""",

                "zh": f"""原始问题: {original_query}

目前收集到的信息:
{summaries_text}

分析以上信息，识别3-5个尚未回答的重要问题或缺失方面（**用中文**）。

每个缺口写在一行，不要编号。"""
            }

            prompt = prompts.get(detected_language, prompts["en"])

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            gaps_text = response.content.strip()

            gaps = [g.strip() for g in gaps_text.split('\n') if g.strip()]
            print(f"[DEBUG] Identified {len(gaps)} knowledge gaps")
            return gaps[:5]

        except Exception as e:
            print(f"[ERROR] Failed to identify gaps: {e}")
            return []

    async def _generate_targeted_queries(self, gaps: List[str], session_id: str, user_id: str, detected_language: str = "ko") -> List[str]:
        """Gap을 메우기 위한 targeted 검색 쿼리 생성"""
        if not gaps:
            return []

        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            base_llm = create_llm(temperature=0.3, max_tokens=1200)

            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="deep_research",
                agent_name=self.name,
                tags=["targeted_query_generation", f"language:{detected_language}"]
            )

            gaps_text = "\n".join(gaps)

            # Add language instruction
            language_instructions = {
                "ko": "**한국어로** 다음 지식 gap들을 메우기 위한 구체적인 검색 쿼리를 각각 1-2개씩 생성해주세요:",
                "en": "Generate 1-2 specific search queries **in English** to fill each of the following knowledge gaps:",
                "ja": "**日本語で**次のナレッジギャップを埋めるための具体的な検索クエリを各1-2個生成してください:",
                "zh": "**用中文**为以下每个知识缺口生成1-2个具体的搜索查询:"
            }

            instruction = language_instructions.get(detected_language, language_instructions["en"])

            prompt = f"""{instruction}

{gaps_text}

각 쿼리는 한 줄로 작성하고, 구체적이고 검색 가능하게 만들어주세요."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            query_text = response.content.strip()

            queries = [q.strip() for q in query_text.split('\n') if q.strip()]
            print(f"[DEBUG] Generated {len(queries)} targeted queries for gaps")
            return queries[:8]

        except Exception as e:
            print(f"[ERROR] Failed to generate targeted queries: {e}")
            return []

    async def _cross_reference_sources(self, summaries: List[str], session_id: str, user_id: str, detected_language: str = "ko") -> List[str]:
        """소스 간 크로스 레퍼런스 및 일관성 확인"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            base_llm = create_llm(temperature=0.2, max_tokens=2000)

            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="deep_research",
                agent_name=self.name,
                tags=["cross_reference", "verification"]
            )

            summaries_text = "\n\n".join([f"소스 {i+1}: {s[:250]}" for i, s in enumerate(summaries[:8])])

            prompt = f"""다음 소스들을 분석하여:

{summaries_text}

다음을 확인해주세요:
1. 일관된 정보와 상충하는 정보 식별
2. 여러 소스에서 확인된 핵심 사실
3. 신뢰도가 높은 정보와 검증이 필요한 정보 구분

각 인사이트는 한 문장으로 작성하고, 5-7개 정도 제공해주세요."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            insights_text = response.content.strip()

            insights = [i.strip() for i in insights_text.split('\n') if i.strip()]
            print(f"[DEBUG] Generated {len(insights)} verification insights")
            return insights

        except Exception as e:
            print(f"[ERROR] Failed to cross-reference sources: {e}")
            return []

    async def _generate_comprehensive_report(
        self,
        query: str,
        all_summaries: List[str],
        verification_insights: List[str],
        all_search_results: List[List[Dict[str, Any]]],
        session_id: str,
        user_id: str,
        context: Dict[str, Any] = None
    ) -> str:
        """종합 리포트 생성 (구조화된 마크다운)"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            # Deep research는 매우 긴 리포트를 생성할 수 있으므로 최대 토큰을 크게 설정
            base_llm = create_llm(temperature=0.3, max_tokens=16000)

            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="deep_research",
                agent_name=self.name,
                tags=["report_generation", "synthesis"]
            )

            # 감지된 언어 가져오기
            detected_language = context.get("detected_language", "ko") if context else "ko"

            # 언어별 프롬프트 템플릿
            language_instructions = self._get_language_instruction(detected_language)

            # 요약 통합 - 더 많은 요약 포함
            summaries_text = "\n\n".join([f"### 정보 블록 {i+1}\n{s}" for i, s in enumerate(all_summaries[:20])])

            # 검증 인사이트
            verification_text = "\n".join([f"- {v}" for v in verification_insights])

            # 총 소스 수 계산
            total_sources = sum(len(r) for r in all_search_results)

            prompt = f"""주제: {query}

수집된 정보 ({total_sources}개 소스):
{summaries_text}

검증 결과:
{verification_text}

{language_instructions}"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            report = response.content.strip()

            print(f"[DEBUG] Generated comprehensive report: {len(report)} characters")
            return report

        except Exception as e:
            print(f"[ERROR] Failed to generate comprehensive report: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")

            # Fallback: 기본 리포트
            return f"""# {query} - Deep Research Report

## 수집된 정보
{chr(10).join(all_summaries[:10])}

## 검증 결과
{chr(10).join(verification_insights)}

총 {sum(len(r) for r in all_search_results)}개 소스에서 정보 수집 완료.
"""

    async def _execute_parallel_searches(self, queries: List[str]) -> List[List[Dict[str, Any]]]:
        """병렬 검색 실행"""
        import asyncio

        search_tasks = [self._single_tavily_search(q) for q in queries]
        results = await asyncio.gather(*search_tasks, return_exceptions=True)

        # Exception 처리
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"[WARNING] Search for query '{queries[i]}' failed: {result}")
                processed_results.append([])
            else:
                processed_results.append(result)

        return processed_results

    async def _single_tavily_search(self, query: str) -> List[Dict[str, Any]]:
        """단일 검색 실행"""
        try:
            if not self.api_available or not self.tavily_client:
                return []

            import asyncio
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                try:
                    future = executor.submit(
                        self.tavily_client.search,
                        query=query,
                        search_depth="advanced",
                        max_results=self.config["results_per_query"],
                        include_answer=True,
                        include_raw_content=True
                    )

                    def get_result_with_timeout():
                        try:
                            return future.result(timeout=20)
                        except concurrent.futures.TimeoutError:
                            return None

                    response = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, get_result_with_timeout),
                        timeout=25
                    )

                    return response.get("results", []) if response else []

                except Exception as e:
                    print(f"[ERROR] Search failed for '{query}': {e}")
                    return []

        except Exception as e:
            print(f"[ERROR] Tavily search error: {e}")
            return []

    async def _summarize_results_batch(self, queries: List[str], results: List[List[Dict[str, Any]]], session_id: str, user_id: str, detected_language: str = "ko") -> List[str]:
        """검색 결과 배치 요약"""
        import asyncio

        async def summarize_single(query: str, search_results: List[Dict[str, Any]]) -> str:
            if not search_results:
                return f"'{query}'에 대한 검색 결과 없음"

            try:
                from neos.utils.llm_wrapper import create_tracked_llm
                # Deep research 요약은 더 상세하게
                base_llm = create_llm(temperature=0.1, max_tokens=2500)

                llm = create_tracked_llm(
                    llm=base_llm,
                    session_id=session_id,
                    user_id=user_id,
                    workflow_step="deep_research",
                    agent_name=self.name,
                    tags=["result_summarization"]
                )

                context_parts = []
                for i, result in enumerate(search_results[:5], 1):
                    title = result.get("title", "")
                    content = result.get("content", "")[:800]  # 더 많은 내용 포함
                    url = result.get("url", "")
                    context_parts.append(f"출처 {i}: {title}\nURL: {url}\n내용: {content}")

                context = "\n\n".join(context_parts)

                prompt = f"""검색 쿼리: {query}

{context}

위 정보를 **상세하게** 요약해주세요 (최소 5-8문장). 중요한 데이터, 수치, 사실을 모두 포함하고 출처를 명시하세요.
가능한 한 많은 정보를 포함하되, 핵심을 벗어나지 마세요."""

                response = await llm.ainvoke([HumanMessage(content=prompt)])
                return response.content.strip()

            except Exception as e:
                print(f"[ERROR] Failed to summarize for '{query}': {e}")
                return f"'{query}' 요약 실패"

        summary_tasks = [summarize_single(q, r) for q, r in zip(queries, results)]

        try:
            summaries = await asyncio.wait_for(
                asyncio.gather(*summary_tasks, return_exceptions=True),
                timeout=120
            )

            processed = []
            for i, s in enumerate(summaries):
                if isinstance(s, Exception):
                    processed.append(f"요약 실패: {queries[i]}")
                else:
                    processed.append(s)

            return processed

        except asyncio.TimeoutError:
            print("[ERROR] Batch summarization timed out")
            return [f"'{q}' 요약 시간 초과" for q in queries]

    async def _save_checkpoint(self, phase: str, data: Dict[str, Any]) -> None:
        """체크포인트 저장"""
        checkpoint = {
            "phase": phase,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }

        self.checkpoints.append(checkpoint)
        print(f"[DEBUG] Checkpoint saved for {phase}: {len(self.checkpoints)} total checkpoints")
