import { strict as assert } from "node:assert/strict";
import { describe, test } from "node:test";

import { isNeosHarnessEvent } from "../../lib/open-responses-types";

describe("OpenResponses NEOS harness event types", () => {
  test("accepts harness events and rejects ordinary workflow progress", () => {
    assert.equal(
      isNeosHarnessEvent({
        type: "neos:harness",
        event: "harness_started",
        report_id: "report-1",
        data: { mode: "gate" },
      }),
      true
    );

    assert.equal(
      isNeosHarnessEvent({
        type: "neos:workflow_progress",
        progress_percent: 50,
        conversation_id: "conversation-1",
      }),
      false
    );
  });
});
