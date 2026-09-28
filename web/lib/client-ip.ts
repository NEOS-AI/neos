/**
 * BFF → nginx 로 **사용자** IP 를 넘기는 헤더 (순수 모듈).
 *
 * 프론트는 Vercel 에서 돌고 백엔드 호출은 BFF 서버에서 나간다. nginx 가 보는 접속
 * IP 는 BFF 의 것이라, 넘기지 않으면 모든 사용자가 rate limit 버킷 하나를 나눠 쓴다.
 *
 * nginx 는 `X-Neos-Proxy-Auth` 가 공유 비밀(`NEOS_CLIENT_IP_SECRET`)과 같을 때만
 * `X-Neos-Client-IP` 를 믿는다(`config/nginx/40-neos-client-ip.sh`). 비밀이 없으면
 * 아무것도 보내지 않는다 -- nginx 도 믿지 않을 값을 흘릴 이유가 없다.
 *
 * 사용자 IP 는 Vercel 이 덮어쓰는 `x-real-ip` 를 먼저, 없으면 `x-forwarded-for` 의
 * 첫 hop 을 쓴다. 스스로 호스팅한다면 이 두 헤더를 덮어쓰는 프록시 뒤에 둬야 한다 --
 * 아니면 사용자가 IP 를 골라 보낼 수 있다.
 */

export const CLIENT_IP_HEADER = "X-Neos-Client-IP";
export const PROXY_AUTH_HEADER = "X-Neos-Proxy-Auth";

// nginx 쪽 map 정규식과 같은 모양이다. 이 밖의 값은 키로 쓰지 않는다.
const ADDRESS = /^[0-9A-Fa-f:.]{2,45}$/;

function address(value: string | null): string | null {
  const candidate = value?.trim() ?? "";
  return ADDRESS.test(candidate) ? candidate : null;
}

export function clientIpFrom(headers: Headers): string | null {
  return (
    address(headers.get("x-real-ip")) ??
    address(headers.get("x-forwarded-for")?.split(",")[0] ?? null)
  );
}

export function clientIpForwardingHeaders(
  headers: Headers,
  secret: string | undefined
): Record<string, string> {
  const ip = clientIpFrom(headers);
  if (!(secret && ip)) {
    return {};
  }
  return { [CLIENT_IP_HEADER]: ip, [PROXY_AUTH_HEADER]: secret };
}
