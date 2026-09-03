import { strict as assert } from "node:assert/strict";
import { describe, test } from "node:test";

import { convertBackendMessagesToUI } from "../../lib/utils";

/**
 * 회귀 테스트: `convertBackendMessagesToUI` 가 BE `attachments` 를 통째로
 * 버리던 문제 (2026-09-03 히스토리 감사, Task 2).
 *
 * BE `MessageResponse.attachments` (`{type, url, name, size, metadata}`) 를
 * FE file 파트로 되살린다. FE file 파트의 필드명은 `filename` 이다
 * (`name` 이 아니다 — Task 3 이 정한 정본 모양, `components/message.tsx` 가
 * `attachment.filename` 을 읽는다).
 */
describe("convertBackendMessagesToUI attachments", () => {
  test("첨부 2개짜리 BE 메시지 → text 파트 1 + file 파트 2, 순서와 필드값", () => {
    const [ui] = convertBackendMessagesToUI([
      {
        message_id: "m1",
        role: "assistant",
        content: "here are the files",
        created_at: "2026-09-03T00:00:00Z",
        sequence_number: 1,
        attachments: [
          {
            type: "file",
            url: "https://storage/a.png",
            name: "a.png",
            size: 123,
            metadata: { mediaType: "image/png" },
          },
          {
            type: "file",
            url: "https://storage/b.pdf",
            name: "b.pdf",
            size: 456,
            metadata: { mediaType: "application/pdf" },
          },
        ],
      },
    ]);

    assert.equal(ui.parts.length, 3);
    assert.deepEqual(ui.parts[0], { type: "text", text: "here are the files" });
    assert.deepEqual(ui.parts[1], {
      type: "file",
      url: "https://storage/a.png",
      filename: "a.png",
      mediaType: "image/png",
    });
    assert.deepEqual(ui.parts[2], {
      type: "file",
      url: "https://storage/b.pdf",
      filename: "b.pdf",
      mediaType: "application/pdf",
    });
  });

  test("attachments: [] → file 파트 없음, 기존 동작 그대로", () => {
    const [ui] = convertBackendMessagesToUI([
      {
        message_id: "m2",
        role: "user",
        content: "no attachments",
        created_at: "2026-09-03T00:00:00Z",
        sequence_number: 1,
        attachments: [],
      },
    ]);

    assert.deepEqual(ui.parts, [{ type: "text", text: "no attachments" }]);
  });

  test("attachments 필드가 아예 없어도 기존 동작 그대로", () => {
    const [ui] = convertBackendMessagesToUI([
      {
        message_id: "m3",
        role: "user",
        content: "legacy message",
        created_at: "2026-09-03T00:00:00Z",
        sequence_number: 1,
      },
    ]);

    assert.deepEqual(ui.parts, [{ type: "text", text: "legacy message" }]);
  });

  test("url 없는 항목은 건너뛰되 나머지 첨부는 살아남는다", () => {
    const [ui] = convertBackendMessagesToUI([
      {
        message_id: "m4",
        role: "assistant",
        content: "mixed",
        created_at: "2026-09-03T00:00:00Z",
        sequence_number: 1,
        attachments: [
          { type: "file", url: null, name: "broken.png", metadata: {} },
          {
            type: "file",
            url: "https://storage/ok.png",
            name: "ok.png",
            metadata: { mediaType: "image/png" },
          },
        ],
      },
    ]);

    assert.equal(ui.parts.length, 2);
    assert.deepEqual(ui.parts[1], {
      type: "file",
      url: "https://storage/ok.png",
      filename: "ok.png",
      mediaType: "image/png",
    });
  });

  test("metadata.mediaType 없으면 mediaType 이 생략되고 렌더가 죽지 않는다", () => {
    const [ui] = convertBackendMessagesToUI([
      {
        message_id: "m5",
        role: "assistant",
        content: "no media type",
        created_at: "2026-09-03T00:00:00Z",
        sequence_number: 1,
        attachments: [
          { type: "file", url: "https://storage/x.bin", name: "x.bin" },
        ],
      },
    ]);

    assert.equal(ui.parts.length, 2);
    const filePart = ui.parts[1] as { type: string; mediaType?: unknown };
    assert.equal("mediaType" in filePart, false);
  });

  test("attachments 가 배열이 아니면 조용히 무시된다", () => {
    const [ui] = convertBackendMessagesToUI([
      {
        message_id: "m6",
        role: "assistant",
        content: "malformed",
        created_at: "2026-09-03T00:00:00Z",
        sequence_number: 1,
        attachments: "not-an-array",
      },
    ]);

    assert.deepEqual(ui.parts, [{ type: "text", text: "malformed" }]);
  });
});
