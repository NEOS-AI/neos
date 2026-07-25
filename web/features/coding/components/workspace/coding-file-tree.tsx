import { FileCode2, Folder } from "lucide-react";
import type { WorkspaceEntry } from "@/features/coding/workspace/types";

export function CodingFileTree({
  entries,
  selectedPath,
  onSelect,
}: {
  entries: WorkspaceEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
}) {
  if (entries.length === 0) {
    return <p className="p-4 text-muted-foreground text-xs">No files yet.</p>;
  }
  return (
    <nav aria-label="Workspace files" className="overflow-auto py-2">
      {entries.map((entry) => (
        <button
          className={`flex w-full items-center gap-2 px-3 py-1.5 text-left font-mono text-xs ${
            selectedPath === entry.path
              ? "bg-amber-400/10 text-amber-200"
              : "text-muted-foreground hover:bg-muted/40 hover:text-foreground"
          }`}
          disabled={entry.kind !== "file"}
          key={entry.path}
          onClick={() => onSelect(entry.path)}
          type="button"
        >
          {entry.kind === "file" ? (
            <FileCode2 className="size-3.5 shrink-0" />
          ) : (
            <Folder className="size-3.5 shrink-0" />
          )}
          <span className="truncate">{entry.path}</span>
        </button>
      ))}
    </nav>
  );
}
