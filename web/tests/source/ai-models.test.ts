import { strict as assert } from "node:assert/strict";
import { describe, test } from "node:test";

import {
  chatModels,
  DEFAULT_CHAT_MODEL,
  mapToBackendModelName,
} from "../../lib/ai/models";

describe("curated AI models", () => {
  test("defaults chats to Claude Sonnet 5", () => {
    assert.equal(DEFAULT_CHAT_MODEL, "anthropic/claude-sonnet-5");
  });

  test("exposes the current models with accurate picker labels", () => {
    const currentIds = new Set([
      "anthropic/claude-sonnet-5",
      "anthropic/claude-opus-5",
      "openai/gpt-5.6-terra",
      "openai/gpt-5.6-sol",
    ]);

    assert.deepEqual(
      chatModels
        .filter((model) => currentIds.has(model.id))
        .map(({ id, name, provider }) => ({ id, name, provider })),
      [
        {
          id: "anthropic/claude-sonnet-5",
          name: "Claude Sonnet 5",
          provider: "anthropic",
        },
        {
          id: "anthropic/claude-opus-5",
          name: "Claude Opus 5",
          provider: "anthropic",
        },
        {
          id: "openai/gpt-5.6-terra",
          name: "GPT-5.6 Terra",
          provider: "openai",
        },
        {
          id: "openai/gpt-5.6-sol",
          name: "GPT-5.6 Sol",
          provider: "openai",
        },
      ]
    );
  });

  test("maps current gateway IDs to their exact backend IDs", () => {
    assert.deepEqual(
      [
        "anthropic/claude-sonnet-5",
        "anthropic/claude-opus-5",
        "openai/gpt-5.6-terra",
        "openai/gpt-5.6-sol",
      ].map((id) => [id, mapToBackendModelName(id)]),
      [
        ["anthropic/claude-sonnet-5", "claude-sonnet-5"],
        ["anthropic/claude-opus-5", "claude-opus-5"],
        ["openai/gpt-5.6-terra", "gpt-5.6-terra"],
        ["openai/gpt-5.6-sol", "gpt-5.6-sol"],
      ]
    );
  });

  test("does not present Claude Opus 4.5 as Claude Opus 4.6", () => {
    const opus45 = chatModels.find(
      (model) => model.id === "anthropic/claude-opus-4.5"
    );

    assert.notEqual(opus45?.name, "Claude Opus 4.6");
  });

  test("still maps retired picker IDs so stored selections keep working", () => {
    // Retired from the picker, but existing chat-model cookies and stored
    // conversations still send this gateway ID. It used to resolve to
    // claude-opus-4-6, which the backend catalog has since retired for having
    // no known price, so it now serves claude-opus-5.
    assert.equal(
      mapToBackendModelName("anthropic/claude-opus-4.5"),
      "claude-opus-5"
    );
  });

  test("never maps onto a model the backend catalog retired", () => {
    // These were selectable without a price, so their cost aggregated as zero.
    const retired = new Set([
      "claude-sonnet-4-6",
      "claude-opus-4-6",
      "gpt-5-mini-2025-08-07",
      "gpt-5-2025-08-07",
      "o3",
      "o3-mini",
    ]);

    for (const model of chatModels) {
      assert.equal(
        retired.has(mapToBackendModelName(model.id)),
        false,
        `${model.id} maps onto retired backend model ${mapToBackendModelName(model.id)}`
      );
    }
  });

  test("never returns a gateway-prefixed ID to the backend", () => {
    for (const model of chatModels) {
      assert.equal(
        mapToBackendModelName(model.id).includes("/"),
        false,
        `${model.id} has no backend mapping`
      );
    }
  });

  test("only offers providers the backend can actually serve", () => {
    // The backend infers the provider from the model name and only recognizes
    // "gpt" and "claude"; anything else silently falls back to Anthropic and
    // fails at request time.
    const servable = chatModels.filter((model) => {
      const backendId = mapToBackendModelName(model.id).toLowerCase();
      return backendId.includes("gpt") || backendId.includes("claude");
    });

    assert.deepEqual(
      chatModels.map((model) => model.id),
      servable.map((model) => model.id)
    );
  });

  test("labels the legacy entries as the model actually served", () => {
    const labelled = new Map(
      chatModels.map((model) => [model.id, model.name])
    );

    assert.equal(labelled.get("openai/gpt-4o"), "GPT-4o");
    assert.equal(labelled.get("openai/gpt-4o-mini"), "GPT-4o Mini");
    assert.equal(
      labelled.get("anthropic/claude-sonnet-4.5-thinking"),
      "Claude Sonnet 4.5 (Thinking)"
    );
  });

  test("keeps the reasoning entry detectable by prompt selection", () => {
    // lib/ai/prompts.ts branches on the id containing "reasoning"/"thinking"
    const reasoning = chatModels.filter((model) => model.provider === "reasoning");

    assert.ok(reasoning.length > 0);
    for (const model of reasoning) {
      assert.ok(
        model.id.includes("thinking") || model.id.includes("reasoning"),
        `${model.id} would lose its reasoning prompt`
      );
    }
  });

  test("retires unsupported selections onto the default model", () => {
    const fallback = mapToBackendModelName(DEFAULT_CHAT_MODEL);

    for (const retired of [
      "google/gemini-2.5-flash-lite",
      "google/gemini-3-pro-preview",
      "xai/grok-4.1-fast-non-reasoning",
      "xai/grok-code-fast-1-thinking",
    ]) {
      assert.equal(mapToBackendModelName(retired), fallback);
    }
  });

  test("keeps retired OpenAI and reasoning IDs on their previous models", () => {
    assert.equal(mapToBackendModelName("openai/gpt-4.1"), "gpt-4o");
    assert.equal(mapToBackendModelName("openai/gpt-4.1-mini"), "gpt-4o-mini");
    assert.equal(
      mapToBackendModelName("anthropic/claude-3.7-sonnet-thinking"),
      "claude-sonnet-4-5-20250929"
    );
  });
});
