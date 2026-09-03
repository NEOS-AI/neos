import assert from "node:assert/strict";
import test from "node:test";
import { readApprovalResumeStream } from "../../lib/approval-stream";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let index = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (index >= chunks.length) {
        controller.close();
        return;
      }
      controller.enqueue(encoder.encode(chunks[index++]));
    },
  });
}

test("event: 줄이 있는 정상 completed 이벤트를 파싱한다", async () => {
  const result = await readApprovalResumeStream(
    streamOf([
      'id: 1\nevent: node_complete\ndata: {"node": "a"}\n\n',
      'id: 2\nevent: completed\ndata: {"response": "final answer"}\n\n',
    ])
  );

  assert.deepEqual(result, { status: "completed", text: "final answer" });
});

test("event: 줄이 없는 타임아웃 payload도 payload.event로 판별한다", async () => {
  // approval_handlers.py의 예전 손-포맷 경로를 흉내낸다: event: 줄이 없고
  // payload 안에 event 키만 있다. 두 관례를 모두 받아야 한다.
  const result = await readApprovalResumeStream(
    streamOf(['data: {"event": "error", "message": "워크플로우 응답 대기 타임아웃"}\n\n'])
  );

  assert.deepEqual(result, {
    status: "error",
    message: "워크플로우 응답 대기 타임아웃",
  });
});

test("직전 이벤트 이름이 이벤트 경계를 넘어 새지 않는다", async () => {
  // node_complete 다음에 event: 줄 없는 데이터가 오면, 초기화되지 않은
  // eventName이 "node_complete"에 머물러 completed/error 어느 쪽으로도
  // 오판되면 안 된다. payload에 event 키도 없으므로 아무 결과도 안 나야
  // 한다 -- 스트림이 종결 이벤트 없이 끝난 것으로 취급된다.
  const result = await readApprovalResumeStream(
    streamOf([
      'event: node_complete\ndata: {"node": "a"}\n\n',
      'data: {"node": "b"}\n\n',
    ])
  );

  assert.equal(result.status, "ended");
});

test("깨진 JSON 줄은 건너뛰고 스트림 전체를 죽이지 않는다", async () => {
  const result = await readApprovalResumeStream(
    streamOf([
      ": keepalive\n\n",
      "data: {not json}\n\n",
      'event: completed\ndata: {"response": "ok after garbage"}\n\n',
    ])
  );

  assert.deepEqual(result, { status: "completed", text: "ok after garbage" });
});

test("completed/error 없이 스트림이 끝나면 성공으로 보고하지 않는다", async () => {
  const result = await readApprovalResumeStream(
    streamOf(['event: node_complete\ndata: {"node": "a"}\n\n'])
  );

  assert.equal(result.status, "ended");
  assert.notEqual(result.status, "completed");
});

test("event: 줄이 있는 error 이벤트도 파싱한다", async () => {
  const result = await readApprovalResumeStream(
    streamOf(['event: error\ndata: {"message": "boom"}\n\n'])
  );

  assert.deepEqual(result, { status: "error", message: "boom" });
});

test("청크 경계로 잘린 이벤트도 이어 붙여 파싱한다", async () => {
  const result = await readApprovalResumeStream(
    streamOf(['event: compl', 'eted\ndata: {"resp', 'onse": "chunked"}\n\n'])
  );

  assert.deepEqual(result, { status: "completed", text: "chunked" });
});
