"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { listCodingCommands } from "@/features/coding/api/coding-api";
import { buildCommandTokens } from "./route-input";
import type { CodingCommandListing } from "./types";

const EMPTY: readonly CodingCommandListing[] = [];

/**
 * 슬래시 커맨드 카탈로그. 배포마다 고정이라 한 번 받아 캐시한다.
 *
 * 로딩 중이거나 실패하면 토큰 집합이 비어 **모든 입력이 steer 로 간다** --
 * "카탈로그에 있는 이름만 커맨드" 규칙을 그대로 따른 결과다. 커맨드가 조용히
 * 사라지는 것보다 지시가 에이전트에 닿는 쪽을 택한다.
 */
export function useCodingCommandCatalog() {
  const { data, error } = useSWR("coding-commands", listCodingCommands, {
    revalidateOnFocus: false,
    revalidateIfStale: false,
  });
  const commands = data ?? EMPTY;
  const tokens = useMemo(() => buildCommandTokens(commands), [commands]);
  return { commands, tokens, error: error as Error | undefined };
}
