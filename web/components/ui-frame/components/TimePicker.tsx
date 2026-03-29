"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { UIFrameComponent } from "@/lib/open-responses-types";

interface Props {
  component: UIFrameComponent;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

export function TimePicker({ component, value, onChange, disabled }: Props) {
  return (
    <div className="flex flex-col gap-1.5">
      {component.label && (
        <Label htmlFor={component.id}>
          {component.label}
          {component.required && <span className="text-destructive ml-1">*</span>}
        </Label>
      )}
      <Input
        id={component.id}
        type="time"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        required={component.required}
      />
    </div>
  );
}
