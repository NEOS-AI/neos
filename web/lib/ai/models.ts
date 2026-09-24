import {
  generatedCatalog,
  generatedDefaultId,
  generatedDefaultPin,
  generatedFallbackMap,
} from "./catalog.generated";

export type CatalogModelOut = {
  id: string;
  catalog_id: string;
  name: string;
  provider: string;
  description: string;
  thinking: "adaptive" | "budgeted" | "none";
  vision: boolean;
  role_alias: string | null;
  default: boolean;
  effort_levels: string[];
  effort_default: string | null;
};

export type ChatModel = CatalogModelOut;

export type CatalogPayload = {
  models: CatalogModelOut[];
  remaps: Record<string, string>;
  default_id: string;
};

export type CatalogLookup = {
  models: ReadonlyArray<{ id: string; catalog_id: string }>;
  remaps: Record<string, string>;
  default_id: string;
};

/** Last-resort default from the committed fallback — not a handwritten pin. */
export const DEFAULT_CHAT_MODEL = generatedDefaultId;

export function groupModelsByProvider(
  models: ChatModel[]
): Record<string, ChatModel[]> {
  return models.reduce(
    (acc, model) => {
      if (!acc[model.provider]) {
        acc[model.provider] = [];
      }
      acc[model.provider].push(model);
      return acc;
    },
    {} as Record<string, ChatModel[]>
  );
}

export function isCatalogApiEnabled(
  env: NodeJS.ProcessEnv | Record<string, string | undefined> = process.env
): boolean {
  return env.CATALOG_API === "1";
}

export function parseCatalogResponse(data: unknown): CatalogPayload | null {
  if (!data || typeof data !== "object") {
    return null;
  }
  const rec = data as Record<string, unknown>;
  if (!Array.isArray(rec.models) || rec.models.length === 0) {
    return null;
  }
  if (typeof rec.default_id !== "string" || rec.default_id.length === 0) {
    return null;
  }
  const remaps =
    rec.remaps && typeof rec.remaps === "object" && !Array.isArray(rec.remaps)
      ? Object.fromEntries(
          Object.entries(rec.remaps as Record<string, unknown>).filter(
            (entry): entry is [string, string] => typeof entry[1] === "string"
          )
        )
      : {};
  return {
    models: rec.models as CatalogModelOut[],
    remaps,
    default_id: rec.default_id,
  };
}

/**
 * Always returns a string. Payload remaps are raw → gateway_id, not raw → pin.
 *
 * 1. live picker id → catalog_id
 * 2. remaps[id] → that row's catalog_id
 * 3. last shipped generated map (raw → pin)
 * 4. catalog default pin
 * 5. raw string (BE canonicalize(apply_remap=True))
 */
export function mapToBackendModelName(
  id: string,
  catalog: CatalogLookup = generatedCatalog
): string {
  const byId = new Map(catalog.models.map((model) => [model.id, model.catalog_id]));
  const hit = byId.get(id);
  if (hit) {
    return hit;
  }
  const remappedGateway = catalog.remaps[id];
  if (remappedGateway) {
    const pin = byId.get(remappedGateway);
    if (pin) {
      return pin;
    }
  }
  const generated = generatedFallbackMap[id];
  if (generated) {
    return generated;
  }
  const fallbackDefault = byId.get(catalog.default_id) ?? generatedDefaultPin;
  if (fallbackDefault) {
    return fallbackDefault;
  }
  return id;
}

export function resolveChatModelFromCookie(
  cookie: string | undefined,
  catalog: CatalogPayload
): { modelId: string; rewriteTo: string | null } {
  if (!cookie) {
    return { modelId: catalog.default_id, rewriteTo: null };
  }
  const remapped = catalog.remaps[cookie];
  if (remapped) {
    const inPicker = catalog.models.some((model) => model.id === remapped);
    const target = inPicker ? remapped : catalog.default_id;
    return {
      modelId: target,
      rewriteTo: target !== cookie ? target : null,
    };
  }
  return { modelId: cookie, rewriteTo: null };
}
