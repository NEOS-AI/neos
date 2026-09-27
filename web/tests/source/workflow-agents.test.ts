import assert from "node:assert/strict";
import test from "node:test";
import {
  applyGraphSubagentEvent,
  graphSubagentLine,
  workflowAgentTitle,
} from "@/lib/workflow-agents";
import type { NeosGraphSubagentEvent } from "@/lib/stream-types";

/**
 * 챗 워크플로우 카드의 이름과 서브에이전트 진행.
 *
 * 카드 헤더는 `title` 없이 `workflow-<agent_name>` 을 그대로 보여 줬다 --
 * 사람이 보는 것은 `workflow-query_analysis`, 설계 그래프 노드라면
 * `workflow-explore_web` 였다. 그리고 서브에이전트 노드가 몇 걸음 갔는지,
 * 끝났는지는 챗 스트림에 아예 오지 않았다(`neos:graph_subagent` 이전).
 */

const step = (steps: number): NeosGraphSubagentEvent => ({
  type: "neos:graph_subagent",
  node: "explore_web",
  label: "Investigating with a subagent",
  phase: "step",
  status: "running",
  steps,
  max_steps: 9,
});

test("a subagent event creates one entry per node and updates it in place", () => {
  const once = applyGraphSubagentEvent(undefined, step(1));
  const twice = applyGraphSubagentEvent(once, step(2));
  assert.equal(twice.length, 1);
  assert.equal(twice[0].steps, 2);
  // 이전 배열은 건드리지 않는다 -- 메타데이터는 새 참조로 갈아 끼운다.
  assert.equal(once[0].steps, 1);
});

test("a step reads as progress against the cap", () => {
  assert.equal(graphSubagentLine(step(2)), "서브에이전트 조사 중 · 2/9 걸음");
});

test("a completed fold says the report is unverified", () => {
  const line = graphSubagentLine({ ...step(3), phase: "folded", status: "completed" });
  assert.equal(line, "서브에이전트 완료 · 3 걸음 · 보고는 미검증");
});

test("a failed fold names the error", () => {
  const line = graphSubagentLine({
    ...step(1),
    phase: "folded",
    status: "failed",
    error_code: "subagent_advance_error: TimeoutError",
  });
  assert.equal(line, "서브에이전트 실패 · subagent_advance_error: TimeoutError");
});

test("a step-capped fold says it was stopped, not that it failed", () => {
  const line = graphSubagentLine({
    ...step(9),
    phase: "folded",
    status: "killed",
    exit_reason: "graph_step_cap",
  });
  assert.equal(line, "서브에이전트 중단 · 걸음 상한 9 도달");
});

test("titles prefer the subagent label, then known agents, then a readable name", () => {
  assert.equal(
    workflowAgentTitle("explore_web", {
      node: "explore_web",
      label: "Investigating with a subagent",
      phase: "step",
      status: "running",
      steps: 1,
    }),
    "Investigating with a subagent"
  );
  assert.equal(workflowAgentTitle("query_analysis"), "질의 분석");
  assert.equal(workflowAgentTitle("some_new_node"), "Some new node");
});
