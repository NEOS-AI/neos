import type { CatalogModelOut } from "./models";

export type EffortOption = { value: string | null; label: string };

/**
 * 레벨을 선언하지 않은 모델(Gemini·레거시)은 선택기를 숨긴다.
 * 필드가 없는 행(effort 필드 이전의 백엔드)도 숨긴다.
 */
export function shouldShowEffort(model: CatalogModelOut | undefined): boolean {
  return Boolean(
    model &&
      Array.isArray(model.effort_levels) &&
      model.effort_levels.length > 0
  );
}

/** 라벨은 API 어휘를 그대로 쓴다 — 번역층은 드리프트의 새 원천이다. */
export function effortOptions(model: CatalogModelOut): EffortOption[] {
  const head: EffortOption = {
    value: null,
    label: model.effort_default
      ? `Default (${model.effort_default})`
      : "Default",
  };
  return [
    head,
    ...model.effort_levels.map((level) => ({ value: level, label: level })),
  ];
}

export function effortRequest(
  catalogId: string,
  effort: string | null
): { url: string; init: RequestInit } {
  const url = `/api/model-preferences/${catalogId}`;
  if (effort === null) {
    return { url, init: { method: "DELETE" } };
  }
  return {
    url,
    init: {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ effort }),
    },
  };
}
