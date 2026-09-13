import "server-only";

import { callBackendAPI } from "@/lib/backend-api";
import { generatedCatalog } from "./catalog.generated";
import {
  isCatalogApiEnabled,
  parseCatalogResponse,
  resolveChatModelFromCookie,
  type CatalogPayload,
} from "./models";

export function fallbackCatalog(): CatalogPayload {
  return {
    models: generatedCatalog.models as CatalogPayload["models"],
    remaps: { ...generatedCatalog.remaps },
    default_id: generatedCatalog.default_id,
  };
}

export async function loadCatalog(): Promise<CatalogPayload> {
  if (!isCatalogApiEnabled()) {
    return fallbackCatalog();
  }

  try {
    const response = await callBackendAPI("/api/v1/models", {
      cache: "no-store",
    });
    if (!response.ok) {
      return fallbackCatalog();
    }
    return parseCatalogResponse(await response.json()) ?? fallbackCatalog();
  } catch {
    return fallbackCatalog();
  }
}

export async function loadPageCatalog(cookieValue: string | undefined): Promise<{
  catalog: CatalogPayload;
  modelId: string;
  rewriteTo: string | null;
}> {
  const catalog = await loadCatalog();
  const resolved = resolveChatModelFromCookie(cookieValue, catalog);
  return { catalog, ...resolved };
}
