"use client";

import { FileCodeIcon, FileTextIcon, TableIcon } from "lucide-react";
import { useArtifact } from "@/hooks/use-artifact";
import { cn } from "@/lib/utils";

interface ArtifactBlockProps {
  artifact: {
    id: string;
    title: string;
    kind: "text" | "code" | "sheet";
  };
}

export function ArtifactBlock({ artifact }: ArtifactBlockProps) {
  const { setArtifact } = useArtifact();

  const handleClick = () => {
    // 아티팩트를 다시 열기
    setArtifact((prev) => ({
      ...prev,
      documentId: artifact.id,
      title: artifact.title,
      kind: artifact.kind,
      isVisible: true,
      status: "idle",
    }));
  };

  // 아티팩트 타입에 따른 아이콘
  const Icon =
    artifact.kind === "code"
      ? FileCodeIcon
      : artifact.kind === "sheet"
        ? TableIcon
        : FileTextIcon;

  // 아티팩트 타입에 따른 라벨
  const kindLabel =
    artifact.kind === "code"
      ? "Code"
      : artifact.kind === "sheet"
        ? "Spreadsheet"
        : "Document";

  return (
    <button
      className={cn(
        "group relative flex w-full items-center gap-3 rounded-xl border border-border bg-muted/30 p-4 transition-all hover:border-blue-500 hover:bg-muted/50 hover:shadow-md",
        "cursor-pointer"
      )}
      onClick={handleClick}
      type="button"
    >
      {/* 아이콘 */}
      <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-blue-500/10 text-blue-600 dark:bg-blue-500/20 dark:text-blue-400">
        <Icon className="size-5" />
      </div>

      {/* 콘텐츠 */}
      <div className="flex min-w-0 flex-1 flex-col items-start text-left">
        <div className="text-muted-foreground text-xs font-medium uppercase tracking-wider">
          {kindLabel}
        </div>
        <div className="mt-0.5 w-full truncate font-medium text-foreground">
          {artifact.title}
        </div>
      </div>

      {/* 호버 시 화살표 */}
      <div className="text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
        <svg
          className="size-5"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          viewBox="0 0 24 24"
        >
          <path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
    </button>
  );
}
