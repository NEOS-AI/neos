"""Skill-based Tool Selector - LLM-powered intelligent selection of skills and tools"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import json
import logging

import jsonschema
from langchain_core.messages import HumanMessage

from neos.config.settings import settings
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillCall:
    """셀렉터가 고른 스킬 하나와 그 인자 (spec 2026-10-11 §3.2)."""

    name: str
    params: Dict[str, Any]
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "params": dict(self.params), "reason": self.reason}


@dataclass
class SkillToolSelection:
    """Skill and Tool selection result

    `skill_calls` 가 정본이다. 비어 있지 않으면 `selected_skills` 는 그 이름에서
    파생한다 -- 승인 정책은 `selected_skills` 를, 실행 노드는 `skill_calls` 를 보므로
    둘이 어긋나면 승인을 우회한다.
    """
    selected_skills: List[str]
    selected_tools: List[str]
    reasoning: str
    priority_order: List[Dict[str, str]]
    skill_calls: List[SkillCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.skill_calls:
            self.selected_skills = [call.name for call in self.skill_calls]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "selected_skills": self.selected_skills,
            "selected_tools": self.selected_tools,
            "reasoning": self.reasoning,
            "priority_order": self.priority_order,
            "skill_calls": [call.to_dict() for call in self.skill_calls],
        }


_LANGUAGE_NAMES = {"ko": "Korean", "en": "English", "ja": "Japanese", "zh": "Chinese"}

_SELECTION_PROMPT = """# Task: Select skills and tools

## User query
{query}

## Context
```json
{context}
```

## Available skills
Only these skills can be executed. Each lists the parameters it accepts.
{skills}

## Available tools
{tools}

## Goal
Select ONLY the skills and tools that are actually necessary for this query.
1. Relevance: directly related to the query
2. Necessity: leave out "nice to have"
3. Efficiency: when two overlap, pick one
Choose at most {max_skills} skills. Fill `params` for each skill using only the parameters
listed for it. When a skill lists `query`, rewrite the user query as a search query for that source.

## Response format
Respond with exactly this JSON:
```json
{{
  "skill_calls": [
    {{"name": "skill_name", "params": {{"query": "..."}}, "reason": "..."}}
  ],
  "selected_tools": ["tool_name"],
  "reasoning": "short explanation",
  "priority_order": [{{"type": "skill", "name": "skill_name", "reason": "..."}}]
}}
```
Write `reasoning` and every `reason` in {language}. Output ONLY the JSON."""


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
        self._skill_manager = None
        self._skill_registry = None
        self._tool_selector = None

    @property
    def skill_manager(self):
        """Lazy load SkillManager"""
        if self._skill_manager is None:
            from neos.skills.manager.skill_manager import skill_manager
            self._skill_manager = skill_manager
        return self._skill_manager

    @property
    def skill_registry(self):
        """Lazy load SkillRegistry"""
        if self._skill_registry is None:
            self._skill_registry = self.skill_manager.registry
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
        detected_language: str = "ko",
        fallback_query: Optional[str] = None,
    ) -> SkillToolSelection:
        """Select necessary skills and tools based on query and context

        Args:
            query: User query or task description
            context: Additional context (intent, query_type, etc.)
            session_id: Session ID for tracking
            user_id: User ID for tracking
            detected_language: Detected language (ko, en, ja, zh)
            fallback_query: params 검증 실패 시 쓸 질의 (None 이면 query)

        Returns:
            SkillToolSelection object with selected skills, tools, and reasoning
        """
        logger.info(f"[{self.name}] Selecting skills and tools for query: {query[:100]}...")

        try:
            # Get available skills and tools
            available_skills = self._get_available_skills()
            available_tools = self._get_available_tools()

            # Create tracked LLM for dataset collection
            base_llm = create_llm(temperature=0.2, max_tokens=8000)

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

            max_skills = settings.config.workflow.skill_execution.max_skills_per_turn
            prompt = self._build_selection_prompt(
                query, context, available_skills, available_tools, detected_language, max_skills
            )

            # Invoke LLM for selection
            logger.info(f"[{self.name}] Invoking LLM for skill/tool selection (language={detected_language})")
            response = await tracked_llm.ainvoke([HumanMessage(content=prompt)])

            # Extract text from response (handles both string and list content when thinking blocks are enabled)
            from neos.utils.llm_wrapper import extract_text_from_response
            selection_text = extract_text_from_response(response).strip()

            # Parse the selection
            selection = self._parse_selection(
                selection_text,
                available_skills,
                available_tools,
                fallback_query=fallback_query or query,
                max_skills=max_skills,
            )

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
        """자동 실행 후보 (spec §3.1): `auto_execute` 이고 초기화가 실패한 적 없는 스킬."""
        unavailable = self.skill_manager.known_unavailable()
        skills = []
        for skill_info in self.skill_registry.list_skills():
            if not skill_info.auto_execute or skill_info.name in unavailable:
                continue
            try:
                schema = skill_info.skill_class.get_input_schema()
            except Exception:  # noqa: BLE001 -- 스키마 없는 스킬도 이름으로는 고를 수 있다
                schema = {}
            skills.append({
                "name": skill_info.name,
                "type": skill_info.skill_type.value,
                "description": skill_info.description,
                "capabilities": skill_info.capabilities,
                "version": skill_info.version,
                "input_schema": schema,
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

    def _build_selection_prompt(
        self,
        query: str,
        context: Dict[str, Any],
        available_skills: List[Dict[str, Any]],
        available_tools: List[Dict[str, Any]],
        detected_language: str,
        max_skills: int,
    ) -> str:
        """언어별 사본 대신 템플릿 하나 + 응답 언어 지시 (spec §3.6)."""
        return _SELECTION_PROMPT.format(
            query=query,
            context=json.dumps(context, ensure_ascii=False, indent=2, default=str),
            skills=self._format_skills_list(available_skills),
            tools=self._format_tools_list(available_tools),
            max_skills=max_skills,
            language=_LANGUAGE_NAMES.get(detected_language, "English"),
        )

    def _format_skills_list(self, skills: List[Dict[str, Any]]) -> str:
        """Format skills list for prompt"""
        if not skills:
            return "None available"

        lines = []
        for skill in skills:
            capabilities = ", ".join(skill.get("capabilities", []))
            skill_info = (
                f"- **{skill['name']}** ({skill['type']}): {skill['description']}\n"
                f"  Capabilities: {capabilities}"
            )

            # Add allowed_tools if available
            if skill.get("allowed_tools"):
                skill_info += f"\n  Required Tools: {skill['allowed_tools']}"

            params = (skill.get("input_schema") or {}).get("properties") or {}
            if params:
                required = set((skill.get("input_schema") or {}).get("required") or [])
                rendered = ", ".join(
                    f"{key} ({spec.get('type', 'any')}{', required' if key in required else ''})"
                    + (f": {spec['description']}" if spec.get("description") else "")
                    for key, spec in params.items()
                )
                skill_info += f"\n  Params: {rendered}"

            lines.append(skill_info)
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
        available_tools: List[Dict[str, Any]],
        *,
        fallback_query: str = "",
        max_skills: int = 3,
    ) -> SkillToolSelection:
        """LLM 응답 → `SkillToolSelection` (spec §3.3).

        후보 밖 이름은 버리고, 중복은 첫 번째만, `max_skills` 에서 자른다. params 는
        스키마에 없는 키를 떼고 검증하며, 실패하면 버리지 않고 질의로 대체한다.
        """
        try:
            json_text = selection_text
            if "```json" in json_text:
                json_text = json_text.split("```json")[1].split("```")[0]
            elif "```" in json_text:
                json_text = json_text.split("```")[1].split("```")[0]
            data = json.loads(json_text.strip())
            if not isinstance(data, dict):
                raise ValueError("selection is not a JSON object")
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to parse selection: {e}")
            logger.debug(f"[{self.name}] Selection text: {selection_text}")
            return self._create_fallback_selection_from_text(selection_text, available_skills, available_tools)

        by_name = {skill["name"]: skill for skill in available_skills}
        raw_calls = data.get("skill_calls")
        if raw_calls is None:
            # 옛 형식(이름 목록)도 받는다 -- 인자는 대체값이다.
            raw_calls = [{"name": name} for name in data.get("selected_skills", []) or []]

        calls: List[SkillCall] = []
        for raw in raw_calls if isinstance(raw_calls, list) else []:
            if not isinstance(raw, dict):
                continue
            name = raw.get("name")
            if name not in by_name or any(call.name == name for call in calls):
                continue
            schema = by_name[name].get("input_schema") or {}
            params = _validated_params(raw.get("params"), schema, fallback_query)
            calls.append(SkillCall(name, params, str(raw.get("reason", "") or "")))
            if len(calls) >= max_skills:
                break

        available_tool_names = {t["name"] for t in available_tools}
        return SkillToolSelection(
            selected_skills=[call.name for call in calls],
            selected_tools=[t for t in data.get("selected_tools", []) or [] if t in available_tool_names],
            reasoning=data.get("reasoning", ""),
            priority_order=data.get("priority_order", []),
            skill_calls=calls,
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
        available_tool_names = {t["name"] for t in available_tools}
        selected_tools = [name for name in available_tool_names if name in selection_text]
        # 스킬은 고르지 않는다 -- 실행 노드가 생긴 뒤로 "본문에 이름이 보인다" 는
        # 실행 근거가 될 수 없다 (spec §3.6).
        return SkillToolSelection(
            selected_skills=[],
            selected_tools=selected_tools,
            reasoning="Fallback: extracted tools from text",
            priority_order=[],
        )


def _validated_params(raw: Any, schema: Dict[str, Any], fallback_query: str) -> Dict[str, Any]:
    properties = schema.get("properties") or {}
    fallback = {"query": fallback_query} if fallback_query and "query" in properties else {}
    if not isinstance(raw, dict):
        return fallback
    params = {key: value for key, value in raw.items() if key in properties}
    try:
        jsonschema.validate(params, schema)
    except jsonschema.ValidationError:
        return fallback
    return params
