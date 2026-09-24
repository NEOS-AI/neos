import { strict as assert } from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  generatedCatalog,
  generatedDefaultId,
  generatedDefaultPin,
  generatedFallbackMap,
} from "../../lib/ai/catalog.generated";
import {
  DEFAULT_CHAT_MODEL,
  type CatalogPayload,
  isCatalogApiEnabled,
  mapToBackendModelName,
  parseCatalogResponse,
  resolveChatModelFromCookie,
} from "../../lib/ai/models";

const PICKER_GROUPS = new Set(["anthropic", "openai", "reasoning"]);

function row(
  id: string,
  catalogId: string,
  extras: Partial<CatalogPayload["models"][number]> = {}
): CatalogPayload["models"][number] {
  return {
    id,
    catalog_id: catalogId,
    name: extras.name ?? id,
    provider: extras.provider ?? "anthropic",
    description: extras.description ?? "",
    thinking: extras.thinking ?? "adaptive",
    vision: extras.vision ?? true,
    role_alias: extras.role_alias ?? null,
    default: extras.default ?? false,
  };
}

/** Live catalog after a 5.1 current: move — sonnet-5 is no longer in models[]. */
const liveAfter51: CatalogPayload = {
  default_id: "anthropic/claude-sonnet-5-1",
  remaps: {
    "anthropic/claude-sonnet-5": "anthropic/claude-sonnet-5-1",
    "anthropic/claude-opus-4.5": "anthropic/claude-opus-5.5",
    "old/no-longer-in-picker": "missing/gateway",
  },
  models: [
    row("anthropic/claude-sonnet-5-1", "claude-sonnet-5-1", {
      name: "Claude Sonnet 5.1",
      default: true,
      role_alias: "sonnet-5",
    }),
    row("anthropic/claude-opus-5.5", "claude-opus-5-5", {
      name: "Claude Opus 5.5",
      role_alias: "opus-5.5",
    }),
  ],
};

describe("mapToBackendModelName", () => {
  test("1. live picker id maps to that row's catalog_id", () => {
    assert.equal(
      mapToBackendModelName("anthropic/claude-sonnet-5-1", liveAfter51),
      "claude-sonnet-5-1"
    );
  });

  test("2. payload remaps[id] is a gateway id; look up that row's catalog_id", () => {
    assert.equal(
      mapToBackendModelName("anthropic/claude-sonnet-5", liveAfter51),
      "claude-sonnet-5-1"
    );
    assert.equal(
      mapToBackendModelName("anthropic/claude-opus-4.5", liveAfter51),
      "claude-opus-5-5"
    );
  });

  test("3. generated fallback map covers ids the live payload has not seen", () => {
    assert.equal(
      mapToBackendModelName("openai/gpt-4o", liveAfter51),
      "gpt-6-sol"
    );
    assert.equal(
      mapToBackendModelName("openai/gpt-4.1-mini", liveAfter51),
      "gpt-6-sol"
    );
  });

  test("4. unknown id falls back to the catalog default pin", () => {
    assert.equal(
      mapToBackendModelName("totally-unknown/model", liveAfter51),
      "claude-sonnet-5-1"
    );
  });

  test("4b. empty live catalog still uses the generated default pin", () => {
    const empty: CatalogPayload = { models: [], remaps: {}, default_id: "" };
    assert.equal(
      mapToBackendModelName("still-raw/id", empty),
      generatedDefaultPin
    );
  });

  test("5. always returns a string — never undefined or omitted", () => {
    const empty: CatalogPayload = { models: [], remaps: {}, default_id: "" };
    for (const id of ["still-raw/id", "", "anthropic/claude-sonnet-5"]) {
      const result = mapToBackendModelName(id, empty);
      assert.equal(typeof result, "string");
      assert.notEqual(result, undefined);
    }
  });

  test("never returns a gateway-prefixed id for live picker rows", () => {
    for (const model of generatedCatalog.models) {
      assert.equal(
        mapToBackendModelName(model.id, generatedCatalog).includes("/"),
        false,
        `${model.id} must not be forwarded as a gateway id`
      );
    }
  });

  test("never maps a generated picker or remap id onto a non-pin", () => {
    const pins = new Set(generatedCatalog.models.map((m) => m.catalog_id));
    pins.add(generatedDefaultPin);

    const ids = [
      ...generatedCatalog.models.map((m) => m.id),
      ...Object.keys(generatedCatalog.remaps),
      ...Object.keys(generatedFallbackMap),
    ];
    for (const id of ids) {
      const backendId = mapToBackendModelName(id, generatedCatalog);
      assert.equal(typeof backendId, "string");
      assert.ok(
        pins.has(backendId) || !backendId.includes("/"),
        `${id} mapped to ${backendId}`
      );
    }
  });
});

describe("generated catalog fallback", () => {
  test("defaults chats to the generated Anthropic everyday gateway id", () => {
    assert.equal(DEFAULT_CHAT_MODEL, generatedDefaultId);
    assert.equal(generatedDefaultId, "anthropic/claude-sonnet-5");
    assert.equal(generatedDefaultPin, "claude-sonnet-5");
    assert.equal(generatedCatalog.default_id, generatedDefaultId);
  });

  test("reproduces today's seven picker rows with accurate labels", () => {
    const byId = new Map(generatedCatalog.models.map((m) => [m.id, m]));
    assert.equal(byId.size, 7);

    assert.equal(byId.get("anthropic/claude-sonnet-5")?.name, "Claude Sonnet 5");
    assert.equal(byId.get("anthropic/claude-sonnet-5")?.provider, "anthropic");
    assert.equal(byId.get("anthropic/claude-opus-5.5")?.name, "Claude Opus 5.5");
    assert.equal(byId.get("openai/gpt-6-sol")?.name, "GPT-6 Sol");
    assert.equal(byId.get("openai/gpt-6-luna")?.name, "GPT-6 Luna");
    assert.equal(
      byId.get("anthropic/claude-sonnet-4.5-thinking")?.name,
      "Claude Sonnet 4.5 (Thinking)"
    );
  });

  test("does not present Claude Opus 4.5 as a live picker row", () => {
    assert.equal(
      generatedCatalog.models.some((m) => m.id === "anthropic/claude-opus-4.5"),
      false
    );
    assert.notEqual(
      generatedCatalog.models.find((m) => m.id === "anthropic/claude-opus-5.5")
        ?.name,
      "Claude Opus 4.6"
    );
  });

  test("keeps gpt-4o and gpt-6-astra out of the picker", () => {
    const ids = new Set(generatedCatalog.models.map((m) => m.id));
    const catalogIds = new Set(
      generatedCatalog.models.map((m) => m.catalog_id)
    );
    assert.equal(ids.has("openai/gpt-4o"), false);
    assert.equal(ids.has("openai/gpt-4o-mini"), false);
    assert.equal(ids.has("openai/gpt-6-astra"), false);
    assert.equal(catalogIds.has("gpt-6-astra"), false);
  });

  test("only offers anthropic / openai / reasoning groups", () => {
    for (const model of generatedCatalog.models) {
      assert.ok(
        PICKER_GROUPS.has(model.provider),
        `${model.id} has unexpected group ${model.provider}`
      );
    }
  });

  test("reasoning rows keep thinking/reasoning in the id", () => {
    const reasoning = generatedCatalog.models.filter(
      (model) => model.provider === "reasoning"
    );
    assert.ok(reasoning.length > 0);
    for (const model of reasoning) {
      assert.ok(
        model.id.includes("thinking") || model.id.includes("reasoning"),
        `${model.id} would lose its reasoning prompt`
      );
    }
  });

  test("every payload remap target is a models[].id", () => {
    const ids = new Set(generatedCatalog.models.map((m) => m.id));
    for (const [raw, target] of Object.entries(generatedCatalog.remaps)) {
      assert.ok(ids.has(target), `${raw} remaps to ${target}, not in models[]`);
    }
  });

  test("generated fallback map still lands retired cookies on current pins", () => {
    assert.equal(generatedFallbackMap["anthropic/claude-opus-4.5"], "claude-opus-5-5");
    assert.equal(generatedFallbackMap["openai/gpt-4o"], "gpt-6-sol");
    assert.equal(generatedFallbackMap["openai/gpt-4o-mini"], "gpt-6-sol");
    assert.equal(generatedFallbackMap["openai/gpt-4.1"], "gpt-6-sol");
    assert.equal(generatedFallbackMap["openai/gpt-4.1-mini"], "gpt-6-sol");
    assert.equal(
      generatedFallbackMap["anthropic/claude-3.7-sonnet-thinking"],
      "claude-sonnet-4-5-20250929"
    );
    assert.equal(
      generatedFallbackMap["google/gemini-2.5-flash-lite"],
      "claude-sonnet-5"
    );
    assert.equal(
      generatedFallbackMap["google/gemini-3-pro-preview"],
      "claude-sonnet-5"
    );
    assert.equal(
      generatedFallbackMap["xai/grok-4.1-fast-non-reasoning"],
      "claude-sonnet-5"
    );
    assert.equal(
      generatedFallbackMap["xai/grok-code-fast-1-thinking"],
      "claude-sonnet-5"
    );
  });

  test("maps current gateway ids to their exact backend pins", () => {
    assert.deepEqual(
      [
        "anthropic/claude-sonnet-5",
        "anthropic/claude-opus-5.5",
        "openai/gpt-6-sol",
        "openai/gpt-6-luna",
      ].map((id) => [id, mapToBackendModelName(id, generatedCatalog)]),
      [
        ["anthropic/claude-sonnet-5", "claude-sonnet-5"],
        ["anthropic/claude-opus-5.5", "claude-opus-5-5"],
        ["openai/gpt-6-sol", "gpt-6-sol"],
        ["openai/gpt-6-luna", "gpt-6-luna"],
      ]
    );
  });
});

describe("cookie remaps", () => {
  test("rewrites a remapped cookie to the payload gateway id", () => {
    const result = resolveChatModelFromCookie(
      "anthropic/claude-opus-4.5",
      generatedCatalog
    );
    assert.equal(result.modelId, "anthropic/claude-opus-5.5");
    assert.equal(result.rewriteTo, "anthropic/claude-opus-5.5");
  });

  test("uses default_id when the remapped gateway is not in models[]", () => {
    const result = resolveChatModelFromCookie(
      "old/no-longer-in-picker",
      liveAfter51
    );
    assert.equal(result.modelId, "anthropic/claude-sonnet-5-1");
    assert.equal(result.rewriteTo, "anthropic/claude-sonnet-5-1");
  });

  test("keeps a live picker cookie and does not rewrite it", () => {
    const result = resolveChatModelFromCookie(
      "anthropic/claude-sonnet-5",
      generatedCatalog
    );
    assert.equal(result.modelId, "anthropic/claude-sonnet-5");
    assert.equal(result.rewriteTo, null);
  });

  test("missing cookie uses default_id", () => {
    const result = resolveChatModelFromCookie(undefined, generatedCatalog);
    assert.equal(result.modelId, generatedDefaultId);
    assert.equal(result.rewriteTo, null);
  });

  test("remapped cookie does not require a render-phase cookies().set", () => {
    const read = (relative: string) =>
      readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf8");

    const newChatPage = read("../../app/(chat)/page.tsx");
    const existingChatPage = read("../../app/(chat)/chat/[id]/page.tsx");
    const chat = read("../../components/chat.tsx");

    for (const [label, source] of [
      ["page.tsx", newChatPage],
      ["chat/[id]/page.tsx", existingChatPage],
    ] as const) {
      assert.equal(
        source.includes("saveChatModelAsCookie"),
        false,
        `${label} must not call saveChatModelAsCookie during RSC render`
      );
      assert.equal(
        /cookies\(\)\s*\.set|cookieStore\.set/.test(source),
        false,
        `${label} must not mutate cookies during RSC render`
      );
    }

    assert.ok(
      chat.includes("saveChatModelAsCookie"),
      "Chat persists the remapped cookie from a client effect"
    );
    assert.ok(
      /useEffect\(\s*\(\)\s*=>\s*\{[\s\S]*saveChatModelAsCookie/.test(chat),
      "cookie persist must be inside useEffect, not render"
    );
  });
});

describe("catalog dual-read helpers", () => {
  test("CATALOG_API=1 enables the live fetch", () => {
    assert.equal(isCatalogApiEnabled({ CATALOG_API: "1" }), true);
    assert.equal(isCatalogApiEnabled({}), false);
    assert.equal(isCatalogApiEnabled({ CATALOG_API: "0" }), false);
  });

  test("parseCatalogResponse accepts a live payload and rejects empty", () => {
    const parsed = parseCatalogResponse({
      models: liveAfter51.models,
      remaps: liveAfter51.remaps,
      default_id: liveAfter51.default_id,
    });
    assert.deepEqual(parsed, liveAfter51);
    assert.equal(parseCatalogResponse({ models: [], default_id: "x" }), null);
    assert.equal(parseCatalogResponse(null), null);
  });
});
