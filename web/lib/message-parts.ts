/**
 * 메시지 파트 → 백엔드 페이로드 변환
 *
 * FE는 메시지를 `parts` 배열로 다루지만(`components/multimodal-input.tsx`),
 * 백엔드 `SendMessageRequest`(`neos/api/models/chat_models.py:76-81`)는
 * `content`(문자열)와 `attachments`(딕셔너리 배열)로 나뉜다.
 *
 * 과거에는 채팅 라우트가 text 파트만 남기고 file 파트를 **전량 폐기**했기 때문에
 * `attachments`가 한 번도 채워지지 않았다 → 첨부가 LLM에 도달하지 못했다.
 * 이 모듈이 그 변환을 담당하고 회귀 테스트로 고정한다.
 */

/**
 * 첨부 가능한 MIME 타입 — **단일 출처(single source of truth)**
 *
 * 업로드 라우트(`app/(chat)/api/files/upload/route.ts`)와
 * 채팅 요청 스키마(`app/(chat)/api/chat/schema.ts`)가 이 목록을 공유한다.
 *
 * 과거에는 두 곳이 어긋나 있었다 — 업로드는 9종을 허용하는데 채팅 스키마는
 * `image/jpeg`/`image/png`만 허용해서, PDF를 첨부하면 업로드는 성공하고
 * 채팅 요청 전체가 400(`bad_request:api`)으로 죽었다.
 */
export const SUPPORTED_ATTACHMENT_MIME_TYPES = [
  // Images
  "image/jpeg",
  "image/png",
  "image/gif",
  "image/webp",
  // Documents
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
  "text/markdown",
] as const;

export type SupportedAttachmentMimeType =
  (typeof SUPPORTED_ATTACHMENT_MIME_TYPES)[number];

/** FE 메시지 파트 (legacy + OpenResponses 두 형식 모두 수용) */
export type AnyMessagePart =
  | { type: "text"; text: string }
  | { type: "input_text"; text: string }
  | { type: "file"; url: string; name: string; mediaType: string }
  | {
      type: "input_file";
      file: { url: string; name: string; media_type: string };
    }
  | { type: string; [key: string]: unknown };

/**
 * 백엔드 `MessageAttachment` 형태
 * (`neos/api/models/chat_models.py:165-170`)
 */
export type BackendAttachment = {
  type: string;
  url: string | null;
  name: string | null;
  metadata: Record<string, unknown>;
};

/** text 계열 파트를 하나의 content 문자열로 합친다. */
export function extractTextContent(parts: readonly AnyMessagePart[]): string {
  return parts
    .filter(
      (part): part is { type: "text" | "input_text"; text: string } =>
        (part.type === "text" || part.type === "input_text") &&
        typeof (part as { text?: unknown }).text === "string"
    )
    .map((part) => part.text)
    .join("\n");
}

/**
 * file 계열 파트를 백엔드 `attachments` 배열로 변환한다.
 *
 * legacy(`{type:"file", url, name, mediaType}`)와
 * OpenResponses(`{type:"input_file", file:{url, name, media_type}}`) 두 형식을 모두 받는다.
 * 두 형식 모두 `app/(chat)/api/chat/schema.ts`의 `partSchema`가 허용하기 때문이다.
 */
export function extractAttachments(
  parts: readonly AnyMessagePart[]
): BackendAttachment[] {
  const attachments: BackendAttachment[] = [];

  for (const part of parts) {
    if (part.type === "file") {
      const filePart = part as {
        url?: string;
        name?: string;
        mediaType?: string;
      };
      attachments.push({
        type: "file",
        url: filePart.url ?? null,
        name: filePart.name ?? null,
        metadata: filePart.mediaType ? { mediaType: filePart.mediaType } : {},
      });
      continue;
    }

    if (part.type === "input_file") {
      const file = (
        part as { file?: { url?: string; name?: string; media_type?: string } }
      ).file;
      if (!file) {
        continue;
      }
      attachments.push({
        type: "file",
        url: file.url ?? null,
        name: file.name ?? null,
        metadata: file.media_type ? { mediaType: file.media_type } : {},
      });
    }
  }

  return attachments;
}
