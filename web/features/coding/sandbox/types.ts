/**
 * 브라우저가 아는 샌드박스 상태의 **전부**.
 *
 * 백엔드 투영(`neos/coding/managed/projection.py`)이 내보내는 다섯 필드와
 * 정확히 같다. 인프라 사실은 여기 없다 -- 이 파일에 필드를 하나 늘리는 것이
 * 곧 유출이고, `coding-sandbox-status.test.ts`가 금지어 목록으로 그것을
 * 막는다.
 *
 * 왜 이렇게까지 하는가: 한 번 브라우저로 나간 값은 계약이 된다. provider
 * 이름을 내보내면 provider 를 바꿀 때 사용자에게 보이는 문자열이 바뀌고,
 * 내부 식별자를 내보내면 그것을 키로 쓰는 코드가 프론트에 생긴다.
 */
export type CodingSandboxState =
  | "preparing"
  | "ready"
  | "suspended"
  | "provider_recovery_pending"
  | "operator_recovery_required"
  | "cleaning_up"
  | "cleaned";

export type CodingSandboxStatus = {
  state: CodingSandboxState;
  can_run: boolean;
  can_open_terminal: boolean;
  recovered_from_checkpoint: boolean;
  updated_at: string;
};
