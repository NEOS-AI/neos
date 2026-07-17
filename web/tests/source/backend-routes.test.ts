import { strict as assert } from "node:assert/strict";
import { describe, test } from "node:test";

import {
  ARTIFACTS_BASE,
  RAG_DOCUMENT_UPLOAD_PATH,
  RAG_DOCUMENTS_BASE,
  ragDocumentPath,
} from "../../lib/backend-routes";

/**
 * 회귀 테스트: 파일 첨부 업로드가 405로 죽던 문제(FE_AUDIT_260717 §3.1).
 *
 * RAG 문서 라우터의 실제 경로는 double-prefix를 포함한다. 백엔드의 중복 prefix를
 * 제거하면 아티팩트 라우터의 `GET/DELETE /api/v1/documents/{id}`를 가로채므로
 * (Starlette은 먼저 등록된 라우트가 이긴다, `neos/main.py:532` < `:548`)
 * 프론트가 실제 경로를 호출하는 쪽이 정답이다. 자세한 근거는 lib/backend-routes.ts 주석.
 *
 * 백엔드 근거: tests/api/handlers/test_document_authorization.py:20
 *   BASE_PATH = "/api/v1/documents/documents"
 */
describe("backend document routes", () => {
  test("RAG 업로드 경로는 백엔드 테스트가 고정한 double-prefix와 일치한다", () => {
    // 백엔드 test_document_authorization.py:20의 BASE_PATH와 동일해야 한다
    assert.equal(RAG_DOCUMENTS_BASE, "/api/v1/documents/documents");
    assert.equal(
      RAG_DOCUMENT_UPLOAD_PATH,
      "/api/v1/documents/documents/upload"
    );
  });

  test("RAG 업로드 경로는 아티팩트 네임스페이스와 겹치지 않는다", () => {
    // 회귀 방지: `/api/v1/documents/upload`로 되돌아가면 405가 재발한다
    assert.notEqual(RAG_DOCUMENT_UPLOAD_PATH, `${ARTIFACTS_BASE}/upload`);
  });

  test("storage_url 조회는 아티팩트가 아니라 RAG 라우터를 향한다", () => {
    // 아티팩트의 GET /api/v1/documents/{id}는 storage_url이 없는 배열을 반환한다
    assert.equal(ragDocumentPath(42), "/api/v1/documents/documents/42");
    assert.notEqual(ragDocumentPath(42), `${ARTIFACTS_BASE}/42`);
  });

  test("문서 id가 문자열이어도 동일한 경로를 만든다", () => {
    assert.equal(ragDocumentPath("abc"), "/api/v1/documents/documents/abc");
  });
});
