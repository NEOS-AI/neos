"use client";

import { Label } from "@/components/ui/label";
import type { UIFrameComponent } from "@/lib/open-responses-types";

interface Props {
  component: UIFrameComponent;
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}

export function SliderField({ component, value, onChange, disabled }: Props) {
  const min = component.min ?? 0;
  const max = component.max ?? 100;
  const step = component.step ?? 1;

  return (
    <div className="flex flex-col gap-1.5">
      {component.label && (
        <Label htmlFor={component.id}>
          {component.label}
          {component.required && <span className="text-destructive ml-1">*</span>}
          <span className="ml-2 font-normal text-muted-foreground">{value}</span>
        </Label>
      )}
      <input
        id={component.id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={disabled}
        className="w-full accent-primary"
      />
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  );
}
