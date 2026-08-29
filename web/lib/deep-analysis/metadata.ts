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

/**
 * 복원 경로의 강등 목록을 읽는다 — kind별로 **접어서** 돌려준다.
 *
 * 접는 이유(FE7): 이 함수는 kind별 유일성을 백엔드의 불변식에 기대고 있었지
 * 스스로 강제하지 않았다. 지금은 `Ledger.degradations()`가 유일한 작성자이고
 * kind를 키로 한 dict로 집계해 넘기므로 중복이 나올 수 없다. 그러나 그 경로를
 * 우회하는 새 작성자가 생기면 같은 kind가 두 번 들어오고, 컴포넌트가 `kind`를
 * React key로 쓰므로 **키가 겹친다**.
 *
 * 라이브 경로(`progress.ts`의 `withDegradation`)는 이미 같은 규칙으로 접는다.
 * 여기서 접지 않으면 같은 데이터가 스트림으로 왔을 때와 새로고침 후에 서로
 * 다른 모양이 되고, 그 불일치는 화면에서만 드러난다.
 *
 * 규칙도 `withDegradation`과 같아야 한다: 합산하고, **최초 발생 순서**를 지킨다.
 */
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
    const resolved = valid ? count : 1;
    // `find`는 O(n²)이지만 n은 강등 종류 수(한 자릿수)다. Map을 쓰면 순서
    // 보존을 따로 관리해야 하고, 그 복잡도가 이득보다 크다.
    const existing = entries.find((entry) => entry.kind === kind);
    if (existing) {
      existing.count += resolved;
    } else {
      entries.push({ kind, count: resolved });
    }
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
      // 상태가 없으면 완료로 본다.
      //
      // ⚠️ 근거가 바뀌었다. 예전에는 "백엔드가 **완료된** run 만 영속화하므로"
      // 였는데, FE5 로 실패한 run 도 메시지를 갖게 됐다 — 다만 그때는 백엔드가
      // `research_status: "failed"` 를 **명시**한다. 그래서 상태가 비어 있는
      // 메시지는 이제 "FE5 이전에 쓰인 옛 메시지"라는 뜻이고, 그것들은 전부
      // 완료된 run 이다. 기본값은 그대로 옳지만 이유가 다르다.
      status: asStatus(metadata[STATUS_KEY]) ?? "completed",
      degradations: asDegradations(metadata[DEGRADATIONS_KEY]),
    };
  } catch (error) {
    // 여기서 삼킨 예외는 사용자에게 보이지 않는다 — 로그가 없으면 향후
    // asStatus/asDegradations 수정이 내부 TypeError를 일으켜도 아무 신호 없이
    // 모든 대화의 deep_analysis 카드가 이력에서 통째로 사라진다. 이 모듈이
    // 막으려는 바로 그 "조용한 강등"이 되지 않도록, metadata 객체(대화 내용)는
    // 찍지 않고 에러만 남긴다.
    console.error("deepAnalysisFromMessageMetadata failed", error);
    return;
  }
}
