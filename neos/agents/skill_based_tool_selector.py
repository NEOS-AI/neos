"""Skill-based Tool Selector - LLM-powered intelligent selection of skills and tools"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import json
import logging
from langchain_core.messages import HumanMessage

from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm


logger = logging.getLogger(__name__)


@dataclass
class SkillToolSelection:
    """Skill and Tool selection result

    Attributes:
        selected_skills: List of selected skill names
        selected_tools: List of selected tool names
        reasoning: Reasoning for the selection
        priority_order: Priority order for execution
    """
    selected_skills: List[str]
    selected_tools: List[str]
    reasoning: str
    priority_order: List[Dict[str, str]]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "selected_skills": self.selected_skills,
            "selected_tools": self.selected_tools,
            "reasoning": self.reasoning,
            "priority_order": self.priority_order
        }


class SkillBasedToolSelector:
    """LLM-powered subagent for intelligent skill and tool selection

    This subagent analyzes the query and context, then selects only the necessary
    skills and tools from the available options. It uses TrackedLLM to log all
    decisions for dataset collection.

    Attributes:
        name: Agent name
        skill_registry: SkillRegistry instance (lazy loaded)
        tool_selector: ToolSelector instance (lazy loaded)
    """

    def __init__(self):
        self.name = "skill_based_tool_selector"
        self._skill_registry = None
        self._tool_selector = None

    @property
    def skill_registry(self):
        """Lazy load SkillRegistry"""
        if self._skill_registry is None:
            from neos.skills.manager.skill_manager import skill_manager
            self._skill_registry = skill_manager.registry
        return self._skill_registry

    @property
    def tool_selector(self):
        """Lazy load ToolSelector"""
        if self._tool_selector is None:
            from neos.tools.manager.tool_selector import tool_selector
            self._tool_selector = tool_selector
        return self._tool_selector

    async def select_skills_and_tools(
        self,
        query: str,
        context: Dict[str, Any],
        session_id: str = "",
        user_id: str = "",
        detected_language: str = "ko"
    ) -> SkillToolSelection:
        """Select necessary skills and tools based on query and context

        Args:
            query: User query or task description
            context: Additional context (intent, query_type, etc.)
            session_id: Session ID for tracking
            user_id: User ID for tracking
            detected_language: Detected language (ko, en, ja, zh)

        Returns:
            SkillToolSelection object with selected skills, tools, and reasoning
        """
        logger.info(f"[{self.name}] Selecting skills and tools for query: {query[:100]}...")

        try:
            # Get available skills and tools
            available_skills = self._get_available_skills()
            available_tools = self._get_available_tools()

            # Create tracked LLM for dataset collection
            base_llm = create_llm(temperature=0.2, max_tokens=3000)

            selection_metadata = {
                "query": query,
                "context": context,
                "detected_language": detected_language,
                "available_skills_count": len(available_skills),
                "available_tools_count": len(available_tools),
                "purpose": "skill_tool_selection"
            }

            tracked_llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="skill_tool_selection",
                agent_name=self.name,
                tags=[
                    "skill_selection",
                    "tool_selection",
                    f"language:{detected_language}",
                    f"intent:{context.get('intent', 'unknown')}"
                ],
                custom_metadata=selection_metadata
            )

            # Create prompt based on language
            prompts = {
                "ko": self._get_korean_selection_prompt,
                "en": self._get_english_selection_prompt,
                "ja": self._get_japanese_selection_prompt,
                "zh": self._get_chinese_selection_prompt
            }

            prompt_func = prompts.get(detected_language, prompts["ko"])
            prompt = prompt_func(query, context, available_skills, available_tools)

            # Invoke LLM for selection
            logger.info(f"[{self.name}] Invoking LLM for skill/tool selection (language={detected_language})")
            response = await tracked_llm.ainvoke([HumanMessage(content=prompt)])

            # Extract text from response (handles both string and list content when thinking blocks are enabled)
            from neos.utils.llm_wrapper import extract_text_from_response
            selection_text = extract_text_from_response(response).strip()

            # Parse the selection
            selection = self._parse_selection(selection_text, available_skills, available_tools)

            logger.info(
                f"[{self.name}] Selected {len(selection.selected_skills)} skills "
                f"and {len(selection.selected_tools)} tools"
            )
            logger.info(f"[{self.name}] Skills: {selection.selected_skills}")
            logger.info(f"[{self.name}] Tools: {selection.selected_tools}")
            logger.info(f"[{self.name}] Selection has been tracked for dataset collection")

            return selection

        except Exception as e:
            logger.error(f"[{self.name}] Failed to select skills/tools: {e}", exc_info=True)
            # Return fallback selection
            return self._create_fallback_selection(context)

    def _get_available_skills(self) -> List[Dict[str, Any]]:
        """Get list of available skills

        Returns:
            List of skill info dictionaries
        """
        skills = []
        for skill_info in self.skill_registry.list_skills():
            skills.append({
                "name": skill_info.name,
                "type": skill_info.skill_type.value,
                "description": skill_info.description,
                "capabilities": skill_info.capabilities,
                "version": skill_info.version
            })
        return skills

    def _get_available_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools

        Returns:
            List of tool info dictionaries
        """
        try:
            tools_summary = self.tool_selector.get_available_tools_summary()
            tools = tools_summary.get("mcp_tools", [])

            # Add strategy-based tools
            strategies = tools_summary.get("strategies", [])
            for strategy in strategies:
                tools.append({
                    "name": strategy,
                    "type": "strategy",
                    "description": f"Tool strategy for {strategy}",
                    "capabilities": [strategy]
                })

            return tools
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to get available tools: {e}")
            return []

    def _get_korean_selection_prompt(
        self,
        query: str,
        context: Dict[str, Any],
        available_skills: List[Dict[str, Any]],
        available_tools: List[Dict[str, Any]]
    ) -> str:
        """Create Korean selection prompt"""

        skills_text = self._format_skills_list(available_skills)
        tools_text = self._format_tools_list(available_tools)
        context_text = json.dumps(context, ensure_ascii=False, indent=2)

        return f"""# Task: Skill 및 Tool 선택

## 사용자 쿼리:
{query}

## 컨텍스트:
```json
{context_text}
```

## 사용 가능한 Skills:
{skills_text}

## 사용 가능한 Tools:
{tools_text}

## 목표:
위 쿼리와 컨텍스트를 분석하여, 이 작업을 완수하는 데 **실제로 필요한** Skills와 Tools만 선택하세요.

## 선택 기준:
1. **관련성**: 쿼리와 직접적으로 관련된 것만 선택
2. **필요성**: 반드시 필요한 것만 선택 (있으면 좋은 것은 제외)
3. **효율성**: 중복 기능을 가진 것들은 하나만 선택
4. **우선순위**: 실행 순서를 고려한 선택

## 응답 형식:
다음 JSON 형식으로 정확하게 응답하세요:

```json
{{
  "selected_skills": ["skill_name_1", "skill_name_2"],
  "selected_tools": ["tool_name_1", "tool_name_2"],
  "reasoning": "선택한 이유에 대한 간단한 설명 (한글)",
  "priority_order": [
    {{"type": "skill", "name": "skill_name_1", "reason": "이유"}},
    {{"type": "tool", "name": "tool_name_1", "reason": "이유"}}
  ]
}}
```

**중요**: JSON만 출력하세요. 다른 설명이나 마크다운은 포함하지 마세요."""

    def _get_english_selection_prompt(
        self,
        query: str,
        context: Dict[str, Any],
        available_skills: List[Dict[str, Any]],
        available_tools: List[Dict[str, Any]]
    ) -> str:
        """Create English selection prompt"""

        skills_text = self._format_skills_list(available_skills)
        tools_text = self._format_tools_list(available_tools)
        context_text = json.dumps(context, ensure_ascii=False, indent=2)

        return f"""# Task: Select Skills and Tools

## User Query:
{query}

## Context:
```json
{context_text}
```

## Available Skills:
{skills_text}

## Available Tools:
{tools_text}

## Goal:
Analyze the query and context, then select **ONLY the skills and tools that are actually necessary** to complete this task.

## Selection Criteria:
1. **Relevance**: Select only items directly related to the query
2. **Necessity**: Select only essential items (exclude "nice to have")
3. **Efficiency**: If multiple items have overlapping functionality, select only one
4. **Priority**: Consider execution order

## Response Format:
Respond in exactly this JSON format:

```json
{{
  "selected_skills": ["skill_name_1", "skill_name_2"],
  "selected_tools": ["tool_name_1", "tool_name_2"],
  "reasoning": "Brief explanation of why these were selected",
  "priority_order": [
    {{"type": "skill", "name": "skill_name_1", "reason": "reason"}},
    {{"type": "tool", "name": "tool_name_1", "reason": "reason"}}
  ]
}}
```

**Important**: Output ONLY the JSON. Do not include any other explanations or markdown."""

    def _get_japanese_selection_prompt(
        self,
        query: str,
        context: Dict[str, Any],
        available_skills: List[Dict[str, Any]],
        available_tools: List[Dict[str, Any]]
    ) -> str:
        """Create Japanese selection prompt"""

        skills_text = self._format_skills_list(available_skills)
        tools_text = self._format_tools_list(available_tools)
        context_text = json.dumps(context, ensure_ascii=False, indent=2)

        return f"""# タスク: スキルとツールの選択

## ユーザークエリ:
{query}

## コンテキスト:
```json
{context_text}
```

## 利用可能なスキル:
{skills_text}

## 利用可能なツール:
{tools_text}

## 目標:
クエリとコンテキストを分析し、このタスクを完了するために**実際に必要な**スキルとツールのみを選択してください。

## 選択基準:
1. **関連性**: クエリに直接関連するものだけを選択
2. **必要性**: 必須のものだけを選択（あると便利なものは除外）
3. **効率性**: 重複する機能を持つものは一つだけ選択
4. **優先順位**: 実行順序を考慮した選択

## 応答形式:
次のJSON形式で正確に応答してください:

```json
{{
  "selected_skills": ["skill_name_1", "skill_name_2"],
  "selected_tools": ["tool_name_1", "tool_name_2"],
  "reasoning": "選択した理由の簡単な説明",
  "priority_order": [
    {{"type": "skill", "name": "skill_name_1", "reason": "理由"}},
    {{"type": "tool", "name": "tool_name_1", "reason": "理由"}}
  ]
}}
```

**重要**: JSONのみを出力してください。他の説明やマークダウンは含めないでください。"""

    def _get_chinese_selection_prompt(
        self,
        query: str,
        context: Dict[str, Any],
        available_skills: List[Dict[str, Any]],
        available_tools: List[Dict[str, Any]]
    ) -> str:
        """Create Chinese selection prompt"""

        skills_text = self._format_skills_list(available_skills)
        tools_text = self._format_tools_list(available_tools)
        context_text = json.dumps(context, ensure_ascii=False, indent=2)

        return f"""# 任务: 选择技能和工具

## 用户查询:
{query}

## 上下文:
```json
{context_text}
```

## 可用技能:
{skills_text}

## 可用工具:
{tools_text}

## 目标:
分析查询和上下文，然后**仅选择实际需要的**技能和工具来完成此任务。

## 选择标准:
1. **相关性**: 仅选择与查询直接相关的项目
2. **必要性**: 仅选择必需的项目（排除"有更好"的项目）
3. **效率**: 如果多个项目具有重叠功能，只选择一个
4. **优先级**: 考虑执行顺序

## 响应格式:
请严格按照以下JSON格式响应:

```json
{{
  "selected_skills": ["skill_name_1", "skill_name_2"],
  "selected_tools": ["tool_name_1", "tool_name_2"],
  "reasoning": "选择这些的简要说明",
  "priority_order": [
    {{"type": "skill", "name": "skill_name_1", "reason": "原因"}},
    {{"type": "tool", "name": "tool_name_1", "reason": "原因"}}
  ]
}}
```

**重要**: 仅输出JSON。不要包含任何其他解释或markdown。"""

    def _format_skills_list(self, skills: List[Dict[str, Any]]) -> str:
        """Format skills list for prompt"""
        if not skills:
            return "None available"

        lines = []
        for skill in skills:
            capabilities = ", ".join(skill.get("capabilities", []))
            lines.append(
                f"- **{skill['name']}** ({skill['type']}): {skill['description']}\n"
                f"  Capabilities: {capabilities}"
            )
        return "\n".join(lines)

    def _format_tools_list(self, tools: List[Dict[str, Any]]) -> str:
        """Format tools list for prompt"""
        if not tools:
            return "None available"

        lines = []
        for tool in tools:
            tool_type = tool.get("type", "unknown")
            description = tool.get("description", "No description")
            capabilities = ", ".join(tool.get("capabilities", []))
            lines.append(
                f"- **{tool['name']}** ({tool_type}): {description}\n"
                f"  Capabilities: {capabilities}"
            )
        return "\n".join(lines)

    def _parse_selection(
        self,
        selection_text: str,
        available_skills: List[Dict[str, Any]],
        available_tools: List[Dict[str, Any]]
    ) -> SkillToolSelection:
        """Parse LLM response into SkillToolSelection

        Args:
            selection_text: LLM response text
            available_skills: List of available skills
            available_tools: List of available tools

        Returns:
            SkillToolSelection object
        """
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_text = selection_text
            if "```json" in json_text:
                json_text = json_text.split("```json")[1].split("```")[0]
            elif "```" in json_text:
                json_text = json_text.split("```")[1].split("```")[0]

            # Parse JSON
            data = json.loads(json_text.strip())

            # Validate selected skills and tools exist
            available_skill_names = {s["name"] for s in available_skills}
            available_tool_names = {t["name"] for t in available_tools}

            selected_skills = [
                s for s in data.get("selected_skills", [])
                if s in available_skill_names
            ]

            selected_tools = [
                t for t in data.get("selected_tools", [])
                if t in available_tool_names
            ]

            return SkillToolSelection(
                selected_skills=selected_skills,
                selected_tools=selected_tools,
                reasoning=data.get("reasoning", ""),
                priority_order=data.get("priority_order", [])
            )

        except Exception as e:
            logger.warning(f"[{self.name}] Failed to parse selection: {e}")
            logger.debug(f"[{self.name}] Selection text: {selection_text}")
            return self._create_fallback_selection_from_text(
                selection_text,
                available_skills,
                available_tools
            )

    def _create_fallback_selection(self, context: Dict[str, Any]) -> SkillToolSelection:
        """Create fallback selection based on context

        Args:
            context: Task context

        Returns:
            SkillToolSelection with basic selections
        """
        intent = context.get("intent", "")
        query_type = context.get("query_type", "")

        # Basic heuristic-based selection
        selected_skills = []
        selected_tools = []

        # Map intents to likely skills/tools
        if "research" in intent.lower() or "search" in query_type.lower():
            selected_tools.append("web_search")

        if "data" in intent.lower() or "analysis" in intent.lower():
            selected_tools.append("data_analysis")
            selected_skills.append("bigquery_skill")

        if "document" in intent.lower() or "pdf" in intent.lower():
            selected_skills.append("pdf_skill")

        return SkillToolSelection(
            selected_skills=selected_skills,
            selected_tools=selected_tools,
            reasoning=f"Fallback selection based on intent: {intent}",
            priority_order=[
                {"type": "tool", "name": t, "reason": "heuristic"}
                for t in selected_tools
            ] + [
                {"type": "skill", "name": s, "reason": "heuristic"}
                for s in selected_skills
            ]
        )

    def _create_fallback_selection_from_text(
        self,
        selection_text: str,
        available_skills: List[Dict[str, Any]],
        available_tools: List[Dict[str, Any]]
    ) -> SkillToolSelection:
        """Create fallback by parsing text for skill/tool names

        Args:
            selection_text: LLM response text
            available_skills: List of available skills
            available_tools: List of available tools

        Returns:
            SkillToolSelection with extracted selections
        """
        available_skill_names = {s["name"] for s in available_skills}
        available_tool_names = {t["name"] for t in available_tools}

        # Simple text search for names
        selected_skills = [
            name for name in available_skill_names
            if name in selection_text
        ]

        selected_tools = [
            name for name in available_tool_names
            if name in selection_text
        ]

        return SkillToolSelection(
            selected_skills=selected_skills,
            selected_tools=selected_tools,
            reasoning="Fallback: extracted from text",
            priority_order=[]
        )
