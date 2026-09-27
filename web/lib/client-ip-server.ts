import "server-only";

import { headers } from "next/headers";
import { clientIpForwardingHeaders } from "@/lib/client-ip";

/**
 * 지금 처리 중인 요청의 사용자 IP 를 nginx 로 넘길 헤더 (`lib/client-ip.ts`).
 *
 * 요청 스코프 밖(빌드·백그라운드)에서는 `headers()` 가 던진다. 그때는 넘길
 * 사용자가 없으므로 빈 객체다 -- nginx 는 접속 IP 로 센다.
 */
export async function requestClientIpHeaders(): Promise<Record<string, string>> {
  try {
    return clientIpForwardingHeaders(
      await headers(),
      process.env.NEOS_CLIENT_IP_SECRET?.trim()
    );
  } catch {
    return {};
  }
}
