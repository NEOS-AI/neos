/**
 * 백엔드 API 경로 상수 및 빌더
 *
 * 백엔드 경로를 한 곳에 모아 FE↔BE 계약 불일치를 회귀 테스트로 고정한다.
 *
 * ## ⚠️ RAG 문서 라우터의 "double-prefix"는 오타가 아니라 실제 운영 경로다
 *
 * 백엔드에는 `documents`라는 이름을 공유하는 **서로 다른 두 라우터**가 있다:
 *
 * 1. **RAG 문서 라우터** (`neos/api/handlers/document_handlers.py`)
 *    - 라우터 자체가 `APIRouter(prefix="/documents")` (`document_handlers.py` 의 `router`)
 *    - `neos/main.py` 의 `document_router` 마운트가 다시 `prefix="/api/v1/documents"`로 마운트
 *    - → 실제 경로: `/api/v1/documents/documents/...`
 *
 * 2. **아티팩트 라우터** (`neos/api/handlers/artifact_handlers.py`)
 *    - `APIRouter(prefix="/documents")` (`artifact_handlers.py` 의 `router`)
 *    - `neos/main.py` 의 `artifact_router` 마운트가 `prefix="/api/v1"`로 마운트
 *    - → 실제 경로: `/api/v1/documents/...`
 *
 * ### 왜 백엔드의 중복 prefix를 제거하지 않았는가
 *
 * RAG 라우터의 중복 prefix를 제거하면 두 라우터가 **같은 네임스페이스**를 놓고 충돌한다.
 * RAG 라우터는 `GET /{document_id}`, `DELETE /{document_id}`를 갖고
 * (`document_handlers.py` 의 `get_document` · `delete_document`), 아티팩트 라우터도 동일 경로를 갖는다
 * (`artifact_handlers.py` 의 같은 두 경로). Starlette은 **먼저 등록된 라우트가 이긴다**.
 * `main.py` 에서 RAG 가 아티팩트보다 먼저 등록되므로, 중복 prefix를 제거하면
 * `GET/DELETE /api/v1/documents/{id}`가 아티팩트 → RAG로 **가로채진다**.
 *
 * 이 경로들은 프론트가 **현재 정상 동작 중인 아티팩트 기능**에 쓰고 있다
 * (`app/(chat)/api/document/route.ts`, `lib/ai/tools/update-document.ts` 등).
 * 즉 백엔드 prefix 제거는 죽어 있는 업로드를 살리는 대신 **살아 있는 아티팩트를 죽인다.**
 *
 * 백엔드 테스트도 이 경로를 의도적으로 고정하고 있다:
 * `tests/api/handlers/test_document_authorization.py:20,44`
 * ("Preserve the production double-prefix while its URL design remains out of scope.")
 *
 * 근본 해결은 네임스페이스 분리(`/assets` vs `/artifacts`)이며, 이는 이미 별도 설계 문서에
 * 계획돼 있다: `docs/superpowers/specs/2026-07-01-neos-research-platform-design.md:92`.
 * 그 재설계 전까지 프론트는 **실제 경로**를 호출한다.
 */

/** RAG 문서 라우터의 실제 베이스 경로 (double-prefix 포함 — 위 주석 참조) */
export const RAG_DOCUMENTS_BASE = "/api/v1/documents/documents";

/** 아티팩트 라우터의 베이스 경로 */
export const ARTIFACTS_BASE = "/api/v1/documents";

/** RAG 문서 업로드: `POST /api/v1/documents/documents/upload` */
export const RAG_DOCUMENT_UPLOAD_PATH = `${RAG_DOCUMENTS_BASE}/upload`;

/**
 * RAG 문서 상세 조회: `GET /api/v1/documents/documents/{id}`
 *
 * `storage_url`을 가진 것은 RAG의 `DocumentInfo`
 * (`neos/api/models/document_models.py`)뿐이다. 아티팩트 라우터의
 * `GET /api/v1/documents/{id}`는 `List[DocumentResponse]`를 반환하며
 * `storage_url`이 없다 — 그쪽으로 조회하면 `undefined`가 된다.
 */
export function ragDocumentPath(documentId: string | number): string {
  return `${RAG_DOCUMENTS_BASE}/${documentId}`;
}
