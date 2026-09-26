import assert from "node:assert/strict";
import test from "node:test";
import {
  effortOptions,
  effortRequest,
  shouldShowEffort,
} from "@/lib/ai/effort";
import type { CatalogModelOut } from "@/lib/ai/models";

const base: CatalogModelOut = {
  id: "anthropic/claude-opus-5.5",
  catalog_id: "claude-opus-5-5",
  name: "Claude Opus 5.5",
  provider: "anthropic",
  description: "",
  thinking: "adaptive",
  vision: true,
  role_alias: null,
  default: false,
  effort_levels: ["low", "medium", "high"],
  effort_default: "high",
};

test("a model without levels hides the selector", () => {
  // Review Focus 5
  assert.equal(shouldShowEffort({ ...base, effort_levels: [] }), false);
  assert.equal(shouldShowEffort(undefined), false);
  assert.equal(shouldShowEffort(base), true);
});

test("a row from an older backend without effort fields hides the selector", () => {
  const { effort_levels: _dropped, ...legacy } = base;
  assert.equal(shouldShowEffort(legacy as CatalogModelOut), false);
});

test("options start with the default and keep API labels", () => {
  assert.deepEqual(effortOptions(base), [
    { value: null, label: "Default (high)" },
    { value: "low", label: "low" },
    { value: "medium", label: "medium" },
    { value: "high", label: "high" },
  ]);
  assert.equal(
    effortOptions({ ...base, effort_default: null })[0].label,
    "Default"
  );
});

test("choosing default deletes, choosing a level puts", () => {
  const del = effortRequest("claude-opus-5-5", null);
  assert.equal(del.url, "/api/model-preferences/claude-opus-5-5");
  assert.equal(del.init.method, "DELETE");

  const put = effortRequest("claude-opus-5-5", "low");
  assert.equal(put.init.method, "PUT");
  assert.equal(put.init.body, JSON.stringify({ effort: "low" }));
});
