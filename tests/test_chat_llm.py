"""
Chat LLM Integration Tests

실제 LLM 통합 및 비용 추적 테스트
"""

import asyncio
import requests
import json
import websockets
from typing import Optional

BASE_URL = "http://localhost:8518/api/v1/chat"
WS_URL = "ws://localhost:8518/api/v1/chat"


class ChatTester:
    """채팅 API 테스터"""

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.conversation_id: Optional[str] = None
        self.user_id = "test_user_001"

    def test_create_conversation(self):
        """대화 생성 테스트"""
        print("\n=== 대화 생성 테스트 ===")

        response = requests.post(
            f"{self.base_url}/conversations",
            json={
                "user_id": self.user_id,
                "model_name": "claude-sonnet-4-5-20250929",
                "system_prompt": "당신은 친절한 Python 전문가입니다.",
                "temperature": 0.7,
            },
        )

        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()

        self.conversation_id = data["conversation_id"]
        print(f"✅ 대화 생성 성공: {self.conversation_id}")
        print(f"   모델: {data['model_name']}")
        print(f"   Temperature: {data['temperature']}")

        return data

    def test_send_message_sync(self):
        """동기 메시지 전송 테스트 (실제 LLM 호출)"""
        print("\n=== 동기 메시지 전송 테스트 ===")

        if not self.conversation_id:
            print("❌ 먼저 대화를 생성하세요")
            return

        response = requests.post(
            f"{self.base_url}/conversations/{self.conversation_id}/messages",
            json={"content": "Python에서 리스트 컴프리헨션이 뭔가요?", "role": "user"},
        )

        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()

        print("✅ 메시지 전송 성공")
        print(f"\n사용자: {data['user_message']['content']}")
        print(f"\nAI: {data['assistant_message']['content'][:200]}...")

        # 비용 정보 확인
        metadata = data["assistant_message"]["metadata"]
        print(f"\n📊 통계:")
        print(f"   토큰: {data['assistant_message']['total_tokens']}")
        print(f"   비용: ${metadata['cost_usd']:.6f}")
        print(f"   지연시간: {metadata['latency_ms']}ms")
        print(f"   완료사유: {metadata.get('finish_reason', 'N/A')}")

        return data

    def test_stream_message(self):
        """스트리밍 메시지 테스트"""
        print("\n=== 스트리밍 메시지 테스트 ===")

        if not self.conversation_id:
            print("❌ 먼저 대화를 생성하세요")
            return

        url = f"{self.base_url}/conversations/{self.conversation_id}/messages/stream"

        with requests.post(
            url, json={"content": "Quick Sort 알고리즘을 간단히 설명해주세요.", "role": "user"}, stream=True
        ) as response:
            print("🤖 AI 응답 (스트리밍):\n")

            total_tokens = 0
            cost_usd = 0.0

            for line in response.iter_lines():
                if line:
                    line = line.decode("utf-8")
                    if line.startswith("data: "):
                        data = json.loads(line[6:])

                        if data["type"] == "start":
                            print("(스트리밍 시작...)\n")

                        elif data["type"] == "content":
                            print(data["content"], end="", flush=True)

                        elif data["type"] == "complete":
                            total_tokens = data["metadata"]["total_tokens"]
                            cost_usd = data["metadata"]["cost_usd"]
                            print("\n\n✅ 스트리밍 완료")

                        elif data["type"] == "error":
                            print(f"\n❌ 에러: {data['error']}")
                            return

            print(f"\n📊 통계:")
            print(f"   토큰: {total_tokens}")
            print(f"   비용: ${cost_usd:.6f}")

    async def test_websocket(self):
        """WebSocket 테스트"""
        print("\n=== WebSocket 테스트 ===")

        if not self.conversation_id:
            print("❌ 먼저 대화를 생성하세요")
            return

        uri = f"{WS_URL}/ws/{self.conversation_id}"

        try:
            async with websockets.connect(uri) as websocket:
                # 연결 확인
                response = await websocket.recv()
                data = json.loads(response)
                print(f"✅ WebSocket 연결: {data['type']}")
                print(f"   모델: {data['model']}")

                # 메시지 전송
                await websocket.send(
                    json.dumps(
                        {
                            "type": "message",
                            "content": "WebSocket으로 메시지를 보냅니다. 간단히 답변해주세요.",
                            "metadata": {},
                        }
                    )
                )

                print("\n🤖 AI 응답 (WebSocket):\n")

                # 응답 수신
                while True:
                    response = await websocket.recv()
                    data = json.loads(response)

                    if data["type"] == "user_message_saved":
                        print("✅ 사용자 메시지 저장됨\n")

                    elif data["type"] == "assistant_start":
                        pass

                    elif data["type"] == "assistant_content":
                        print(data["content"], end="", flush=True)

                    elif data["type"] == "assistant_complete":
                        print("\n\n✅ 완료")
                        print(f"\n📊 통계:")
                        print(f"   토큰: {data['usage']['total_tokens']}")
                        print(f"   비용: ${data['cost_usd']:.6f}")
                        print(f"   지연시간: {data['latency_ms']}ms")
                        break

                    elif data["type"] == "assistant_error":
                        print(f"\n❌ 에러: {data['error']}")
                        break

        except Exception as e:
            print(f"❌ WebSocket 에러: {e}")

    def test_get_analytics(self):
        """분석 데이터 조회 테스트"""
        print("\n=== 분석 데이터 조회 ===")

        if not self.conversation_id:
            print("❌ 먼저 대화를 생성하세요")
            return

        # 대화 분석
        response = requests.get(
            f"{self.base_url}/conversations/{self.conversation_id}/analytics"
        )

        if response.status_code == 200:
            data = response.json()
            print("📊 대화 통계:")
            print(f"   총 메시지: {data.get('total_messages', 0)}")
            print(f"   총 토큰: {data.get('total_tokens_used', 0)}")
            print(f"   총 비용: ${data.get('total_cost', 0):.6f}")
            print(f"   평균 응답시간: {data.get('average_response_time_ms', 0)}ms")
        else:
            print(f"⚠️ 분석 데이터 없음 (아직 집계 전)")

        # 사용자 통계
        response = requests.get(f"{self.base_url}/users/{self.user_id}/statistics")

        if response.status_code == 200:
            data = response.json()
            print("\n👤 사용자 통계:")
            print(f"   총 대화: {data['total_conversations']}")
            print(f"   활성 대화: {data['active_conversations']}")
            print(f"   총 메시지: {data['total_messages']}")
            print(f"   총 비용: ${data['total_cost']:.2f}")

    def test_list_conversations(self):
        """대화 목록 조회 테스트"""
        print("\n=== 대화 목록 조회 ===")

        response = requests.get(
            f"{self.base_url}/users/{self.user_id}/conversations?limit=10"
        )

        assert response.status_code == 200
        data = response.json()

        print(f"✅ 총 {data['total_count']}개 대화")

        for conv in data["conversations"][:3]:
            print(f"\n   대화: {conv['conversation_id'][:8]}...")
            print(f"   제목: {conv['title'] or '(제목 없음)'}")
            print(f"   메시지: {conv['message_count']}개")
            if conv.get("last_message_preview"):
                print(f"   마지막 메시지: {conv['last_message_preview'][:50]}...")


def run_all_tests():
    """모든 테스트 실행"""
    print("=" * 60)
    print("Chat LLM Integration Tests")
    print("=" * 60)

    tester = ChatTester()

    try:
        # 1. 대화 생성
        tester.test_create_conversation()

        # 2. 동기 메시지 전송 (실제 LLM)
        tester.test_send_message_sync()

        # 3. 스트리밍 메시지
        tester.test_stream_message()

        # 4. WebSocket
        asyncio.run(tester.test_websocket())

        # 5. 분석 데이터
        tester.test_get_analytics()

        # 6. 대화 목록
        tester.test_list_conversations()

        print("\n" + "=" * 60)
        print("✅ 모든 테스트 완료!")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n❌ 테스트 실패: {e}")
    except Exception as e:
        print(f"\n❌ 에러: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    # API 서버가 실행 중이어야 합니다
    # uvicorn neos.main:app --reload --port 8518

    run_all_tests()
