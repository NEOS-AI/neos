// DOM 전역을 **먼저** 세운다. 부수효과 임포트라 biome 의 정렬이
// 건드리지 않는다 -- 이름 있는 임포트로만 두면 정렬이 컴포넌트 뒤로
// 밀어 버리고(실제로 그렇게 됐다) 순서 보장이 우연에 기댄다.
// 실제 렌더 경로의 순서는 `tests/render.tsx` 가 따로 지킨다.
import "../dom-setup";
import assert from "node:assert/strict";
import test from "node:test";
import { Tool, ToolContent, ToolHeader } from "../../components/elements/tool";
import { renderComponent } from "../render";

/**
 * 공유 `Tool` 카드의 구조 회귀.
 *
 * 이 파일이 생긴 이유는 한 줄짜리 결함 하나다: `ToolHeader` 의 셰브론이
 * `group-data-[state=open]:rotate-180` 을 쓰는데 `group` 조상이 없어
 * **앱 전체에서 한 번도 회전한 적이 없었다**(로드맵 §5.5 FE11-A). 형제인
 * `elements/task.tsx` 는 같은 자리에 `group` 을 갖고 있어 그쪽은 돈다.
 *
 * 순수 모듈로는 잡을 수 없는 종류다 -- 결함이 JSX 배선 자체에 있다.
 */

const card = (defaultOpen: boolean) => (
  <Tool defaultOpen={defaultOpen}>
    <ToolHeader
      state={"input-available" as never}
      title="테스트 카드"
      type={"workflow-test" as never}
    />
    <ToolContent>
      <div>본문</div>
    </ToolContent>
  </Tool>
);

test("셰브론 회전에 필요한 두 가지가 같은 엘리먼트에 있다", async () => {
  const host = await renderComponent(card(true));

  // Tailwind 의 `group-*` 는 조상의 `group` 클래스로 걸린다. 계산된 스타일이
  // 아니라 **이 두 가지의 공존**이 회전의 전부이므로 그것을 고정한다
  // (happy-dom 은 Tailwind 를 계산하지 않는다 -- 할 수 있는 최선이 아니라
  // 이 결함에 대해 정확히 옳은 단언이다).
  const trigger = host.querySelector("button");
  assert.ok(trigger, "트리거 버튼이 없다");
  assert.ok(
    trigger.classList.contains("group"),
    "트리거에 `group` 이 없다 -- 셰브론이 회전하지 않는다"
  );
  assert.equal(
    trigger.getAttribute("data-state"),
    "open",
    "`group-data-[state=open]` 이 읽을 속성이 트리거에 없다"
  );
});

test("닫힌 카드도 같은 자리에 상태를 싣는다", async () => {
  const host = await renderComponent(card(false));

  const trigger = host.querySelector("button");
  assert.ok(trigger?.classList.contains("group"));
  assert.equal(trigger?.getAttribute("data-state"), "closed");
});

test("접힌 카드는 본문을 마운트하지 않는다", async () => {
  // 이 성질에 라이브 영역 설계가 기대고 있다 -- 접힌 카드는 안내하지 않는다
  // (`deep-analysis-status.tsx` 의 주석). 기대는 것이 사실인지 고정해 둔다.
  const open = await renderComponent(card(true));
  const closed = await renderComponent(card(false));

  assert.ok(open.textContent?.includes("본문"));
  assert.ok(
    !closed.textContent?.includes("본문"),
    "닫힌 카드가 본문을 남기면 라이브 영역이 접힌 채로도 안내한다"
  );
});
