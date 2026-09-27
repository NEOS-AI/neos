import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import {
  CLIENT_IP_HEADER,
  clientIpForwardingHeaders,
  clientIpFrom,
  PROXY_AUTH_HEADER,
} from "@/lib/client-ip";

/**
 * BFF → nginx 로 **사용자** IP 를 넘긴다.
 *
 * 프론트는 Vercel 에서 돌고 백엔드 호출은 BFF 서버에서 나간다. nginx 가 보는 접속
 * IP 는 BFF 의 것이라 모든 사용자가 rate limit 버킷 하나를 나눠 쓴다. nginx 는
 * 공유 비밀이 맞을 때만 `X-Neos-Client-IP` 를 믿는다(`config/nginx/40-neos-client-ip.sh`).
 */

const SECRET = "s".repeat(40);

test("x-real-ip wins over x-forwarded-for", () => {
  const headers = new Headers({
    "x-real-ip": "203.0.113.7",
    "x-forwarded-for": "198.51.100.1, 10.0.0.1",
  });
  assert.equal(clientIpFrom(headers), "203.0.113.7");
});

test("the first x-forwarded-for hop is the client", () => {
  const headers = new Headers({ "x-forwarded-for": " 198.51.100.1 , 10.0.0.1" });
  assert.equal(clientIpFrom(headers), "198.51.100.1");
});

test("ipv6 addresses pass", () => {
  assert.equal(
    clientIpFrom(new Headers({ "x-real-ip": "2001:db8::1" })),
    "2001:db8::1"
  );
});

test("anything that is not an address is dropped", () => {
  for (const value of ["", "unknown", "1.2.3.4; drop", "a".repeat(60)]) {
    assert.equal(clientIpFrom(new Headers({ "x-real-ip": value })), null, value);
  }
  assert.equal(clientIpFrom(new Headers()), null);
});

test("with a secret the IP and the proof travel together", () => {
  const forwarded = clientIpForwardingHeaders(
    new Headers({ "x-real-ip": "203.0.113.7" }),
    SECRET
  );
  assert.deepEqual(forwarded, {
    [CLIENT_IP_HEADER]: "203.0.113.7",
    [PROXY_AUTH_HEADER]: SECRET,
  });
});

test("without a secret or an address nothing is sent", () => {
  const ip = new Headers({ "x-real-ip": "203.0.113.7" });
  assert.deepEqual(clientIpForwardingHeaders(ip, undefined), {});
  assert.deepEqual(clientIpForwardingHeaders(ip, ""), {});
  assert.deepEqual(clientIpForwardingHeaders(new Headers(), SECRET), {});
});

test("every BFF fetch to the backend forwards the IP", () => {
  // 하나라도 빠지면 그 경로의 사용자는 다시 BFF IP 버킷 하나를 나눠 쓴다.
  // 백엔드를 부르는 fetch 는 `backendUrl` 로 URL 을 만들거나(직접 호출)
  // `lib/backend-api.ts` 안에서 `fetch(url` 로 부른다.
  // 파일 목록을 손으로 적지 않는다 -- 백엔드 URL 을 쓰는 파일이 곧 대상이다.
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) {
        walk(full);
      } else if (
        /\.tsx?$/.test(name) &&
        full !== path.join("lib", "server-config.ts") &&
        readFileSync(full, "utf8").includes("getBackendUrl(")
      ) {
        files.push(full);
      }
    }
  };
  walk("app");
  walk("lib");
  const missing: string[] = [];
  let calls = 0;
  for (const file of files) {
    const source = readFileSync(file, "utf8");
    let at = source.indexOf("fetch(");
    while (at !== -1) {
      const head = source.slice(at, at + 160);
      if (head.includes("backendUrl") || head.startsWith("fetch(url")) {
        calls += 1;
        const options = source.slice(at, source.indexOf("});", at));
        if (!options.includes("...(await requestClientIpHeaders())")) {
          missing.push(`${file}:${source.slice(0, at).split("\n").length}`);
        }
      }
      at = source.indexOf("fetch(", at + 1);
    }
  }
  assert.ok(calls >= 9, `scanner found only ${calls} backend fetches`);
  assert.deepEqual(missing, []);
});
