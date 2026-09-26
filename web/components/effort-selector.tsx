"use client";

import { memo } from "react";
import { useModelEffort } from "@/hooks/use-model-effort";
import { effortOptions, shouldShowEffort } from "@/lib/ai/effort";
import type { CatalogModelOut } from "@/lib/ai/models";

function PureEffortSelector({ model }: { model: CatalogModelOut | undefined }) {
  const { efforts, setEffort } = useModelEffort();
  if (!model || !shouldShowEffort(model)) {
    return null;
  }
  const current = efforts[model.catalog_id] ?? "";
  return (
    <select
      aria-label="Effort"
      className="h-8 rounded-md bg-transparent px-2 text-muted-foreground text-xs"
      data-testid="effort-selector"
      onChange={(event) => {
        const value = event.target.value;
        setEffort(model.catalog_id, value === "" ? null : value);
      }}
      value={current}
    >
      {effortOptions(model).map((option) => (
        <option key={option.value ?? "default"} value={option.value ?? ""}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export const EffortSelector = memo(PureEffortSelector);
