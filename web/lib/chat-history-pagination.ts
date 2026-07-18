import type { Chat } from "@/lib/db/schema";

export type ChatHistory = {
  chats: Chat[];
  hasMore: boolean;
  nextCursor: string | null;
};

export const PAGE_SIZE = 20;

/**
 * SWRInfinite 키 빌더. 백엔드가 발급한 불투명 커서를 그대로 되돌려 보낸다
 * (내용을 해석하지 않는다). 근거: docs/FE_AUDIT_260717 §3.4.
 */
export function getChatHistoryPaginationKey(
  pageIndex: number,
  previousPageData: ChatHistory | null
): string | null {
  if (previousPageData && previousPageData.hasMore === false) {
    return null;
  }

  if (pageIndex === 0) {
    return `/api/history?limit=${PAGE_SIZE}`;
  }

  const cursor = previousPageData?.nextCursor;
  if (!cursor) {
    return null;
  }

  return `/api/history?cursor=${encodeURIComponent(cursor)}&limit=${PAGE_SIZE}`;
}
