import { strict as assert } from "node:assert/strict";
import { describe, test } from "node:test";

import { attachmentNoticesFromMessageMetadata } from "../../lib/utils";

/**
 * 백엔드는 상한·해석 실패로 모델에 싣지 못한 첨부의 사유를
 * `attachment_notices` 로 메시지 메타데이터에 남긴다. 통과 경로가 그것을
 * **무검증으로** 컴포넌트까지 옮기므로(`convertBackendMessagesToUI` 의 일반
 * 복사), harness 와 같은 이유로 여기서 모양을 확정한다.
 */
describe("attachmentNoticesFromMessageMetadata", () => {
  test("문자열 배열은 그대로 통과한다", () => {
    assert.deepEqual(
      attachmentNoticesFromMessageMetadata({
        attachment_notices: ["scan.png: 길이 상한으로 제외됨"],
      }),
      ["scan.png: 길이 상한으로 제외됨"]
    );
  });

  test("빈 배열은 undefined 로 접는다 — 보여줄 것이 없다", () => {
    assert.equal(
      attachmentNoticesFromMessageMetadata({ attachment_notices: [] }),
      undefined
    );
  });

  test("키가 없으면 undefined", () => {
    assert.equal(attachmentNoticesFromMessageMetadata({}), undefined);
    assert.equal(attachmentNoticesFromMessageMetadata(null), undefined);
    assert.equal(attachmentNoticesFromMessageMetadata(undefined), undefined);
  });

  test("배열이 아니면 버린다 — 렌더에서 .map 이 터지지 않게", () => {
    assert.equal(
      attachmentNoticesFromMessageMetadata({ attachment_notices: "nope" }),
      undefined
    );
    assert.equal(
      attachmentNoticesFromMessageMetadata({ attachment_notices: 3 }),
      undefined
    );
  });

  test("문자열이 아닌 항목만 걸러내고 나머지는 살린다", () => {
    assert.deepEqual(
      attachmentNoticesFromMessageMetadata({
        attachment_notices: ["a.png: 제외됨", 5, null, "b.pdf: 제외됨"],
      }),
      ["a.png: 제외됨", "b.pdf: 제외됨"]
    );
  });

  test("전부 걸러지면 undefined", () => {
    assert.equal(
      attachmentNoticesFromMessageMetadata({ attachment_notices: [1, 2] }),
      undefined
    );
  });
});
