import assert from "node:assert/strict";
import Module from "node:module";
import { afterEach, describe, test } from "node:test";

/**
 * Dual-read: CATALOG_API=1 fetches GET /api/v1/models; unset uses generated.
 * 404/503 (picker_api off, empty catalog) must not clear the picker.
 */

type CallBackendAPIStub = (
  endpoint: string,
  options?: RequestInit
) => Promise<Response>;

let stubImpl: CallBackendAPIStub = async () => {
  throw new Error("callBackendAPI stub not configured");
};
let fetchCount = 0;
let lastFetch: { endpoint: string; options?: RequestInit } | undefined;

const stubCallBackendAPI: CallBackendAPIStub = async (endpoint, options) => {
  fetchCount += 1;
  lastFetch = { endpoint, options };
  return stubImpl(endpoint, options);
};

async function importLoader() {
  const ModuleAny = Module as any;
  const originalLoad = ModuleAny._load;
  ModuleAny._load = (request: string, ...rest: any[]) => {
    if (request === "server-only") {
      return {};
    }
    if (request === "@/lib/backend-api") {
      return { callBackendAPI: stubCallBackendAPI };
    }
    return originalLoad(request, ...rest);
  };
  try {
    return await import("../../lib/ai/catalog");
  } finally {
    ModuleAny._load = originalLoad;
  }
}

const originalCatalogApi = process.env.CATALOG_API;

afterEach(() => {
  fetchCount = 0;
  lastFetch = undefined;
  if (originalCatalogApi === undefined) {
    delete process.env.CATALOG_API;
  } else {
    process.env.CATALOG_API = originalCatalogApi;
  }
});

describe("loadCatalog dual-read", () => {
  test("unset CATALOG_API uses the generated fallback and does not fetch", async () => {
    delete process.env.CATALOG_API;
    const { loadCatalog, fallbackCatalog } = await importLoader();
    const catalog = await loadCatalog();

    assert.equal(fetchCount, 0);
    assert.equal(catalog.default_id, fallbackCatalog().default_id);
    assert.ok(catalog.models.length >= 7);
  });

  test("CATALOG_API=1 fetches /api/v1/models with cache: no-store", async () => {
    process.env.CATALOG_API = "1";
    stubImpl = async () =>
      new Response(
        JSON.stringify({
          version: 1,
          etag: "abc",
          default_id: "anthropic/claude-sonnet-5-1",
          remaps: { "anthropic/claude-sonnet-5": "anthropic/claude-sonnet-5-1" },
          models: [
            {
              id: "anthropic/claude-sonnet-5-1",
              catalog_id: "claude-sonnet-5-1",
              name: "Claude Sonnet 5.1",
              provider: "anthropic",
              description: "bumped",
              thinking: "adaptive",
              vision: true,
              role_alias: "sonnet-5",
              default: true,
            },
          ],
        }),
        { status: 200 }
      );

    const { loadCatalog } = await importLoader();
    const catalog = await loadCatalog();

    assert.equal(fetchCount, 1);
    assert.equal(lastFetch?.endpoint, "/api/v1/models");
    assert.equal((lastFetch?.options as { cache?: string } | undefined)?.cache, "no-store");
    assert.equal(catalog.default_id, "anthropic/claude-sonnet-5-1");
    assert.equal(catalog.models[0]?.catalog_id, "claude-sonnet-5-1");
    assert.equal(
      catalog.remaps["anthropic/claude-sonnet-5"],
      "anthropic/claude-sonnet-5-1"
    );
  });

  test("CATALOG_API=1 + 404 (picker_api off) keeps the generated fallback", async () => {
    process.env.CATALOG_API = "1";
    stubImpl = async () => new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });

    const { loadCatalog, fallbackCatalog } = await importLoader();
    const catalog = await loadCatalog();

    assert.equal(catalog.default_id, fallbackCatalog().default_id);
    assert.ok(catalog.models.length >= 7);
  });

  test("CATALOG_API=1 + 503 empty catalog keeps the generated fallback", async () => {
    process.env.CATALOG_API = "1";
    stubImpl = async () =>
      new Response(JSON.stringify({ detail: "Model catalog is empty" }), {
        status: 503,
      });

    const { loadCatalog, fallbackCatalog } = await importLoader();
    const catalog = await loadCatalog();

    assert.equal(catalog.default_id, fallbackCatalog().default_id);
    assert.ok(catalog.models.length >= 7);
  });
});
