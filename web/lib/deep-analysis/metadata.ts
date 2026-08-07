/**
 * 백엔드 메시지 메타데이터 → `DeepAnalysisMetadata` 브리지
 *
 * ## 왜 필요한가 — 키 이름이 양쪽에서 달랐다
 *
 * 백엔드는 완료된 리포트를 메시지로 저장하면서 메타데이터에
 * `deep_analysis_run_id` / `research_status` / `deep_analysis_degradations`를
 * 심는다(`neos/tasks/deep_analysis_job_task.py`의 `_persist_assistant_message`).
 * 프론트 컴포넌트가 읽는 키는 `deep_analysis` = `{run_id, status, degradations}`다
 * (`components/message.tsx`).
 *
 * 이 불일치 때문에 **새로고침하면 진행 카드가 통째로 사라졌다** — 강등 경고만이
 * 아니라 카드 자체가. `sessionStorage`의 run 포인터도 종결 시
 * `forgetActiveRun()`으로 지워지므로 그 경로로도 복구되지 않았다.
 *
 * 이력 로드 경로(`lib/utils.ts`의 `convertBackendMessagesToUI`)가 백엔드
 * 메타데이터 키를 그대로 통과시키므로, 이 함수가 원본 키를 읽어 프론트 모양으로
 * 옮긴다. 방어적으로 읽는다 — 이력 로드 전체를 깨뜨리면 안 되므로 어떤 입력에도
 * 던지지 않는다.
 */

import type { DeepAnalysisMetadata } from "../types";
import type { DegradationEntry } from "./progress";

const RUN_ID_KEY = "deep_analysis_run_id";
const STATUS_KEY = "research_status";
const DEGRADATIONS_KEY = "deep_analysis_degradations";

const STATUSES = ["pending", "running", "completed", "failed"] as const;
type DeepAnalysisStatus = (typeof STATUSES)[number];

function asStatus(value: unknown): DeepAnalysisStatus | undefined {
  return typeof value === "string" &&
    (STATUSES as readonly string[]).includes(value)
    ? (value as DeepAnalysisStatus)
    : undefined;
}

function asDegradations(value: unknown): DegradationEntry[] | undefined {
  if (!Array.isArray(value)) {
    return;
  }
  const entries: DegradationEntry[] = [];
  for (const raw of value) {
    if (typeof raw !== "object" || raw === null) {
      continue;
    }
    const { kind, count } = raw as { kind?: unknown; count?: unknown };
    if (typeof kind !== "string" || kind.length === 0) {
      continue;
    }
    // 횟수가 깨졌으면 1로 본다 — 사건이 있었다는 사실이 횟수보다 중요하다.
    const valid =
      typeof count === "number" && Number.isFinite(count) && count > 0;
    entries.push({ kind, count: valid ? count : 1 });
  }
  return entries.length > 0 ? entries : undefined;
}

export function deepAnalysisFromMessageMetadata(
  metadata: Record<string, unknown> | undefined | null
): DeepAnalysisMetadata | undefined {
  // 위 주석의 "어떤 입력에도 던지지 않는다"는 약속을 코드로 지킨다. 평범한
  // JSON에서 온 metadata라면 속성 접근이 던질 리 없지만, 이 함수의 시그니처는
  // 그 전제를 강제하지 않는다 — 언젠가 getter나 Proxy가 섞인 객체로 호출될
  // 수 있다. try/catch로 감싸 두면 그런 입력이 이력 로드 전체를 끌고
  // 내려가는 대신 이 메시지 하나만 "심층분석 아님"으로 처리하고 넘어간다.
  try {
    if (!metadata) {
      return;
    }
    const runId = metadata[RUN_ID_KEY];
    if (typeof runId !== "string" || runId.length === 0) {
      return;
    }
    return {
      run_id: runId,
      // 백엔드는 **완료된** run 만 메시지로 영속화하므로, run_id 가 있는데
      // 상태가 없으면 완료로 본다.
      status: asStatus(metadata[STATUS_KEY]) ?? "completed",
      degradations: asDegradations(metadata[DEGRADATIONS_KEY]),
    };
  } catch {
    return;
  }
}
