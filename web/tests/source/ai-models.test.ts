import { strict as assert } from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  chatModels,
  DEFAULT_CHAT_MODEL,
  mapToBackendModelName,
  RETIRED_MODEL_MAP,
} from "../../lib/ai/models";

/**
 * Derives "which backend model ids the catalog will actually accept" from
 * the real catalog source (`neos/config/models.yaml`), instead of a
 * hand-typed list of retired names. Finding 1 slipped past the old
 * hand-maintained `retired` set precisely because that set never covered
 * `selectable: false` entries — see git history for
 * `web/tests/source/ai-models.test.ts` around 2026-09-04.
 *
 * This is a light-weight structural scan, not a full YAML parser (no `yaml`
 * package is a web/ dependency). It only needs to know, per top-level key
 * under `models:`, whether that key's block contains `selectable: false`.
 * The `models:` section is bounded by the next top-level key
 * (`anthropic_families:`) so unrelated sections (aliases, families) can't
 * leak in.
 */
function loadSelectableBackendModelIds(): Set<string> {
  const yamlPath = fileURLToPath(
    new URL("../../../neos/config/models.yaml", import.meta.url)
  );
  const source = readFileSync(yamlPath, "utf8");

  const modelsStart = source.indexOf("\nmodels:\n");
  const modelsEnd = source.indexOf("\nanthropic_families:\n");
  assert.ok(
    modelsStart >= 0 && modelsEnd > modelsStart,
    "neos/config/models.yaml structure changed — can't locate the models: block"
  );
  const modelsBlock = source.slice(modelsStart, modelsEnd);

  // Top-level (2-space indent) keys, quoted or bare (e.g. "llama3.1:8b":).
  const keyRe = /^ {2}(?:"([^"\n]+)"|([^"\s:][^:\n]*?)):\s*$/gm;
  const keys: { name: string; index: number }[] = [];
  let match: RegExpExecArray | null;
  // biome-ignore lint/suspicious/noAssignInExpressions: standard regex-exec-in-loop idiom
  while ((match = keyRe.exec(modelsBlock))) {
    keys.push({ name: match[1] ?? match[2], index: match.index });
  }
  assert.ok(
    keys.length > 5,
    "found suspiciously few model keys — the scan regex likely broke"
  );

  const selectable = new Set<string>();
  for (let i = 0; i < keys.length; i++) {
    const end = i + 1 < keys.length ? keys[i + 1].index : modelsBlock.length;
    const body = modelsBlock.slice(keys[i].index, end);
    // Field lines are 4-space indented; comments describing an *upcoming*
    // entry sit at 2-space indent and can themselves contain the literal
    // text "selectable: false" in prose (e.g. claude-opus-4-8's docstring).
    // Anchor to the real field line only.
    if (!/^ {4}selectable:\s*false\s*$/m.test(body)) {
      selectable.add(keys[i].name);
    }
  }
  return selectable;
}

const SELECTABLE_BACKEND_MODEL_IDS = loadSelectableBackendModelIds();

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

  test("never maps onto a model the backend catalog would reject", () => {
    // Covers both "retired / never existed" (not in models.yaml at all) and
    // "exists but selectable: false" (Finding 1: gpt-4o / gpt-4o-mini) —
    // anything not in SELECTABLE_BACKEND_MODEL_IDS fails the backend's
    // `_is_user_selectable_model` check (chat_stream_pipeline.py) and gets
    // silently dropped to the conversation's existing model.
    //
    // Checks every id `mapToBackendModelName` can produce: current picker
    // entries AND every RETIRED_MODEL_MAP target (cookies/stored
    // conversations can still send retired gateway ids).
    const idsToCheck = [
      ...chatModels.map((model) => model.id),
      ...Object.keys(RETIRED_MODEL_MAP),
    ];

    for (const id of idsToCheck) {
      const backendId = mapToBackendModelName(id);
      assert.equal(
        SELECTABLE_BACKEND_MODEL_IDS.has(backendId),
        true,
        `${id} maps to backend id "${backendId}", which neos/config/models.yaml ` +
          "does not mark selectable (or doesn't define at all)"
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

    assert.equal(
      labelled.get("anthropic/claude-sonnet-4.5-thinking"),
      "Claude Sonnet 4.5 (Thinking)"
    );
  });

  test("does not offer gpt-4o / gpt-4o-mini — the backend catalog marks both non-selectable", () => {
    const ids = new Set(chatModels.map((model) => model.id));

    assert.equal(ids.has("openai/gpt-4o"), false);
    assert.equal(ids.has("openai/gpt-4o-mini"), false);
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

  test("keeps retired OpenAI and reasoning IDs on current, servable models", () => {
    // gpt-4.1 / gpt-4.1-mini used to bounce through gpt-4o / gpt-4o-mini,
    // which are themselves now non-selectable (Finding 1) — both now chase
    // straight to the current-generation models.
    assert.equal(mapToBackendModelName("openai/gpt-4.1"), "gpt-5.6-sol");
    assert.equal(mapToBackendModelName("openai/gpt-4.1-mini"), "gpt-5.6-terra");
    assert.equal(
      mapToBackendModelName("anthropic/claude-3.7-sonnet-thinking"),
      "claude-sonnet-4-5-20250929"
    );
  });

  test("routes the retired gpt-4o / gpt-4o-mini picker ids to current-generation models", () => {
    assert.equal(mapToBackendModelName("openai/gpt-4o"), "gpt-5.6-sol");
    assert.equal(mapToBackendModelName("openai/gpt-4o-mini"), "gpt-5.6-terra");
  });
});
