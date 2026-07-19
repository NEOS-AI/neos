"""
Document API Example

이 예제는 neos의 문서 관리 REST API를 사용하는 방법을 보여줍니다.

⚠️ 이 라우터의 모든 엔드포인트는 인증을 요구한다
(`get_current_active_user` / `get_owned_document`). 이 스크립트는 자격 증명을
보내지 않으므로, 그대로 실행하면 모든 호출이 401을 반환하고 업로드부터 중단된다.
401은 경로 오류가 아니라 인증 누락이다. 실제로 실행하려면 요청에
`Authorization: Bearer <JWT>` 또는 `X-API-Key` 헤더를 추가해야 한다
(`neos/api/dependencies/auth.py`).
"""

import requests
import json
from pathlib import Path

# API 기본 URL
#
# `documents`가 두 번 반복되는 것은 오타가 아니라 실제 운영 경로다.
# RAG 문서 라우터는 자기 자신이 `APIRouter(prefix="/documents")`이고
# (`neos/api/handlers/document_handlers.py:34`), `neos/main.py:532`가 이를 다시
# `prefix="/api/v1/documents"`로 마운트한다 → `/api/v1/documents/documents/...`
#
# 백엔드의 중복 prefix를 제거해서 "고치면" 안 된다. `/api/v1/documents`는 이미
# 아티팩트 라우터(`neos/api/handlers/artifact_handlers.py:21`, `main.py:548`에서
# `prefix="/api/v1"`로 마운트)가 `GET/DELETE /{document_id}`로 점유하고 있다.
# Starlette은 먼저 등록된 라우트가 이기므로(RAG=532 < 아티팩트=548), 중복 prefix를
# 제거하면 프론트가 실제로 사용 중인 아티팩트 경로를 RAG가 가로챈다.
# 백엔드 테스트도 이 경로를 의도적으로 고정한다:
# `tests/api/handlers/test_document_authorization.py:20,44`
#
# 자세한 배경과 근본 해결(네임스페이스 분리) 계획은 `web/lib/backend-routes.ts` 참조.
BASE_URL = "http://localhost:8518/api/v1/documents/documents"


def example_upload_document():
    """문서 업로드 API 예제"""
    print("=" * 80)
    print("1. 문서 업로드 API")
    print("=" * 80)

    # 테스트 파일 생성
    test_file = Path("test_api_document.txt")
    test_content = """
# OpenAI의 역사

OpenAI는 2015년에 샘 알트만(Sam Altman)과 일론 머스크(Elon Musk) 등에 의해 설립되었습니다.

## 주요 제품

1. GPT-3: 2020년 출시된 대규모 언어 모델
2. GPT-4: 2023년 출시된 멀티모달 모델
3. DALL-E: 이미지 생성 AI
4. Whisper: 음성 인식 모델

OpenAI의 사명은 안전한 인공지능을 개발하는 것입니다.
"""
    test_file.write_text(test_content)

    # 문서 업로드
    url = f"{BASE_URL}/upload"

    with open(test_file, "rb") as f:
        files = {"file": (test_file.name, f, "text/plain")}
        # 소유자는 인증된 사용자에서 결정된다. `user_id` 폼 필드는 deprecated이며
        # 서버가 무시한다 (`document_handlers.py:41,63`).
        data = {"metadata": json.dumps({"category": "AI", "company": "OpenAI"})}

        response = requests.post(url, files=files, data=data)

    if response.status_code == 200:
        result = response.json()
        print(f"✅ 업로드 성공!")
        print(f"   Document ID: {result['document_id']}")
        print(f"   Filename: {result['filename']}")
        print(f"   Status: {result['status']}")
        return result["document_id"]
    else:
        print(f"❌ 업로드 실패: {response.status_code}")
        print(f"   {response.text}")
        return None


def example_list_documents():
    """문서 목록 조회 API 예제"""
    print("\n" + "=" * 80)
    print("2. 문서 목록 조회 API")
    print("=" * 80)

    url = f"{BASE_URL}/"
    # `user_id` 쿼리 파라미터도 deprecated이며 무시된다 (`document_handlers.py:86,102`).
    params = {"limit": 10}

    response = requests.get(url, params=params)

    if response.status_code == 200:
        result = response.json()
        print(f"✅ 총 {result['total']}개의 문서")

        for doc in result["documents"]:
            print(f"\n📄 {doc['filename']}")
            print(f"   ID: {doc['id']}")
            print(f"   상태: {doc['processing_status']}")
            print(f"   KG: {doc['kg_extracted']}, Embedding: {doc['embedding_processed']}")
    else:
        print(f"❌ 조회 실패: {response.status_code}")


def example_get_document(document_id: int):
    """문서 상세 정보 조회 API 예제"""
    print("\n" + "=" * 80)
    print(f"3. 문서 상세 정보 조회 API (ID: {document_id})")
    print("=" * 80)

    url = f"{BASE_URL}/{document_id}"
    response = requests.get(url)

    if response.status_code == 200:
        doc = response.json()
        print(f"✅ 문서 정보:")
        print(f"   파일명: {doc['filename']}")
        print(f"   크기: {doc.get('file_size', 'N/A')} bytes")
        print(f"   타입: {doc.get('mime_type', 'N/A')}")
        print(f"   스토리지: {doc['storage_provider']}")
        print(f"   상태: {doc['processing_status']}")
        print(f"   메타데이터: {doc['metadata']}")
    else:
        print(f"❌ 조회 실패: {response.status_code}")


def example_get_chunks(document_id: int):
    """문서 청크 조회 API 예제"""
    print("\n" + "=" * 80)
    print(f"4. 문서 청크 조회 API (ID: {document_id})")
    print("=" * 80)

    url = f"{BASE_URL}/{document_id}/chunks"
    params = {"limit": 5}

    response = requests.get(url, params=params)

    if response.status_code == 200:
        chunks = response.json()
        print(f"✅ 총 {len(chunks)}개의 청크 (상위 5개)")

        for chunk in chunks:
            preview = chunk["chunk_text"][:100] + "..." if len(chunk["chunk_text"]) > 100 else chunk["chunk_text"]
            print(f"\n   Chunk #{chunk['chunk_index']}:")
            print(f"   {preview}")
    else:
        print(f"❌ 조회 실패: {response.status_code}")


def example_get_knowledge_graph(document_id: int):
    """지식 그래프 조회 API 예제"""
    print("\n" + "=" * 80)
    print(f"5. 지식 그래프 조회 API (ID: {document_id})")
    print("=" * 80)

    url = f"{BASE_URL}/{document_id}/knowledge-graph"
    response = requests.get(url)

    if response.status_code == 200:
        entities = response.json()
        print(f"✅ 총 {len(entities)}개의 엔티티")

        for entity in entities:
            print(f"\n   🔗 {entity['entity_name']} ({entity['entity_type']})")
            print(f"      설명: {entity.get('entity_description', 'N/A')}")
            print(f"      신뢰도: {entity['confidence_score']:.2f}")
            print(f"      관계: {len(entity['relations'])}개")

            # 관계 출력
            for rel in entity["relations"][:3]:  # 최대 3개만
                print(f"         → {rel['relation_type']}: {rel['target_entity_id']}")
    else:
        print(f"❌ 조회 실패: {response.status_code}")


def example_search_documents(query: str):
    """문서 검색 API 예제"""
    print("\n" + "=" * 80)
    print(f"6. 문서 검색 API: '{query}'")
    print("=" * 80)

    url = f"{BASE_URL}/search"
    # 검색 범위는 인증된 사용자로 한정된다. 요청 본문의 `user_id`는 deprecated이며
    # 무시된다 (`document_models.py:79`, `document_handlers.py:289`).
    payload = {"query": query, "top_k": 5}

    response = requests.post(url, json=payload)

    if response.status_code == 200:
        result = response.json()
        print(f"✅ 검색 결과 {len(result['results'])}개")

        for i, res in enumerate(result["results"], 1):
            print(f"\n{i}. 문서: {res['document_name']}")
            print(f"   유사도: {res['similarity_score']:.4f}")
            preview = res["chunk_text"][:200] + "..." if len(res["chunk_text"]) > 200 else res["chunk_text"]
            print(f"   내용: {preview}")
    else:
        print(f"❌ 검색 실패: {response.status_code}")
        print(f"   {response.text}")


def example_delete_document(document_id: int):
    """문서 삭제 API 예제"""
    print("\n" + "=" * 80)
    print(f"7. 문서 삭제 API (ID: {document_id})")
    print("=" * 80)

    url = f"{BASE_URL}/{document_id}"
    response = requests.delete(url)

    if response.status_code == 200:
        print(f"✅ 문서 삭제 완료!")
    else:
        print(f"❌ 삭제 실패: {response.status_code}")


def main():
    """메인 예제 실행"""
    print("\n🚀 NEOS 문서 관리 API 예제\n")

    # 1. 문서 업로드
    document_id = example_upload_document()

    if document_id:
        # 잠시 대기 (문서 처리 시간)
        import time

        print("\n⏳ 문서 처리 대기 중 (5초)...")
        time.sleep(5)

        # 2. 문서 목록 조회
        example_list_documents()

        # 3. 문서 상세 정보
        example_get_document(document_id)

        # 4. 청크 조회
        example_get_chunks(document_id)

        # 5. 지식 그래프 조회
        example_get_knowledge_graph(document_id)

        # 6. 문서 검색
        example_search_documents("OpenAI GPT")

        # 7. 문서 삭제 (주석 처리 - 필요시 해제)
        # example_delete_document(document_id)

    print("\n" + "=" * 80)
    print("✅ 모든 API 예제 완료!")
    print("=" * 80)


if __name__ == "__main__":
    main()
