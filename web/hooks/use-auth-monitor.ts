"use client";

import { useEffect, useRef } from "react";
import { useSession, signOut } from "next-auth/react";

/**
 * 세션 상태를 모니터링하고 토큰 갱신 실패 시 자동 로그아웃하는 Hook
 *
 * 사용법:
 * - 클라이언트 컴포넌트에서 호출
 * - SessionProvider 하위에서만 작동
 *
 * @example
 * ```tsx
 * function MyComponent() {
 *   useAuthMonitor();
 *   return <div>...</div>;
 * }
 * ```
 */
export function useAuthMonitor() {
  const { data: session, status } = useSession();
  const hasLoggedOut = useRef(false);

  useEffect(() => {
    // 이미 로그아웃 처리했으면 중복 실행 방지
    if (hasLoggedOut.current) return;

    // 로딩 중이면 대기
    if (status === "loading") return;

    // 세션이 없으면 처리 불필요
    if (!session) return;

    // Refresh Token이 만료되어 갱신 실패한 경우
    if (session.error === "RefreshTokenExpired") {
      console.warn("Refresh token expired. Logging out...");
      hasLoggedOut.current = true;

      // 자동 로그아웃 (로그인 페이지로 리다이렉트)
      signOut({
        callbackUrl: "/login",
        redirect: true,
      });
    }
  }, [session, status]);
}
