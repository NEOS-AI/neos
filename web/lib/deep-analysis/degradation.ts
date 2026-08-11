/**
 * 강등 상태 → 사람이 읽는 경고 (순수 함수)
 *
 * `progress.ts`가 원장의 어휘(`kind`)만 상태에 싣고 문구는 싣지 않는 이유가
 * 이 파일의 존재 이유다: 문구를 상태에 넣으면 재생된 옛 이벤트가 옛 문구를
 * 고착시킨다. 문구는 렌더 시점에 만든다.
 *
 * 컴포넌트가 아니라 여기 있는 이유: `web/package.json`의 `test:source`는
 * `tsx --test`라 DOM이 없다. 표시 로직이 컴포넌트로 들어가면 회귀 가드가 0이 된다.
 *
 * `progress.ts`와 나눈 이유: 저쪽의 일은 *원장 → 상태*이고 이쪽은
 * *완성된 상태 → 문구*다. 생애주기가 다르다.
 */

import type { DegradationEntry } from "./progress";

/** `degradationKind()`가 판정자 강등에 붙이는 접두사 (progress.ts와 짝). */
const JUDGE_PREFIX = "judge_unreviewed:";

// `kind`는 백엔드 이벤트 원문에서 그대로 온다 — 새로고침 후 복원 경로에서는
// 와이어 위의 임의 문자열이다. 일반 객체 리터럴로 테이블을 만들면
// `"constructor"`, `"toString"` 같은 kind가 `Object.prototype`의 메서드에
// 걸려 함수를 돌려준다(`declared string` 타입을 런타임에 깨고, 컴포넌트가
// `{notice.text}`를 그대로 렌더하면 React가 던진다). `Map`은 프로토타입
// 체인을 타지 않으므로 이 클래스의 버그를 원천 차단한다.
const LABELS = new Map<string, string>([
  ["report_assembly_degraded", "리포트가 LLM 조립 없이 템플릿으로 작성됐습니다"],
  ["node_reduction_degraded", "하위 요약이 강등돼 자식 답변을 그대로 이어붙였습니다"],
  ["finalization_prompt_clamped", "마무리 입력이 허용량을 넘어 일부 내용이 잘렸습니다"],
]);

const JUDGE_LABELS = new Map<string, string>([
  ["budget_exhausted", "심사 없이 통과됐습니다 — 판정자 예산 소진"],
  ["truncated", "심사 없이 통과됐습니다 — 판정자 응답이 잘림"],
  ["unparseable", "심사 없이 통과됐습니다 — 판정자 응답을 해석하지 못함"],
]);

/**
 * kind 하나를 문구로 만든다.
 *
 * 모르는 kind를 조용히 떨구지 않는다 — 조용한 누락은 이 파일이 없애려는 바로
 * 그 죄다. `progress.ts`가 모르는 이벤트에도 커서를 전진시키는 것과 같은 판단.
 */
export function degradationLabel(kind: string): string {
  const known = LABELS.get(kind);
  if (known) {
    return known;
  }
  if (kind.startsWith(JUDGE_PREFIX)) {
    const reason = kind.slice(JUDGE_PREFIX.length);
    return JUDGE_LABELS.get(reason) ?? `심사 없이 통과됐습니다 — ${reason}`;
  }
  return `리포트 품질이 저하됐습니다 · ${kind}`;
}

export type DegradationNotice = { kind: string; text: string };

/**
 * 강등 항목들을 화면에 그릴 문구로 바꾼다.
 *
 * 상태(`DeepAnalysisProgress`)가 아니라 항목 배열을 받는 이유: 출처가 둘이다.
 * 라이브 스트림은 `progress.degradations`, 새로고침 후는 메시지 메타데이터.
 * 둘 다 같은 모양이므로 이 함수는 출처를 몰라도 된다.
 */
export function degradationNotices(
  entries: readonly DegradationEntry[]
): DegradationNotice[] {
  return entries.map((entry) => {
    const label = degradationLabel(entry.kind);
    return {
      kind: entry.kind,
      // 3회와 1회는 다른 이야기다(D26). 1회일 때 "(1회)"는 소음이므로 뺀다.
      text: entry.count > 1 ? `${label} (${entry.count}회)` : label,
    };
  });
}
