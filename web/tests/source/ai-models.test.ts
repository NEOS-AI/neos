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
});
