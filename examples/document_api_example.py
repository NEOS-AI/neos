"""
Document API Example

이 예제는 neos의 문서 관리 REST API를 사용하는 방법을 보여줍니다.
"""

import requests
import json
from pathlib import Path

# API 기본 URL
BASE_URL = "http://localhost:8518/api/v1/documents"


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
        data = {
            "user_id": "api_test_user",
            "metadata": json.dumps({"category": "AI", "company": "OpenAI"}),
        }

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


def example_list_documents(user_id="api_test_user"):
    """문서 목록 조회 API 예제"""
    print("\n" + "=" * 80)
    print("2. 문서 목록 조회 API")
    print("=" * 80)

    url = f"{BASE_URL}/"
    params = {"user_id": user_id, "limit": 10}

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


def example_search_documents(query: str, user_id="api_test_user"):
    """문서 검색 API 예제"""
    print("\n" + "=" * 80)
    print(f"6. 문서 검색 API: '{query}'")
    print("=" * 80)

    url = f"{BASE_URL}/search"
    payload = {"query": query, "top_k": 5, "user_id": user_id}

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
        example_search_documents("OpenAI GPT", user_id="api_test_user")

        # 7. 문서 삭제 (주석 처리 - 필요시 해제)
        # example_delete_document(document_id)

    print("\n" + "=" * 80)
    print("✅ 모든 API 예제 완료!")
    print("=" * 80)


if __name__ == "__main__":
    main()
