import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("coding stream renders through the frame-batched projection store only", () => {
  const source = readFileSync(
    "features/coding/stream/use-coding-stream.ts",
    "utf8"
  );

  assert.doesNotMatch(source, /\buseReducer\b/);
  assert.doesNotMatch(source, /\bdispatch\(/);
  assert.doesNotMatch(source, /return \{ state, projection, connection \}/);
  assert.match(source, /store\.applyEvent\(envelope as CodingEvent\)/);
  assert.match(source, /return \{ projection, connection \}/);
});
