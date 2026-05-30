"use client";

import { memo, type ReactNode, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { AUTONOMY_CONFIGS, type AutonomyLevel } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  CheckCircleFillIcon,
  ChevronDownIcon,
  CpuIcon,
  LockIcon,
  SparklesIcon,
} from "./icons";

const autonomyIcons: Record<string, ReactNode> = {
  lock: <LockIcon />,
  sparkles: <SparklesIcon />,
  cpu: <CpuIcon />,
};

interface AgentAutonomySelectorProps {
  autonomyLevel: AutonomyLevel;
  onAutonomyChange: (level: AutonomyLevel) => void;
  className?: string;
  disabled?: boolean;
}

function PureAgentAutonomySelector({
  autonomyLevel,
  onAutonomyChange,
  className,
  disabled = false,
}: AgentAutonomySelectorProps) {
  const [open, setOpen] = useState(false);
  const current = useMemo(
    () =>
      AUTONOMY_CONFIGS.find((config) => config.level === autonomyLevel) ??
      AUTONOMY_CONFIGS[1],
    [autonomyLevel]
  );

  return (
    <DropdownMenu onOpenChange={setOpen} open={open}>
      <DropdownMenuTrigger
        asChild
        className={cn(
          "w-fit data-[state=open]:bg-accent data-[state=open]:text-accent-foreground",
          className
        )}
        disabled={disabled}
      >
        <Button
          className="hidden h-8 gap-1.5 px-2 md:flex md:h-fit"
          data-testid="autonomy-selector"
          title={`Agent autonomy: ${current.label}`}
          variant="outline"
        >
          {autonomyIcons[current.icon]}
          <span className="hidden text-xs md:inline">{current.label}</span>
          <ChevronDownIcon />
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="min-w-[280px]">
        <div className="px-2 py-1.5 text-muted-foreground text-xs font-medium">
          Agent autonomy
        </div>
        {AUTONOMY_CONFIGS.map((config) => (
          <DropdownMenuItem
            className="group/item flex flex-row items-center justify-between gap-4"
            data-active={config.level === autonomyLevel}
            data-testid={`autonomy-selector-item-${config.level}`}
            key={config.level}
            onSelect={() => {
              onAutonomyChange(config.level);
              setOpen(false);
            }}
          >
            <div className="flex items-start gap-2">
              <div className="mt-0.5 text-muted-foreground">
                {autonomyIcons[config.icon]}
              </div>
              <div className="flex flex-col items-start gap-1">
                <span>{config.label}</span>
                <span className="text-muted-foreground text-xs">
                  {config.description}
                </span>
              </div>
            </div>
            <div className="text-foreground opacity-0 group-data-[active=true]/item:opacity-100 dark:text-foreground">
              <CheckCircleFillIcon />
            </div>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export const AgentAutonomySelector = memo(
  PureAgentAutonomySelector,
  (prev, next) =>
    prev.autonomyLevel === next.autonomyLevel &&
    prev.disabled === next.disabled &&
    prev.className === next.className
);
