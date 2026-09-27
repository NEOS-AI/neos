import "../dom-setup";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { act } from "react";
import { DeepAnalysisStatus } from "../../components/deep-analysis-status";
import { renderComponent } from "../render";

/**
 * 실패한 run 의 **사람이 누르는** 재개.
 *
 * 감사 §4.2 재과금 사고는 두 가지가 겹친 것이었다: ① 재연결 때 **자동으로**
 * ② `POST /api/chat` 으로 워크플로우를 **통째로** 다시 돌렸다. 여기 있는 재개는
 * 둘 다 아니다 -- 버튼을 눌러야만 불리고, 원장이 이미 쓴 토큰을 기억하는 전용
 * `POST /api/v1/deep-analysis/{run_id}/resume` 을 부른다. 구독 경로(GET 전용)는
 * 그대로다(`deep-analysis-subscription.test.ts`).
 *
 * 그리고 재개가 동작하려면 "종결"이 **마지막** 종결이어야 한다. 재개된 run 의
 * 이력은 `job_failed → job_resumed → …` 이라, 첫 종결에서 멈추면 재생하는
 * 사람은 살아 있는 run 을 실패로 본다.
 */

const originalFetch = globalThis.fetch;

function sse(lines: string[]) {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        for (const line of lines) {
          controller.enqueue(encoder.encode(`data: ${line}\n\n`));
        }
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } }
  );
}

const RESUMED_HISTORY = [
  '{"seq":1,"type":"job_started","payload":{}}',
  '{"seq":2,"type":"job_failed","payload":{"error":"boom"}}',
  '{"seq":3,"type":"job_resumed","payload":{}}',
  '{"seq":4,"type":"job_completed","payload":{"report_markdown":"## 요약"}}',
];

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

test("a failure that was resumed is not the end of the replay", async () => {
  const outcomes: string[] = [];
  globalThis.fetch = (() => Promise.resolve(sse(RESUMED_HISTORY))) as typeof fetch;
  try {
    const host = await renderComponent(
      <DeepAnalysisStatus
        deepAnalysis={{ run_id: "run-1", status: "running" }}
        onCompleted={() => outcomes.push("completed")}
        onFailed={() => outcomes.push("failed")}
      />
    );
    await flush();

    assert.deepEqual(outcomes, ["completed"]);
    assert.ok(host.textContent?.includes("완료"));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("only a failed run offers the resume button", async () => {
  for (const status of ["completed", "running"] as const) {
    globalThis.fetch = (() => new Promise(() => undefined)) as typeof fetch;
    try {
      const host = await renderComponent(
        <DeepAnalysisStatus deepAnalysis={{ run_id: "run-1", status }} />
      );
      assert.equal(
        host.querySelector('[aria-label="Resume deep analysis"]'),
        null,
        `${status} run must not offer resume`
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  }

  const host = await renderComponent(
    <DeepAnalysisStatus deepAnalysis={{ run_id: "run-1", status: "failed" }} />
  );
  assert.ok(host.querySelector('[aria-label="Resume deep analysis"]'));
});

test("resuming posts once, then re-subscribes with a GET and follows the run", async () => {
  const calls: Array<{ url: string; method: string }> = [];
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method });
    if (method === "POST") {
      return Promise.resolve(
        Response.json({ run_id: "run-1", status: "accepted" }, { status: 202 })
      );
    }
    return Promise.resolve(sse(RESUMED_HISTORY));
  }) as typeof fetch;
  try {
    const host = await renderComponent(
      <DeepAnalysisStatus deepAnalysis={{ run_id: "run-1", status: "failed" }} />
    );
    // 종결된 run 은 버튼을 누르기 전에는 아무것도 부르지 않는다.
    assert.deepEqual(calls, []);

    const button = host.querySelector(
      '[aria-label="Resume deep analysis"]'
    ) as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    await flush();

    assert.deepEqual(calls, [
      { url: "/api/deep-analysis/run-1/resume", method: "POST" },
      { url: "/api/deep-analysis/run-1/events?after=0", method: "GET" },
    ]);
    assert.ok(host.textContent?.includes("재개됨"));
    assert.ok(host.textContent?.includes("완료"));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("a refused resume says why and keeps the button", async () => {
  globalThis.fetch = (() =>
    Promise.resolve(
      Response.json({ error: "run is 'completed' and cannot be resumed" }, { status: 409 })
    )) as typeof fetch;
  try {
    const host = await renderComponent(
      <DeepAnalysisStatus deepAnalysis={{ run_id: "run-1", status: "failed" }} />
    );
    const button = host.querySelector(
      '[aria-label="Resume deep analysis"]'
    ) as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    await flush();

    assert.ok(host.textContent?.includes("cannot be resumed"));
    assert.ok(host.querySelector('[aria-label="Resume deep analysis"]'));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("the resume call has exactly one caller and it is not the subscription", () => {
  // 재개 함수를 구독 훅이나 재부착 효과가 부르기 시작하면 '자동 재개'가 된다.
  const importers: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (name === "node_modules" || name.startsWith(".")) {
        continue;
      }
      if (statSync(full).isDirectory()) {
        walk(full);
      } else if (
        /\.tsx?$/.test(name) &&
        !full.startsWith("tests") &&
        readFileSync(full, "utf8").includes("resumeDeepAnalysis(")
      ) {
        importers.push(full);
      }
    }
  };
  for (const dir of ["app", "components", "hooks", "lib", "features"]) {
    walk(dir);
  }
  assert.deepEqual(importers.sort(), [
    "components/deep-analysis-status.tsx",
    "lib/deep-analysis/resume.ts",
  ]);
});

test("the resume BFF proxies exactly the backend route that exists", () => {
  const bff = readFileSync("app/(chat)/api/deep-analysis/[runId]/resume/route.ts", "utf8");
  const backend = readFileSync("../neos/api/handlers/deep_analysis_handlers.py", "utf8");

  assert.match(bff, /export async function POST\(/);
  assert.doesNotMatch(bff, /export async function GET\(/);
  assert.match(bff, /\/api\/v1\/deep-analysis\/\$\{[^}]+\}\/resume/);
  assert.match(backend, /"\/deep-analysis\/\{run_id\}\/resume"/);
});
