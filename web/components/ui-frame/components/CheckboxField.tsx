"use client";

import { Label } from "@/components/ui/label";
import type { UIFrameComponent } from "@/lib/open-responses-types";

interface Props {
  component: UIFrameComponent;
  value: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}

export function CheckboxField({ component, value, onChange, disabled }: Props) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        id={component.id}
        type="checkbox"
        className="h-4 w-4 rounded border-border accent-primary"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
      />
      {component.label && (
        <Label htmlFor={component.id} className="cursor-pointer">
          {component.label}
          {component.required && <span className="text-destructive ml-1">*</span>}
        </Label>
      )}
    </label>
  );
}
