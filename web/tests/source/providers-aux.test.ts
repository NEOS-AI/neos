import assert from "node:assert/strict";
import Module from "node:module";
import { describe, test } from "node:test";

import {
  generatedAux,
  generatedCatalog,
  generatedModels,
} from "../../lib/ai/catalog.generated";

async function importProviders() {
  const ModuleAny = Module as unknown as {
    _load: (request: string, ...rest: unknown[]) => unknown;
  };
  const originalLoad = ModuleAny._load;
  ModuleAny._load = (request: string, ...rest: unknown[]) => {
    if (request === "server-only") {
      return {};
    }
    return originalLoad(request, ...rest);
  };
  try {
    return await import("../../lib/ai/providers");
  } finally {
    ModuleAny._load = originalLoad;
  }
}

describe("generated aux helpers", () => {
  test("seeds title/artifact/fast to the dated haiku pin", () => {
    assert.equal(generatedAux.fast, "claude-haiku-4-5-20251001");
    assert.equal(generatedAux.title, "claude-haiku-4-5-20251001");
    assert.equal(generatedAux.artifact, "claude-haiku-4-5-20251001");
    assert.deepEqual(generatedCatalog.aux, generatedAux);
  });
});

describe("resolveAuxGatewayId", () => {
  test("maps committed aux pins to the haiku gateway id", async () => {
    const { resolveAuxGatewayId } = await importProviders();

    assert.equal(resolveAuxGatewayId("title"), "anthropic/claude-haiku-4.5");
    assert.equal(resolveAuxGatewayId("artifact"), "anthropic/claude-haiku-4.5");
    assert.equal(resolveAuxGatewayId("fast"), "anthropic/claude-haiku-4.5");
  });

  test("falls back to haiku when aux is missing", async () => {
    const { resolveAuxGatewayId } = await importProviders();

    assert.equal(
      resolveAuxGatewayId("title", {}, generatedModels),
      "anthropic/claude-haiku-4.5"
    );
  });

  test("falls back to haiku when the pin is not picker-visible", async () => {
    const { resolveAuxGatewayId } = await importProviders();

    assert.equal(
      resolveAuxGatewayId("title", { title: "not-in-picker" }, generatedModels),
      "anthropic/claude-haiku-4.5"
    );
  });
});
