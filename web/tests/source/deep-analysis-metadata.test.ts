/**
 * 백엔드 키 → 프론트 모양 브리지.
 *
 * 이 브리지가 없으면 새로고침 후 진행 카드가 **통째로** 사라진다 — 백엔드는
 * `deep_analysis_run_id`를 심는데 컴포넌트는 `deep_analysis`를 읽기 때문이다
 * (설계 §1.2).
 */

import assert from "node:assert/strict";
import test from "node:test";
import { deepAnalysisFromMessageMetadata } from "../../lib/deep-analysis/metadata";

test("백엔드 키를 프론트 모양으로 옮긴다", () => {
  const result = deepAnalysisFromMessageMetadata({
    deep_analysis_run_id: "a1b2c3d4",
    research_status: "completed",
    deep_analysis_degradations: [
      { kind: "report_assembly_degraded", count: 3 },
    ],
  });

  assert.deepEqual(result, {
    run_id: "a1b2c3d4",
    status: "completed",
    degradations: [{ kind: "report_assembly_degraded", count: 3 }],
  });
});

test("run_id가 없으면 undefined — 심층분석 메시지가 아니다", () => {
  assert.equal(deepAnalysisFromMessageMetadata({ createdAt: "x" }), undefined);
  assert.equal(deepAnalysisFromMessageMetadata({}), undefined);
  assert.equal(deepAnalysisFromMessageMetadata(undefined), undefined);
  assert.equal(deepAnalysisFromMessageMetadata(null), undefined);
  assert.equal(
    deepAnalysisFromMessageMetadata({ deep_analysis_run_id: "" }),
    undefined
  );
});

test("강등 키가 없으면 status만 복원한다", () => {
  const result = deepAnalysisFromMessageMetadata({
    deep_analysis_run_id: "a1b2c3d4",
    research_status: "completed",
  });

  assert.equal(result?.run_id, "a1b2c3d4");
  assert.equal(result?.status, "completed");
  assert.equal(result?.degradations, undefined);
});

test("run_id가 있는데 status가 없으면 completed로 본다", () => {
  // 백엔드는 완료된 run 만 메시지로 영속화한다 (deep_analysis_job_task.py).
  const result = deepAnalysisFromMessageMetadata({
    deep_analysis_run_id: "a1b2c3d4",
  });

  assert.equal(result?.status, "completed");
});

test("깨진 강등 값에 던지지 않는다", () => {
  const result = deepAnalysisFromMessageMetadata({
    deep_analysis_run_id: "a1b2c3d4",
    deep_analysis_degradations: [
      null,
      "쓰레기",
      { count: 2 },
      { kind: "", count: 1 },
      { kind: "report_assembly_degraded" },
      { kind: "node_reduction_degraded", count: "셋" },
      { kind: "judge_unreviewed:truncated", count: 2 },
    ],
  });

  assert.deepEqual(result?.degradations, [
    { kind: "report_assembly_degraded", count: 1 },
    { kind: "node_reduction_degraded", count: 1 },
    { kind: "judge_unreviewed:truncated", count: 2 },
  ]);
});

test("강등 배열이 배열이 아니면 무시한다", () => {
  const result = deepAnalysisFromMessageMetadata({
    deep_analysis_run_id: "a1b2c3d4",
    deep_analysis_degradations: "report_assembly_degraded",
  });

  assert.equal(result?.degradations, undefined);
});

test("run_id 접근에서 던지는 getter에도 던지지 않는다", () => {
  const metadata = {
    get deep_analysis_run_id(): string {
      throw new Error("boom");
    },
  };

  assert.doesNotThrow(() => deepAnalysisFromMessageMetadata(metadata));
  assert.equal(deepAnalysisFromMessageMetadata(metadata), undefined);
});

test("degradations 접근에서 던지는 getter에도 던지지 않는다", () => {
  const metadata = {
    deep_analysis_run_id: "a1b2c3d4",
    get deep_analysis_degradations(): unknown[] {
      throw new Error("boom2");
    },
  };

  assert.doesNotThrow(() => deepAnalysisFromMessageMetadata(metadata));
  assert.equal(deepAnalysisFromMessageMetadata(metadata), undefined);
});

test("get 트랩이 던지는 Proxy에도 던지지 않는다", () => {
  const metadata = new Proxy(
    {},
    {
      get() {
        throw new Error("proxy-boom");
      },
    }
  );

  assert.doesNotThrow(() => deepAnalysisFromMessageMetadata(metadata));
  assert.equal(deepAnalysisFromMessageMetadata(metadata), undefined);
});
