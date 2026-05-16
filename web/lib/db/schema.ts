/**
 * DB 타입 정의 (Drizzle 제거 후 순수 TypeScript 인터페이스)
 *
 * 이 파일은 Drizzle ORM 없이 동일한 타입 형태를 유지합니다.
 * 임포트 경로를 변경하지 않아도 됩니다.
 */

export type User = {
  id: string;
  email: string;
  password: string | null;
};

export type Chat = {
  id: string;
  createdAt: Date;
  title: string;
  userId: string;
  visibility: "public" | "private";
  backendConversationId: string | null;
};

/** @deprecated Message_v2로 대체됨 */
export type MessageDeprecated = {
  id: string;
  chatId: string;
  role: string;
  content: unknown;
  createdAt: Date;
};

export type DBMessage = {
  id: string;
  chatId: string;
  role: string;
  parts: unknown;
  attachments: unknown;
  createdAt: Date;
};

/** @deprecated Vote_v2로 대체됨 */
export type VoteDeprecated = {
  chatId: string;
  messageId: string;
  isUpvoted: boolean;
};

export type Vote = {
  chatId: string;
  messageId: string;
  isUpvoted: boolean;
};

export type Document = {
  id: string;
  createdAt: Date;
  title: string;
  content: string | null;
  kind: "text" | "code" | "image" | "sheet";
  userId: string;
};

export type Suggestion = {
  id: string;
  documentId: string;
  documentCreatedAt: Date;
  originalText: string;
  suggestedText: string;
  description: string | null;
  isResolved: boolean;
  userId: string;
  createdAt: Date;
};

export type Stream = {
  id: string;
  chatId: string;
  createdAt: Date;
};
