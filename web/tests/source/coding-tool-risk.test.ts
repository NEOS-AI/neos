import assert from "node:assert/strict";
import test from "node:test";
import { describeToolRisk } from "../../features/coding/components/tool-risk";
import type { CodingToolRiskView } from "../../features/coding/types/projection";

type Scored = Extract<CodingToolRiskView, { kind: "scored" }>;

const scored = (overrides: Partial<Scored> = {}): Scored => ({
  kind: "scored",
  tool_call_id: "t1",
  seq: 1,
  tool: "execute.v1",
  probability: 0.62,
  band: "mid",
  low_below: 0.3,
  high_at_or_above: 0.8,
  static_outcome: "allow",
  would_be_outcome: "require_approval",
  enforced: false,
  rubric_digest: "f5faf377",
  model: "jev-1.13.0",
  ...overrides,
});

test("an unchanged outcome adds nothing to the badge", () => {
  assert.equal(
    describeToolRisk(
      scored({ probability: 0.1, band: "low", would_be_outcome: "allow" })
    ),
    null
  );
  // An outcome the payload did not carry is not a change either.
  assert.equal(describeToolRisk(scored({ would_be_outcome: null })), null);
  assert.equal(describeToolRisk(scored({ static_outcome: null })), null);
});

test("shadow speaks in the counterfactual and names what the static policy did", () => {
  const sentence = describeToolRisk(scored());
  assert.ok(sentence);
  assert.match(sentence, /^Shadow:/);
  assert.match(sentence, /would have required approval/);
  assert.match(sentence, /static policy allowed it/);
  assert.doesNotMatch(sentence, /Gate narrowed/);
});

test("a shadow deny reads as a denial that did not happen", () => {
  const sentence = describeToolRisk(
    scored({ probability: 0.91, band: "high", would_be_outcome: "deny" })
  );
  assert.match(sentence ?? "", /would have been denied/);
});

test("an enforced deny says what happened and shows the threshold it crossed", () => {
  const sentence = describeToolRisk(
    scored({
      probability: 0.91,
      band: "high",
      would_be_outcome: "deny",
      enforced: true,
    })
  );
  assert.ok(sentence);
  assert.match(sentence, /^Gate narrowed allow → deny/);
  assert.match(sentence, /p=0\.91 ≥ 0\.80/);
  assert.doesNotMatch(sentence, /Shadow|would have/);
});

test("an unattended mid-band deny cites the low boundary, not the high one", () => {
  const sentence = describeToolRisk(
    scored({ probability: 0.55, would_be_outcome: "deny", enforced: true })
  );
  assert.match(sentence ?? "", /p=0\.55 ≥ 0\.30/);
});

test("an enforced approval requirement carries no denial evidence", () => {
  const sentence = describeToolRisk(scored({ enforced: true }));
  assert.equal(sentence, "Gate narrowed allow → require_approval.");
});

test("an unavailable verdict is never silent, with or without details", () => {
  const unavailable = (
    reason: string | null,
    static_outcome: string | null
  ): CodingToolRiskView => ({
    kind: "unavailable",
    tool_call_id: "t1",
    seq: 1,
    tool: "execute.v1",
    reason,
    static_outcome,
    enforced: true,
  });

  const full = describeToolRisk(unavailable("TimeoutError", "allow"));
  assert.match(full ?? "", /TimeoutError/);
  assert.match(full ?? "", /static policy's allow stood/);

  const bare = describeToolRisk(unavailable(null, null));
  assert.ok(bare);
  assert.match(bare, /static policy stood/);
});

test("an unknown outcome code passes through instead of throwing", () => {
  const sentence = describeToolRisk(
    scored({ static_outcome: "quarantine", would_be_outcome: "escalate" })
  );
  assert.match(sentence ?? "", /escalate/);
  assert.match(sentence ?? "", /quarantine/);
});
