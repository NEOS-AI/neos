"use client";

import type { UIFramePayload } from "@/lib/open-responses-types";
import { UIFrameForm } from "./UIFrameForm";

interface Props {
  uiFrame: UIFramePayload;
  onSubmitted?: () => void;
}

export function UIFrameRenderer({ uiFrame, onSubmitted }: Props) {
  if (!uiFrame?.components?.length) return null;

  return (
    <div className="rounded-lg border bg-card text-card-foreground p-4 my-2 shadow-sm max-w-md">
      {uiFrame.intent && (
        <p className="text-xs text-muted-foreground mb-3 capitalize">
          {uiFrame.intent.replace(/_/g, " ")}
        </p>
      )}
      <UIFrameForm uiFrame={uiFrame} onSubmitted={onSubmitted} />
    </div>
  );
}
