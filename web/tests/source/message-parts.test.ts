import { strict as assert } from "node:assert/strict";
import { describe, test } from "node:test";

import {
  extractAttachments,
  extractTextContent,
  SUPPORTED_ATTACHMENT_MIME_TYPES,
} from "../../lib/message-parts";
import { postRequestBodySchema } from "../../app/(chat)/api/chat/schema";

/**
 * 회귀 테스트: 채팅 라우트가 file 파트를 전량 폐기하던 문제(FE_AUDIT_260717 §3.2).
 * 업로드가 성공해도 백엔드 `attachments` 필드가 한 번도 채워지지 않았다.
 */
describe("message parts → backend payload", () => {
  test("text 파트만 content로 합쳐진다", () => {
    const content = extractTextContent([
      { type: "text", text: "first" },
      {
        type: "file",
        url: "https://x/a.png",
        filename: "a.png",
        mediaType: "image/png",
      },
      { type: "text", text: "second" },
    ]);

    assert.equal(content, "first\nsecond");
  });

  test("legacy file 파트(filename)가 백엔드 attachments(name)로 변환된다 (폐기되지 않는다)", () => {
    const attachments = extractAttachments([
      { type: "text", text: "설명해줘" },
      {
        type: "file",
        url: "https://storage/report.pdf",
        filename: "report.pdf",
        mediaType: "application/pdf",
      },
    ]);

    assert.equal(attachments.length, 1);
    assert.deepEqual(attachments[0], {
      type: "file",
      url: "https://storage/report.pdf",
      name: "report.pdf",
      metadata: { mediaType: "application/pdf" },
    });
  });

  test("OpenResponses input_file 형식도 attachments로 변환된다", () => {
    const attachments = extractAttachments([
      {
        type: "input_file",
        file: {
          url: "https://storage/a.png",
          name: "a.png",
          media_type: "image/png",
        },
      },
    ]);

    assert.deepEqual(attachments, [
      {
        type: "file",
        url: "https://storage/a.png",
        name: "a.png",
        metadata: { mediaType: "image/png" },
      },
    ]);
  });

  test("input_text 파트도 content에 포함된다", () => {
    assert.equal(
      extractTextContent([{ type: "input_text", text: "hello" }]),
      "hello"
    );
  });

  test("첨부가 없으면 빈 배열 (백엔드 기본값과 동일)", () => {
    assert.deepEqual(extractAttachments([{ type: "text", text: "hi" }]), []);
  });

  test("file 파트의 documentId가 metadata로 보존된다", () => {
    const attachments = extractAttachments([
      {
        type: "file",
        url: "s3://bucket/key",
        filename: "scan.png",
        mediaType: "image/png",
        documentId: 42,
      },
    ]);

    assert.equal(attachments.length, 1);
    assert.deepEqual(attachments[0].metadata, {
      mediaType: "image/png",
      documentId: 42,
    });
  });

  test("documentId가 없는 옛 형식도 그대로 통과한다", () => {
    const attachments = extractAttachments([
      { type: "file", url: "s3://bucket/key", filename: "old.png", mediaType: "image/png" },
    ]);

    assert.deepEqual(attachments[0].metadata, { mediaType: "image/png" });
  });

  test("여러 첨부가 순서대로 보존된다", () => {
    const attachments = extractAttachments([
      {
        type: "file",
        url: "https://x/1.png",
        filename: "1.png",
        mediaType: "image/png",
      },
      {
        type: "file",
        url: "https://x/2.pdf",
        filename: "2.pdf",
        mediaType: "application/pdf",
      },
    ]);

    assert.deepEqual(
      attachments.map((a) => a.name),
      ["1.png", "2.pdf"]
    );
  });
});

/**
 * 경계 고정: FE 파트 = `filename`, 와이어(BE·OpenResponses) = `name`.
 * (2026-09-03 히스토리 감사 Task 3 — 작성기가 `name`을 쓰고 렌더러가
 * `filename`을 읽어서 모든 첨부가 새로고침 전에도 "file"로만 보이던 버그)
 */
describe("FE/wire boundary: filename ↔ name", () => {
  test("legacy file 파트가 filename을 쓰면 BackendAttachment.name으로 변환된다", () => {
    const attachments = extractAttachments([
      {
        type: "file",
        url: "https://storage/spec.docx",
        filename: "spec.docx",
        mediaType:
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      },
    ]);

    assert.deepEqual(attachments, [
      {
        type: "file",
        url: "https://storage/spec.docx",
        name: "spec.docx",
        metadata: {
          mediaType:
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
      },
    ]);
  });

  test("input_file 파트는 여전히 file.name을 읽는다 (외부 스펙 필드 불변)", () => {
    const attachments = extractAttachments([
      {
        type: "input_file",
        file: {
          url: "https://storage/spec.docx",
          name: "spec.docx",
          media_type:
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
      },
    ]);

    assert.deepEqual(attachments, [
      {
        type: "file",
        url: "https://storage/spec.docx",
        name: "spec.docx",
        metadata: {
          mediaType:
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
      },
    ]);
  });

  test("작성기가 만드는 legacy file 파트(filename)가 postRequestBodySchema.parse를 통과한다", () => {
    const body = {
      id: "5b7b6d8e-8e0b-4b8a-9c0b-0e6b1a2b3c4d",
      message: {
        id: "6c8c7e9f-9f1c-5c9b-ad1c-1f7c2b3c4d5e",
        role: "user" as const,
        parts: [
          { type: "text" as const, text: "이 파일 봐줘" },
          {
            type: "file" as const,
            url: "https://storage/report.pdf",
            filename: "report.pdf",
            mediaType: "application/pdf" as const,
          },
        ],
      },
      selectedChatModel: "claude-sonnet-5",
      selectedVisibilityType: "private" as const,
    };

    const result = postRequestBodySchema.parse(body);
    assert.equal(result.message.parts.length, 2);
  });
});

/**
 * 회귀 테스트: 업로드 라우트와 채팅 스키마의 MIME 목록 불일치(FE_AUDIT_260717 §3.5).
 * 업로드는 PDF를 허용하는데 채팅 스키마가 이미지 2종만 허용해서 400이 났다.
 */
describe("supported attachment MIME types", () => {
  test("업로드 UI가 허용하는 문서 타입이 채팅 스키마에서도 허용된다", () => {
    for (const mime of [
      "application/pdf",
      "image/gif",
      "image/webp",
      "text/markdown",
    ]) {
      assert.ok(
        (SUPPORTED_ATTACHMENT_MIME_TYPES as readonly string[]).includes(mime),
        `${mime} 이 지원 목록에서 빠졌다 — 첨부 시 400이 발생한다`
      );
    }
  });

  test("이미지 2종만 남는 회귀를 방지한다", () => {
    assert.ok(SUPPORTED_ATTACHMENT_MIME_TYPES.length > 2);
  });
});
