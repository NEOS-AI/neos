import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import {
  classifySubscriptionError,
  DEEP_ANALYSIS_EVENTS_PROXY_BASE,
  deepAnalysisEventsPath,
  nextCursor,
  reconnectDelayMs,
  runIdFromEventsUrl,
  shouldResubscribe,
} from "../../lib/deep-analysis/subscription";

const WEB_ROOT = path.resolve(import.meta.dirname, "../..");
const read = (relative: string) =>
  readFileSync(path.join(WEB_ROOT, relative), "utf8");

// 정규식은 모듈 최상위에 둔다 (repo 관례 — `coding-stream-client.test.ts` 참조).
const AFTER_ZERO = /after=0$/;
const COMMENTS = /\/\*[\s\S]*?\*\/|\/\/.*$/gm;
const POST_METHOD = /method\s*:\s*["']POST["']/i;
const SUBMIT_CALL = /\/deep-analysis["'`]\s*,?\s*\{/;
const FETCH_CALL = /fetch\(/g;
const FETCH_EVENTS_PATH = /fetch\(\s*deepAnalysisEventsPath\(/;
const EVENTS_PATH_WITH_CURSOR =
  /deepAnalysisEventsPath\(\s*activeRunId\s*,\s*cursor\s*\)/;
const CURSOR_ADVANCE = /cursor = nextCursor\(cursor, event\.seq\)/;
const EXPORT_GET = /export async function GET\(/;
const EXPORT_POST = /export async function POST\(/;
const EXPORT_PUT = /export async function PUT\(/;
const EXPORT_DELETE = /export async function DELETE\(/;
const CALL_BACKEND = /callBackendAPI/;
const BACKEND_EVENTS_PATH = /\/api\/v1\/deep-analysis\//;
const READ_ACTIVE_RUN = /readActiveRun\(id\)/;

const stripComments = (source: string) => source.replace(COMMENTS, "");

test("이벤트 경로는 커서를 쿼리로 싣는다", () => {
  assert.equal(
    deepAnalysisEventsPath("run-1"),
    "/api/deep-analysis/run-1/events?after=0"
  );
  assert.equal(
    deepAnalysisEventsPath("run-1", 42),
    "/api/deep-analysis/run-1/events?after=42"
  );
});

test("run_id는 경로 인코딩된다", () => {
  assert.equal(
    deepAnalysisEventsPath("a/b?c", 1),
    "/api/deep-analysis/a%2Fb%3Fc/events?after=1"
  );
});

test("손상된 커서는 0(전체 재생)으로 떨어진다", () => {
  assert.match(deepAnalysisEventsPath("r", Number.NaN), AFTER_ZERO);
  assert.match(deepAnalysisEventsPath("r", -5), AFTER_ZERO);
  assert.match(deepAnalysisEventsPath("r", 1.5), AFTER_ZERO);
});

test("백엔드 events_url에서 run_id를 뽑는다", () => {
  assert.equal(
    runIdFromEventsUrl("/api/v1/deep-analysis/run-abc/events"),
    "run-abc"
  );
  assert.equal(
    runIdFromEventsUrl(
      "https://api.example.com/api/v1/deep-analysis/r1/events?after=3"
    ),
    "r1"
  );
  assert.equal(runIdFromEventsUrl("/api/v1/something/else"), null);
});

test("커서는 단조 최대값만 취한다", () => {
  assert.equal(nextCursor(5, 6), 6);
  assert.equal(nextCursor(5, 5), 5);
  assert.equal(nextCursor(5, 4), 5);
  // 연속이 아니어도 전진한다 (seq는 전역 PK라 구멍이 정상이다).
  assert.equal(nextCursor(5, 900), 900);
  assert.equal(nextCursor(5, Number.NaN), 5);
});

test("4xx는 재시도하지 않고 429/5xx/네트워크만 재시도한다", () => {
  assert.equal(classifySubscriptionError(401), "terminal");
  assert.equal(classifySubscriptionError(403), "terminal");
  assert.equal(classifySubscriptionError(404), "terminal");
  assert.equal(classifySubscriptionError(429), "retry");
  assert.equal(classifySubscriptionError(500), "retry");
  assert.equal(classifySubscriptionError(503), "retry");
  assert.equal(classifySubscriptionError(undefined), "retry");
});

test("재연결 백오프는 지수적이고 상한이 있다", () => {
  assert.equal(
    reconnectDelayMs(0, () => 0),
    500
  );
  assert.equal(
    reconnectDelayMs(1, () => 0),
    1000
  );
  assert.equal(
    reconnectDelayMs(10, () => 0),
    15_000
  );
});

test("종결·정리·terminal 에러에서는 재구독하지 않는다", () => {
  assert.equal(
    shouldResubscribe({
      settled: false,
      disposed: false,
      terminalError: false,
    }),
    true
  );
  assert.equal(
    shouldResubscribe({ settled: true, disposed: false, terminalError: false }),
    false
  );
  assert.equal(
    shouldResubscribe({ settled: false, disposed: true, terminalError: false }),
    false
  );
  assert.equal(
    shouldResubscribe({ settled: false, disposed: false, terminalError: true }),
    false
  );
});

// ---------------------------------------------------------------------------
// 회귀 고정 (감사 §4.2): 재접속은 **재구독**이지 **재실행**이 아니다.
//
// `use-auto-resume.ts`의 "재개"가 실은 `POST /api/chat` 재실행이라 워크플로우가
// 재과금됐던 사고가 있었다. deep_analysis 재접속에서 같은 일이 벌어지지
// 않도록, 구독 경로에 제출 수단이 존재하지 않음을 소스 수준에서 못박는다.
// ---------------------------------------------------------------------------

test("구독 모듈에는 제출 경로가 존재하지 않는다", () => {
  const source = read("lib/deep-analysis/subscription.ts");
  const code = stripComments(source);

  assert.equal(POST_METHOD.test(code), false);
  assert.equal(code.includes("/api/chat"), false);
  assert.equal(SUBMIT_CALL.test(code), false);
  assert.equal(code.includes("sendMessage"), false);
  // 유일하게 만들어내는 경로는 GET 이벤트 경로다.
  assert.ok(DEEP_ANALYSIS_EVENTS_PROXY_BASE.startsWith("/api/deep-analysis"));
});

test("구독 훅은 커서를 실은 GET만 호출한다", () => {
  const source = read("hooks/use-deep-analysis-stream.ts");
  const code = stripComments(source);

  // fetch는 정확히 한 번, 그리고 인자는 이벤트 경로 빌더다.
  const fetches = code.match(FETCH_CALL) ?? [];
  assert.equal(fetches.length, 1, "구독 경로는 fetch 한 곳뿐이어야 한다");
  assert.match(code, FETCH_EVENTS_PATH);

  // 제출로 이어질 수 있는 어떤 흔적도 없어야 한다.
  assert.equal(POST_METHOD.test(code), false, "POST 금지");
  assert.equal(code.includes("/api/chat"), false, "챗 재실행 금지");
  assert.equal(code.includes("sendMessage"), false);
  assert.equal(code.includes("/resume"), false, "job 재제출 API 호출 금지");

  // 커서가 요청에 실제로 실린다.
  assert.match(code, EVENTS_PATH_WITH_CURSOR);
  assert.match(code, CURSOR_ADVANCE);
});

test("이벤트 프록시 라우트는 GET만 노출한다", () => {
  const source = read("app/(chat)/api/deep-analysis/[runId]/events/route.ts");
  const code = stripComments(source);

  assert.match(code, EXPORT_GET);
  assert.equal(EXPORT_POST.test(code), false);
  assert.equal(EXPORT_PUT.test(code), false);
  assert.equal(EXPORT_DELETE.test(code), false);
  // 인증은 기존 백엔드 호출과 같은 경로를 탄다.
  assert.match(code, CALL_BACKEND);
  assert.match(code, BACKEND_EVENTS_PATH);
});

test("새로고침 재부착 경로가 재실행을 부르지 않는다", () => {
  const source = read("hooks/use-chat-stream.ts");
  const code = stripComments(source);

  // 재부착 효과는 readActiveRun → setMessages(메타데이터 부착)까지다.
  assert.match(code, READ_ACTIVE_RUN);
  const effect = code.slice(
    code.indexOf("readActiveRun(id)"),
    code.indexOf("const processStream")
  );
  assert.ok(effect.length > 0, "재부착 효과를 찾지 못했다");
  assert.equal(effect.includes("sendMessage"), false);
  assert.equal(effect.includes("fetch("), false);
  assert.equal(effect.includes("/api/chat"), false);

  // resumeStream은 여전히 no-op이어야 한다 (감사 §4.2 차단 조치 유지).
  const resumeStart = code.indexOf("const resumeStream");
  const resume = code.slice(resumeStart, code.indexOf("return {", resumeStart));
  assert.ok(resume.length > 0, "resumeStream을 찾지 못했다");
  assert.equal(resume.includes("sendMessage("), false);
  assert.equal(resume.includes("fetch("), false);
});
