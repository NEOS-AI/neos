import { strict as assert } from "node:assert/strict";
import { describe, test } from "node:test";

import {
  extractAttachments,
  extractTextContent,
  SUPPORTED_ATTACHMENT_MIME_TYPES,
} from "../../lib/message-parts";

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
        name: "a.png",
        mediaType: "image/png",
      },
      { type: "text", text: "second" },
    ]);

    assert.equal(content, "first\nsecond");
  });

  test("file 파트가 백엔드 attachments로 보존된다 (폐기되지 않는다)", () => {
    const attachments = extractAttachments([
      { type: "text", text: "설명해줘" },
      {
        type: "file",
        url: "https://storage/report.pdf",
        name: "report.pdf",
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

  test("여러 첨부가 순서대로 보존된다", () => {
    const attachments = extractAttachments([
      {
        type: "file",
        url: "https://x/1.png",
        name: "1.png",
        mediaType: "image/png",
      },
      {
        type: "file",
        url: "https://x/2.pdf",
        name: "2.pdf",
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
