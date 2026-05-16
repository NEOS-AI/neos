"use server";

import { adaptBESuggestion } from "@/lib/adapters/artifact-adapters";
import { callBackendAPI } from "@/lib/backend-api";

export async function getSuggestions({ documentId }: { documentId: string }) {
  const res = await callBackendAPI(
    `/api/v1/documents/${documentId}/suggestions`
  );

  if (!res.ok) return [];

  const raw: unknown[] = await res.json();
  return (raw as Parameters<typeof adaptBESuggestion>[0][]).map(
    adaptBESuggestion
  );
}
