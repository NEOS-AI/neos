"""Planning agent for complex research tasks"""

from typing import List
from dataclasses import dataclass
from langchain_core.messages import HumanMessage

from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import extract_text_from_response


@dataclass
class ResearchTask:
    """Research task item"""
    id: int
    description: str
    status: str  # pending, in_progress, completed
    result: str = ""
    dependencies: List[int] = None

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


class PlanningAgent:
    """Planning agent that creates structured research plans"""

    def __init__(self):
        self.name = "planning_agent"

    async def create_research_plan(
        self,
        query: str,
        research_type: str,
        session_id: str = "",
        user_id: str = "",
        detected_language: str = "ko"
    ) -> List[ResearchTask]:
        """Create a structured research plan with tasks"""
        print(f"[DEBUG] PlanningAgent creating research plan for: {query[:50]}...")

        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            base_llm = create_llm(temperature=0.3, max_tokens=2000)

            # Prepare custom metadata for tracking
            planning_metadata = {
                "query": query,
                "research_type": research_type,
                "detected_language": detected_language,
                "purpose": "create_research_plan"
            }

            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="planning",
                agent_name=self.name,
                tags=[
                    "research_planning",
                    f"research_type:{research_type}",
                    f"language:{detected_language}"
                ],
                custom_metadata=planning_metadata
            )

            # Language-specific prompts
            prompts = {
                "ko": self._get_korean_planning_prompt(query, research_type),
                "en": self._get_english_planning_prompt(query, research_type),
                "ja": self._get_japanese_planning_prompt(query, research_type),
                "zh": self._get_chinese_planning_prompt(query, research_type)
            }

            prompt = prompts.get(detected_language, prompts["en"])

            print(f"[DEBUG] Invoking LLM for planning (language={detected_language}, type={research_type})")
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            plan_text = extract_text_from_response(response).strip()

            # Parse the plan into tasks
            tasks = self._parse_plan(plan_text)

            # Update custom_metadata with the generated plan
            # Note: This will be captured in the next LLM call, but we can log it separately
            plan_summary = {
                "query": query,
                "research_type": research_type,
                "detected_language": detected_language,
                "num_tasks": len(tasks),
                "tasks": [{"id": t.id, "description": t.description} for t in tasks],
                "raw_plan": plan_text
            }

            print(f"[DEBUG] Created research plan with {len(tasks)} tasks")
            print("[DEBUG] Planning LLM call has been tracked for dataset collection")
            print(f"[DEBUG] Plan metadata: {plan_summary}")
            return tasks

        except Exception as e:
            print(f"[ERROR] Failed to create research plan: {e}")
            # Fallback: create basic plan
            return self._create_fallback_plan(query, research_type, detected_language)

    def _get_korean_planning_prompt(self, query: str, research_type: str) -> str:
        """Korean planning prompt"""
        task_count = "8-10" if research_type == "deep_research" else "4-6"

        return f"""질문: {query}
리서치 유형: {research_type}

위 질문에 대해 체계적인 리서치를 수행하기 위한 단계별 계획을 수립해주세요.

요구사항:
1. {task_count}개의 구체적인 작업(task)으로 구성하세요
2. 각 작업은 독립적으로 실행 가능해야 합니다
3. 작업 순서는 논리적이어야 하며, 기초 → 심화 순으로 배열하세요
4. 각 작업은 다음 형식으로 작성하세요:
   - Task [번호]: [작업 설명]

예시:
- Task 1: 주제의 기본 개념과 정의 조사
- Task 2: 최신 동향 및 뉴스 수집
- Task 3: 주요 플레이어 및 경쟁 구도 분석

작업 계획:"""

    def _get_english_planning_prompt(self, query: str, research_type: str) -> str:
        """English planning prompt"""
        task_count = "8-10" if research_type == "deep_research" else "4-6"

        return f"""Question: {query}
Research Type: {research_type}

Please create a step-by-step plan for conducting systematic research on the above question.

Requirements:
1. Create {task_count} specific tasks
2. Each task should be independently executable
3. Tasks should be in logical order, from basic to advanced
4. Format each task as follows:
   - Task [number]: [task description]

Example:
- Task 1: Research basic concepts and definitions of the topic
- Task 2: Collect latest trends and news
- Task 3: Analyze key players and competitive landscape

Task Plan:"""

    def _get_japanese_planning_prompt(self, query: str, research_type: str) -> str:
        """Japanese planning prompt"""
        task_count = "8-10" if research_type == "deep_research" else "4-6"

        return f"""質問: {query}
リサーチタイプ: {research_type}

上記の質問について体系的なリサーチを行うための段階的な計画を立ててください。

要件:
1. {task_count}個の具体的なタスクを作成してください
2. 各タスクは独立して実行可能でなければなりません
3. タスクの順序は論理的で、基礎から応用の順に配置してください
4. 各タスクは次の形式で記述してください:
   - Task [番号]: [タスクの説明]

例:
- Task 1: トピックの基本概念と定義の調査
- Task 2: 最新動向とニュースの収集
- Task 3: 主要プレーヤーと競争構造の分析

タスク計画:"""

    def _get_chinese_planning_prompt(self, query: str, research_type: str) -> str:
        """Chinese planning prompt"""
        task_count = "8-10" if research_type == "deep_research" else "4-6"

        return f"""问题: {query}
研究类型: {research_type}

请为上述问题制定系统研究的分步计划。

要求:
1. 创建{task_count}个具体任务
2. 每个任务应该可以独立执行
3. 任务顺序应该符合逻辑，从基础到深入
4. 每个任务按以下格式编写:
   - Task [编号]: [任务描述]

示例:
- Task 1: 研究主题的基本概念和定义
- Task 2: 收集最新趋势和新闻
- Task 3: 分析主要参与者和竞争格局

任务计划:"""

    def _parse_plan(self, plan_text: str) -> List[ResearchTask]:
        """Parse LLM response into structured tasks"""
        tasks = []
        lines = plan_text.split('\n')

        task_id = 1
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Look for task patterns: "- Task N:", "Task N:", "N.", etc.
            if any(pattern in line.lower() for pattern in ['task', '작업', 'タスク', '任务']):
                # Remove leading markers like "- ", "* ", numbers, etc.
                description = line
                for marker in ['- task', 'task', '- 작업', '작업', '- タスク', 'タスク', '- 任务', '任务']:
                    if marker in description.lower():
                        # Find and remove the task number
                        parts = description.split(':', 1)
                        if len(parts) == 2:
                            description = parts[1].strip()
                            break

                # Clean up the description
                description = description.lstrip('0123456789-*•. ')

                if description and len(description) > 5:  # Ignore very short descriptions
                    tasks.append(ResearchTask(
                        id=task_id,
                        description=description,
                        status="pending"
                    ))
                    task_id += 1

        return tasks if tasks else self._create_default_tasks()

    def _create_default_tasks(self) -> List[ResearchTask]:
        """Create default tasks if parsing fails"""
        return [
            ResearchTask(id=1, description="Initial research and background", status="pending"),
            ResearchTask(id=2, description="Detailed analysis", status="pending"),
            ResearchTask(id=3, description="Synthesis and conclusion", status="pending")
        ]

    def _create_fallback_plan(self, query: str, research_type: str, detected_language: str) -> List[ResearchTask]:
        """Create a fallback plan in case of errors"""
        templates = {
            "ko": [
                "기본 개념 및 배경 조사",
                "최신 동향 및 데이터 수집",
                "상세 분석 및 비교",
                "종합 및 결론 도출"
            ],
            "en": [
                "Research basic concepts and background",
                "Collect latest trends and data",
                "Detailed analysis and comparison",
                "Synthesis and conclusions"
            ],
            "ja": [
                "基本概念と背景の調査",
                "最新動向とデータの収集",
                "詳細分析と比較",
                "統合と結論"
            ],
            "zh": [
                "研究基本概念和背景",
                "收集最新趋势和数据",
                "详细分析和比较",
                "综合和结论"
            ]
        }

        descriptions = templates.get(detected_language, templates["en"])

        return [
            ResearchTask(id=i+1, description=desc, status="pending")
            for i, desc in enumerate(descriptions)
        ]

    def update_task_status(self, tasks: List[ResearchTask], task_id: int, status: str, result: str = "") -> None:
        """Update task status"""
        for task in tasks:
            if task.id == task_id:
                task.status = status
                if result:
                    task.result = result
                break

    def get_next_pending_task(self, tasks: List[ResearchTask]) -> ResearchTask:
        """Get the next pending task"""
        for task in tasks:
            if task.status == "pending":
                return task
        return None

    def get_task_summary(self, tasks: List[ResearchTask]) -> str:
        """Get a summary of all tasks"""
        summary_lines = []
        for task in tasks:
            status_emoji = "✅" if task.status == "completed" else "🔄" if task.status == "in_progress" else "⏳"
            summary_lines.append(f"{status_emoji} Task {task.id}: {task.description}")

        return "\n".join(summary_lines)
