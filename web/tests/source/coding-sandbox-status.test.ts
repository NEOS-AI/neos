import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  initialSandboxStatus,
  markSandboxStatusStale,
  reduceSandboxStatus,
  sandboxStatusCopy,
} from "../../features/coding/sandbox/sandbox-status-store";

/**
 * 이 스위트가 지키는 것은 하나다: **샌드박스가 아플 때 사용자의 작업이
 * 사라지지 않는다.**
 *
 * 실행 표면(제출·터미널 생성)은 막되, 읽기(파일·diff)와 작성 중인 초안은
 * 그대로 둔다. 그리고 막는 근거는 **서버가 보낸 불리언**이지 상태 이름을
 * 프론트에서 다시 해석한 결과가 아니다 -- 두 번 해석하면 백엔드가 정책을
 * 바꿔도 화면이 따라오지 않는다.
 */

test("provider recovery preserves draft and blocks execution surfaces", () => {
  const state = reduceSandboxStatus(initialSandboxStatus(), {
    state: "provider_recovery_pending",
    can_run: false,
    can_open_terminal: false,
    recovered_from_checkpoint: false,
    updated_at: "2026-07-25T00:00:00Z",
  });

  assert.equal(state.canRun, false);
  assert.equal(state.canOpenTerminal, false);
  assert.equal(state.copy, "Provider recovery pending");
});

test("gating follows the server booleans, not the state name", () => {
  // 상태 이름은 'ready' 인데 서버가 실행을 막았다면 막힌 것이다. 이름으로
  // 다시 판정하면 백엔드 정책 변경이 화면에 반영되지 않는다.
  const state = reduceSandboxStatus(initialSandboxStatus(), {
    state: "ready",
    can_run: false,
    can_open_terminal: false,
    recovered_from_checkpoint: false,
    updated_at: "2026-07-25T00:00:00Z",
  });

  assert.equal(state.canRun, false);
  assert.equal(state.canOpenTerminal, false);
});

test("every projected state has copy and none of it names a provider", () => {
  const states = [
    "preparing",
    "ready",
    "suspended",
    "provider_recovery_pending",
    "operator_recovery_required",
    "cleaning_up",
    "cleaned",
  ] as const;

  for (const state of states) {
    const copy = sandboxStatusCopy(state);
    assert.ok(copy.length > 0, `missing copy for ${state}`);
    // provider 이름이 문구로 새면 백엔드가 지운 것을 프론트가 되살리는 셈이다.
    assert.doesNotMatch(copy, /docker|e2b|modal|kubernetes/i);
  }
});

test("an unknown state does not silently read as ready", () => {
  // 백엔드가 상태를 추가했는데 프론트가 모를 때, 기본이 '실행 가능'이면
  // 정리 중인 샌드박스에서 명령이 도는 사고가 조용히 열린다.
  const state = reduceSandboxStatus(initialSandboxStatus(), {
    state: "some_future_state" as never,
    can_run: true,
    can_open_terminal: true,
    recovered_from_checkpoint: false,
    updated_at: "2026-07-25T00:00:00Z",
  });

  assert.equal(state.canRun, false);
  assert.equal(state.canOpenTerminal, false);
  assert.equal(state.copy, "Sandbox status unavailable");
});

test("a network error keeps the last status and marks it stale", () => {
  const ready = reduceSandboxStatus(initialSandboxStatus(), {
    state: "ready",
    can_run: true,
    can_open_terminal: true,
    recovered_from_checkpoint: false,
    updated_at: "2026-07-25T00:00:00Z",
  });

  const stale = markSandboxStatusStale(ready);

  // 마지막으로 알던 것을 지우지 않는다 -- 지우면 사용자는 방금까지 되던 것이
  // 왜 안 되는지 알 수 없고, 화면이 깜빡이며 실행 버튼이 요동친다.
  assert.equal(stale.state, "ready");
  assert.equal(stale.copy, sandboxStatusCopy("ready"));
  assert.equal(stale.stale, true);
  // stale 은 **경고**이지 차단이 아니다. 네트워크가 잠깐 끊겼다고 실행을
  // 막으면 그것 자체가 사용자에게는 고장이다.
  assert.equal(stale.canRun, true);
});

test("a fresh status clears the stale marker", () => {
  const stale = markSandboxStatusStale(
    reduceSandboxStatus(initialSandboxStatus(), {
      state: "ready",
      can_run: true,
      can_open_terminal: true,
      recovered_from_checkpoint: false,
      updated_at: "2026-07-25T00:00:00Z",
    })
  );

  const fresh = reduceSandboxStatus(stale, {
    state: "ready",
    can_run: true,
    can_open_terminal: true,
    recovered_from_checkpoint: false,
    updated_at: "2026-07-25T00:00:05Z",
  });

  assert.equal(fresh.stale, false);
});

test("the restored notice is announced once, not on every poll", () => {
  const first = reduceSandboxStatus(initialSandboxStatus(), {
    state: "ready",
    can_run: true,
    can_open_terminal: true,
    recovered_from_checkpoint: true,
    updated_at: "2026-07-25T00:00:00Z",
  });
  const second = reduceSandboxStatus(first, {
    state: "ready",
    can_run: true,
    can_open_terminal: true,
    recovered_from_checkpoint: true,
    updated_at: "2026-07-25T00:00:05Z",
  });

  assert.equal(first.announceRestored, true);
  assert.equal(second.announceRestored, false);
});

test("the initial status blocks execution until the server answers", () => {
  const initial = initialSandboxStatus();

  assert.equal(initial.canRun, false);
  assert.equal(initial.canOpenTerminal, false);
});

test("the client type accepts no provider or internal identifier", () => {
  // 산문이 아니라 **필드 선언**을 본다. `provider_recovery_pending` 은 정당한
  // 상태 *값*이고, 금지하려는 것은 `provider:` 같은 *속성*이다 -- 단어를
  // 통째로 막으면 그 구별이 사라져 테스트가 무엇을 지키는지 흐려진다.
  const source = readFileSync("features/coding/sandbox/types.ts", "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");

  for (const forbidden of [
    "provider",
    "region",
    "allocation_id",
    "provider_ref",
    "ownership_digest",
    "error_code",
    "tenant_id",
  ]) {
    assert.doesNotMatch(
      source,
      new RegExp(`\\b${forbidden}\\s*[?]?\\s*:`, "i"),
      `${forbidden} must not be a field of the browser contract`
    );
  }
});

test("the sandbox-status BFF route is GET only", () => {
  const source = readFileSync(
    "app/(code)/api/coding/tasks/[taskId]/sandbox-status/route.ts",
    "utf8"
  );

  assert.match(source, /export async function GET/);
  // POST 를 두면 브라우저가 할당을 다시 만들 수 있는 경로가 생긴다 --
  // deep-analysis 프록시가 재과금 사고 뒤에 세운 규율과 같다.
  assert.doesNotMatch(source, /export async function (POST|PUT|DELETE|PATCH)/);
});

test("the status component announces politely and shows no provider detail", () => {
  const source = readFileSync(
    "features/coding/components/coding-sandbox-status.tsx",
    "utf8"
  );

  assert.match(source, /aria-live="polite"/);
  assert.doesNotMatch(source, /provider_ref|allocation_id|error_code/);
});

test("the terminal disables creation from the server boolean", () => {
  const source = readFileSync(
    "features/coding/components/workspace/coding-terminal.tsx",
    "utf8"
  );

  assert.match(source, /canOpenTerminal/);
});

test("the workspace gates the composer but keeps file and diff reading", () => {
  const source = readFileSync(
    "features/coding/components/coding-task-workspace.tsx",
    "utf8"
  );

  assert.match(source, /useSandboxStatus/);
  assert.match(source, /canRun/);
  // 독은 파일·diff 읽기를 계속 제공한다 -- 실행만 막고 조회는 막지 않는다.
  assert.match(source, /CodingWorkspaceDock/);
});

test("the browser vocabulary cannot drift from the backend projection", () => {
  /*
   * 상태 어휘가 **두 언어에 각각** 구현돼 있다. 로드맵 FE6이 이름 붙인 바로
   * 그 위험이다 -- 갈라지면 백엔드가 새 상태를 내보내는데 프론트는 그것을
   * 모르는 채로 렌더한다(그리고 규칙 2 때문에 실행이 조용히 막힌다).
   *
   * 그래서 주석으로 "백엔드와 같아야 한다"고 적는 대신 기계가 대조한다.
   */
  const python = readFileSync(
    "../neos/coding/managed/projection.py",
    "utf8"
  );
  const backendStates = [
    ...python.matchAll(/^\s{4}[A-Z_]+ = "([a-z_]+)"$/gm),
  ].map((match) => match[1]);
  const browserStates = [
    // 마지막 멤버는 `| "cleaned";` 처럼 세미콜론으로 끝난다 -- 그것을 놓치면
    // 이 테스트가 조용히 한 개 적게 비교한다(처음 쓸 때 실제로 그랬다).
    ...readFileSync("features/coding/sandbox/types.ts", "utf8").matchAll(
      /^\s*\| "([a-z_]+)";?$/gm
    ),
  ].map((match) => match[1]);

  assert.ok(backendStates.length > 0, "could not read the backend enum");
  assert.equal(
    browserStates.length,
    7,
    "the browser union should have all seven states"
  );
  assert.deepEqual(
    [...browserStates].sort(),
    [...backendStates].sort(),
    "OwnerSandboxState and CodingSandboxState must stay identical"
  );
});

test("the BFF proxies exactly the backend route that exists", () => {
  const bff = readFileSync(
    "app/(code)/api/coding/tasks/[taskId]/sandbox-status/route.ts",
    "utf8"
  );
  const backend = readFileSync(
    "../neos/api/handlers/coding_handlers.py",
    "utf8"
  );

  assert.match(bff, /\/api\/v1\/coding\/tasks\/\$\{[^}]+\}\/sandbox-status/);
  assert.match(backend, /"\/tasks\/\{task_id\}\/sandbox-status"/);
});

test("polling does not infer provider health from the websocket", () => {
  const source = readFileSync(
    "features/coding/sandbox/use-sandbox-status.ts",
    "utf8"
  );

  // 소켓이 끊겼다고 provider 가 아프다고 결론 내리면, 네트워크 문제로
  // 멀쩡한 샌드박스가 죽은 것처럼 보인다.
  assert.doesNotMatch(source, /connection === "(unauthorized|not_found)"/);
  assert.match(source, /5000|POLL_INTERVAL_MS/);
});
