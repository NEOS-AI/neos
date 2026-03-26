"use client";

import { Label } from "@/components/ui/label";
import type { UIFrameComponent } from "@/lib/open-responses-types";

interface Props {
  component: UIFrameComponent;
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
}

function getOptionLabel(opt: { label: string; value: string } | string): string {
  return typeof opt === "string" ? opt : opt.label;
}

function getOptionValue(opt: { label: string; value: string } | string): string {
  return typeof opt === "string" ? opt : opt.value;
}

export function MultiSelect({ component, value, onChange, disabled }: Props) {
  const options = component.options ?? [];

  const toggle = (optValue: string) => {
    if (value.includes(optValue)) {
      onChange(value.filter((v) => v !== optValue));
    } else {
      onChange([...value, optValue]);
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      {component.label && (
        <Label>
          {component.label}
          {component.required && <span className="text-destructive ml-1">*</span>}
        </Label>
      )}
      <div className="flex flex-col gap-2">
        {options.map((opt) => {
          const optValue = getOptionValue(opt);
          return (
            <label key={optValue} className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-border accent-primary"
                checked={value.includes(optValue)}
                onChange={() => toggle(optValue)}
                disabled={disabled}
              />
              <span className="text-sm">{getOptionLabel(opt)}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
