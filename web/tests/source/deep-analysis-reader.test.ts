import assert from "node:assert/strict";
import test from "node:test";
import type { DeepAnalysisJobEvent } from "../../lib/deep-analysis/events";
import { readDeepAnalysisEventStream } from "../../lib/deep-analysis/reader";

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

test("SSE 본문에서 검증된 이벤트만 뽑는다", async () => {
  const seen: DeepAnalysisJobEvent[] = [];
  await readDeepAnalysisEventStream(
    streamOf([
      ": keepalive\n\n",
      'data: {"seq":1,"type":"job_started","payload":{}}\n\n',
      'data: {"seq":2,"type":"question_opened","payload":{"text":"q"}}\n\n',
      "data: {not json}\n\n",
      "data: [DONE]\n\n",
    ]),
    (event) => {
      seen.push(event);
    }
  );

  assert.deepEqual(
    seen.map((event) => [event.seq, event.kind]),
    [
      [1, "job_started"],
      [2, "question_opened"],
    ]
  );
});

test("청크 경계로 잘린 이벤트를 이어 붙인다", async () => {
  const seen: DeepAnalysisJobEvent[] = [];
  await readDeepAnalysisEventStream(
    streamOf(['data: {"seq":7,"type":"claim_ver', 'ified","payload":{}}\n\n']),
    (event) => {
      seen.push(event);
    }
  );

  assert.equal(seen.length, 1);
  assert.equal(seen[0].kind, "claim_verified");
  assert.equal(seen[0].seq, 7);
});

test("콜백이 false를 반환하면 즉시 읽기를 멈춘다", async () => {
  const seen: DeepAnalysisJobEvent[] = [];
  await readDeepAnalysisEventStream(
    streamOf([
      'data: {"seq":1,"type":"job_started","payload":{}}\n',
      'data: {"seq":2,"type":"job_completed","payload":{"report_markdown":"# R"}}\n',
      'data: {"seq":3,"type":"never_read","payload":{}}\n',
    ]),
    (event) => {
      seen.push(event);
      return event.kind !== "job_completed";
    }
  );

  assert.deepEqual(
    seen.map((event) => event.kind),
    ["job_started", "job_completed"]
  );
});

test("빈 스트림도 정상 종료한다", async () => {
  const result = await readDeepAnalysisEventStream(streamOf([]), () => {
    assert.fail("이벤트가 없어야 한다");
  });
  assert.deepEqual(result, { ended: true });
});
