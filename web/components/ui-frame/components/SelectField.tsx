"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import type { UIFrameComponent } from "@/lib/open-responses-types";

interface Props {
  component: UIFrameComponent;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

function getOptionLabel(opt: { label: string; value: string } | string): string {
  return typeof opt === "string" ? opt : opt.label;
}

function getOptionValue(opt: { label: string; value: string } | string): string {
  return typeof opt === "string" ? opt : opt.value;
}

export function SelectField({ component, value, onChange, disabled }: Props) {
  const options = component.options ?? [];

  return (
    <div className="flex flex-col gap-1.5">
      {component.label && (
        <Label>
          {component.label}
          {component.required && <span className="text-destructive ml-1">*</span>}
        </Label>
      )}
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger>
          <SelectValue placeholder={component.placeholder ?? "선택하세요"} />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem key={getOptionValue(opt)} value={getOptionValue(opt)}>
              {getOptionLabel(opt)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
