import type { CodingCommandListing } from "./types";

/**
 * 입력기 한 줄을 steer 와 슬래시 커맨드 중 어디로 보낼지 정한다.
 *
 * 규칙: **카탈로그에 있는 이름일 때만** 커맨드 엔드포인트로 간다. `/` 로
 * 시작하는 경로(`/src/app.py 고쳐줘`)나 모르는 단어는 steer 로 넘긴다 --
 * 커맨드로 보내면 백엔드가 `unknown_coding_command` 400 을 내고 지시가
 * 에이전트에 닿지 않는다.
 *
 * 토큰화는 백엔드 `neos/coding/commands/parse.py` 의 `parse_slash_command` 와
 * 같아야 한다: 앞뒤 공백 제거 → 첫 스페이스로 머리 분리 → 소문자 →
 * `/`·`!` 접두어 → `/name@bot` 의 `@` 뒤 제거. 어긋나면 프론트가 커맨드라고
 * 보낸 것을 백엔드가 모른다고 한다.
 */

export type ComposerRoute =
  | { kind: "command"; text: string }
  | { kind: "steer"; instruction: string };

/** 카탈로그 → 조회 토큰 집합 (백엔드 `_BY_TOKEN` 과 같은 키). */
export function buildCommandTokens(
  commands: readonly CodingCommandListing[]
): ReadonlySet<string> {
  const tokens = new Set<string>();
  for (const command of commands) {
    for (const raw of [command.name, ...command.aliases]) {
      const token = raw.replace(/^[/!]+/, "").toLowerCase();
      if (token) {
        tokens.add(token);
      }
    }
  }
  return tokens;
}

/** 슬래시 토큰의 이름 부분. 슬래시 형태가 아니면 null. */
function slashCommandName(text: string): string | null {
  const head = text.trim().split(" ", 1)[0].toLowerCase();
  if (!head.startsWith("/") && !head.startsWith("!")) {
    return null;
  }
  const bare = head.startsWith("/") ? head.split("@", 1)[0] : head;
  const name = bare.slice(1);
  return name || null;
}

export function routeComposerInput(
  text: string,
  tokens: ReadonlySet<string>
): ComposerRoute {
  const name = slashCommandName(text);
  if (name !== null && tokens.has(name)) {
    return { kind: "command", text };
  }
  return { kind: "steer", instruction: text };
}
