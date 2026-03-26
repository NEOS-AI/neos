"use client";

import { Button } from "@/components/ui/button";
import type { UIFrameComponent } from "@/lib/open-responses-types";

interface Props {
  component: UIFrameComponent;
  onClick?: () => void;
  disabled?: boolean;
}

export function ButtonField({ component, onClick, disabled }: Props) {
  return (
    <Button
      type="button"
      variant="outline"
      onClick={onClick}
      disabled={disabled}
    >
      {component.label ?? component.id}
    </Button>
  );
}
