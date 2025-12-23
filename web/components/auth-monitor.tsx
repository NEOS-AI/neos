"use client";

import { useAuthMonitor } from "@/hooks/use-auth-monitor";

/**
 * 인증 상태 모니터링 컴포넌트
 * - 토큰 갱신 실패 시 자동 로그아웃 처리
 * - UI 렌더링 없이 백그라운드에서 동작
 */
export function AuthMonitor() {
  useAuthMonitor();
  return null;
}
