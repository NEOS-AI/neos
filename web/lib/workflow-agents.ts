import type { NeosGraphSubagentEvent } from "@/lib/stream-types";
import type { GraphSubagentView } from "@/lib/types";

/**
 * 챗 워크플로우 카드(`message.tsx`)의 이름과 서브에이전트 진행 문구.
 *
 * 카드 헤더는 `title` 없이 `workflow-<agent_name>` 을 그대로 보여 줬다. 백엔드
 * `map_node_to_agent` 는 레거시 노드 여덟만 id 로 바꾸고 나머지(설계 그래프
 * 노드 등)는 노드 이름을 그대로 흘린다 -- 그래서 여기서 사람이 읽을 이름을 정한다.
 */

/** 백엔드 `chat_handlers.map_node_to_agent` 가 내는 id → 화면 이름. */
const KNOWN_AGENTS: Record<string, string> = {
  query_analysis: "질의 분석",
  tool_selection: "도구 선택",
  knowledge_search: "지식 검색",
  data_analysis: "데이터 분석",
  content_generation: "콘텐츠 생성",
  result_integration: "결과 통합",
  quality_check: "품질 검증",
  response_generation: "응답 생성",
};

function humanize(name: string): string {
  const words = name.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : name;
}

/** 서브에이전트 라벨(백엔드 템플릿이 정한 것) → 알려진 에이전트 → 읽을 수 있는 이름. */
export function workflowAgentTitle(
  agentName: string,
  subagent?: GraphSubagentView
): string {
  return subagent?.label || KNOWN_AGENTS[agentName] || humanize(agentName);
}

/** 노드별로 한 줄. 새 배열을 돌려준다(메타데이터 참조를 갈아 끼우도록). */
export function applyGraphSubagentEvent(
  current: GraphSubagentView[] | undefined,
  event: NeosGraphSubagentEvent
): GraphSubagentView[] {
  const { type: _type, ...view } = event;
  const rest = (current ?? []).filter((entry) => entry.node !== event.node);
  return [...rest, view];
}

export function graphSubagentLine(view: GraphSubagentView): string {
  if (view.phase === "step") {
    const cap = view.max_steps ? `/${view.max_steps}` : "";
    return `서브에이전트 조사 중 · ${view.steps}${cap} 걸음`;
  }
  if (view.status === "completed") {
    // 보고서는 검증된 클레임이 아니라 검색 결과로만 쓰인다 -- 그 사실을 말한다.
    return `서브에이전트 완료 · ${view.steps} 걸음 · 보고는 미검증`;
  }
  if (view.exit_reason === "graph_step_cap") {
    return `서브에이전트 중단 · 걸음 상한 ${view.steps} 도달`;
  }
  if (view.status === "failed") {
    return `서브에이전트 실패 · ${view.error_code || view.exit_reason || "원인 미상"}`;
  }
  return `서브에이전트 ${view.status} · ${view.steps} 걸음`;
}
