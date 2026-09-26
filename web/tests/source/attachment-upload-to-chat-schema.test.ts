import { strict as assert } from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import { postRequestBodySchema } from "../../app/(chat)/api/chat/schema";
import { extractAttachments } from "../../lib/message-parts";

/**
 * Finding 1 (최종 전체 브랜치 리뷰, 2026-09-06) — e2e 회귀.
 *
 * `multimodal-input.tsx`의 `uploadFile`이 업로드 라우트 응답을
 * `{ url, pathname, contentType, documentId }`로 destructure했으나, 실제
 * 라우트(`app/(chat)/api/files/upload/route.ts`)는 `pathname`이 아니라
 * `name`을 돌려준다. 그 결과 `attachment.name`이 항상 `undefined`가 되고,
 * `submitForm`이 만드는 `filename: undefined`는 `JSON.stringify`에서 키째
 * 사라져 `postRequestBodySchema.parse`(`filename: z.string().min(1)`)가
 * 요청 전체를 400으로 거부했다 — 첨부가 달린 채팅은 백엔드에 도달조차
 * 못 했다. 단위 테스트(스키마만, 매핑만)는 이 결함을 각각 통과시켜
 * 잡지 못했다 — 실제 스키마 + 실제 업로드 응답 모양을 함께 걸어야 한다.
 *
 * 이 테스트는 `uploadFile`의 응답→첨부 매핑 코드를 소스에서 그대로 뽑아
 * 실행한다(재구현하지 않는다) — 그래야 `pathname` 구조분해로 되돌리면
 * 이 테스트가 실제로 빨개진다.
 */

function extractUploadFileMapping(): (data: Record<string, unknown>) => {
  url: unknown;
  name: unknown;
  contentType: unknown;
  documentId: unknown;
} {
  const source = readFileSync("components/multimodal-input.tsx", "utf8");
  const match = source.match(
    /const data = await response\.json\(\);([\s\S]*?return \{[\s\S]*?\};)/
  );
  if (!match) {
    throw new Error(
      "uploadFile의 응답→첨부 매핑 코드를 찾지 못했다 — multimodal-input.tsx 구조가 바뀌었다"
    );
  }

  const body = match[1];
  // eslint-disable-next-line @typescript-eslint/no-implied-eval, no-new-func
  return new Function("data", body) as (data: Record<string, unknown>) => {
    url: unknown;
    name: unknown;
    contentType: unknown;
    documentId: unknown;
  };
}

describe("attachment upload → chat schema (finding 1 e2e)", () => {
  test("실제 업로드 라우트 응답 모양으로 만든 첨부가 실제 postRequestBodySchema를 통과한다", () => {
    // web/app/(chat)/api/files/upload/route.ts 가 실제로 돌려주는 키들
    // (NextResponse.json({ url, name, contentType, documentId, processingStatus })).
    const uploadRouteResponse = {
      url: "https://storage.example.com/report.pdf",
      name: "report.pdf",
      contentType: "application/pdf",
      documentId: 42,
      processingStatus: "completed",
    };

    const mapToAttachment = extractUploadFileMapping();
    const attachment = mapToAttachment(uploadRouteResponse);

    assert.equal(
      attachment.name,
      "report.pdf",
      "uploadFile이 업로드 응답의 파일명을 잃어버렸다 (pathname 구조분해로 되돌아갔는가?)"
    );

    // submitForm(:145)이 실제로 만드는 file 파트 모양
    const body = {
      id: "5b7b6d8e-8e0b-4b8a-9c0b-0e6b1a2b3c4d",
      message: {
        id: "6c8c7e9f-9f1c-5c9b-ad1c-1f7c2b3c4d5e",
        role: "user" as const,
        parts: [
          { type: "text" as const, text: "이 파일 봐줘" },
          {
            type: "file" as const,
            url: attachment.url,
            filename: attachment.name,
            mediaType: attachment.contentType,
            documentId: attachment.documentId,
          },
        ],
      },
      selectedChatModel: "claude-sonnet-5",
      selectedVisibilityType: "private" as const,
    };

    // JSON.stringify를 실제로 거친 뒤 파싱한 것과 동일한 페이로드를 검증한다 —
    // `filename: undefined`는 JSON 왕복에서 키째 사라지는 것이 이 결함의 핵심이었다.
    const wireBody = JSON.parse(JSON.stringify(body));

    const result = postRequestBodySchema.safeParse(wireBody);

    assert.equal(
      result.success,
      true,
      "실제 업로드 응답으로 만든 첨부 채팅 요청이 postRequestBodySchema를 통과하지 못했다 " +
        "(첨부 달린 채팅이 400 bad_request:api 로 죽는다)"
    );
    if (!result.success) {
      return;
    }

    const attachments = extractAttachments(result.data.message.parts);
    assert.equal(attachments.length, 1);
    assert.equal(attachments[0].metadata.documentId, 42);
    assert.ok(
      typeof attachments[0].name === "string" && attachments[0].name.length > 0,
      "파싱된 파트에서 첨부 이름이 비어 있다"
    );
  });
});
