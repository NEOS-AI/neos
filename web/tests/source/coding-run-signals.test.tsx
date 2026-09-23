import "../dom-setup";
import assert from "node:assert/strict";
import test from "node:test";
import { CodingDetailPanel } from "@/features/coding/components/coding-detail-panel";
import { CodingRunSignals } from "@/features/coding/components/coding-run-signals";
import { emptyProjection } from "@/features/coding/stream/projection-reducer";
import type { CodingProjectionState } from "@/features/coding/types/projection";
import { renderComponent } from "../render";

const projection = (
  overrides: Partial<CodingProjectionState>
): CodingProjectionState => ({
  ...emptyProjection("ct_1"),
  ...overrides,
});

test("nothing to say renders nothing", async () => {
  const host = await renderComponent(
    <CodingRunSignals projection={projection({})} />
  );
  assert.equal(host.textContent, "");
});

// K4a put the note in the projection and no component ever read it. This is
// the test that would have caught that.
test("the model's running note reaches the screen", async () => {
  const host = await renderComponent(
    <CodingRunSignals
      projection={projection({ thinkingStatus: "Reading the parser" })}
    />
  );
  assert.equal(
    host.querySelector('[data-testid="coding-thinking-status"]')?.textContent,
    "Reading the parser"
  );
});

test("a refusal says the run will not retry", async () => {
  const host = await renderComponent(
    <CodingRunSignals
      projection={projection({
        refusal: { run_id: "cr_1", stop_category: "cyber", seq: 4 },
      })}
    />
  );
  const text =
    host.querySelector('[data-testid="coding-refusal"]')?.textContent ?? "";
  assert.match(text, /declined/);
  assert.match(text, /cyber/);
  assert.match(text, /will not retry/);
});

test("a stalled child shows as ended, with its reason", async () => {
  const host = await renderComponent(
    <CodingRunSignals
      projection={projection({
        childrenById: {
          sa_1: {
            run_id: "sa_1",
            spec: "explore",
            status: "failed",
            turn_count: 2,
            tool_count: 3,
            parent_tool_call_id: "t1",
            end_reason: "stalled",
          },
        },
      })}
    />
  );
  const rows = host.querySelectorAll('[data-testid="coding-subagent"]');
  assert.equal(rows.length, 1);
  assert.match(rows[0]?.textContent ?? "", /failed · stalled/);
});

test("a tool row carries its Jev verdict and whether it was enforced", async () => {
  const host = await renderComponent(
    <CodingDetailPanel
      phaseId="phase:implement:1"
      projection={projection({
        phases: [
          {
            phase_id: "phase:implement:1",
            run_id: "cr_1",
            kind: "implement",
            attempt: 1,
            status: "active",
            started_at: "2026-09-23T00:00:00Z",
            completed_at: null,
          },
        ],
        toolsById: {
          t1: {
            tool_call_id: "t1",
            run_id: "cr_1",
            status: "completed",
            result: null,
            name: "execute.v1",
          },
          t2: {
            tool_call_id: "t2",
            run_id: "cr_1",
            status: "completed",
            result: null,
            name: "read_file.v1",
          },
        },
        toolRisksById: {
          t1: {
            kind: "scored",
            tool_call_id: "t1",
            seq: 3,
            tool: "execute.v1",
            probability: 0.623,
            band: "middle",
            low_below: 0.3,
            high_at_or_above: 0.8,
            static_outcome: "allow",
            would_be_outcome: "require_approval",
            enforced: false,
            rubric_digest: "f5faf377",
            model: "jev-1.13.0",
          },
        },
      })}
    />
  );
  // Found by structure, not by substring over the whole panel (roadmap §14,
  // the K2b lesson): the verdict must sit on t1's row and on no other.
  const lines = host.querySelectorAll('[data-testid="coding-tool-risk"]');
  assert.equal(lines.length, 1);
  assert.match(lines[0]?.textContent ?? "", /jev 0\.62 · middle/);
  assert.match(lines[0]?.textContent ?? "", /shadow/);
  assert.match(lines[0]?.parentElement?.textContent ?? "", /execute\.v1/);
});
