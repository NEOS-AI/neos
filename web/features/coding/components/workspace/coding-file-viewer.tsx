import type { CodingWorkspaceState } from "@/features/coding/workspace/workspace-store";

export function CodingFileViewer({
  state,
  checkpointId,
  onBeginEdit,
  onUpdateDraft,
  onCancel,
  onSave,
  onReload,
  onCompare,
}: {
  state: CodingWorkspaceState;
  checkpointId: string | null;
  onBeginEdit: () => void;
  onUpdateDraft: (content: string) => void;
  onCancel: () => void;
  onSave: () => void;
  onReload: () => void;
  onCompare: () => void;
}) {
  if (!state.file && !state.draft) {
    return (
      <p className="p-4 text-muted-foreground text-xs">
        Select a file to inspect it.
      </p>
    );
  }
  const editing = Boolean(state.draft);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-border/60 border-b px-3 py-2">
        <span className="truncate font-mono text-[11px]">
          {state.draft?.path ?? state.file?.path}
        </span>
        <div className="flex gap-2">
          {editing ? (
            <>
              <button
                className="text-muted-foreground text-xs"
                onClick={onCancel}
                type="button"
              >
                Cancel
              </button>
              <button
                className="text-amber-300 text-xs"
                onClick={onSave}
                type="button"
              >
                Save changes
              </button>
            </>
          ) : (
            <button
              className="text-amber-300 text-xs"
              onClick={onBeginEdit}
              type="button"
            >
              Edit
            </button>
          )}
        </div>
      </div>
      {state.editState === "revision_conflict" ? (
        <div className="border-amber-400/30 border-b bg-amber-400/5 px-3 py-2 text-xs">
          <p className="text-amber-200">File changed since editing began</p>
          <div className="mt-1 flex gap-3">
            <button onClick={onReload} type="button">
              Reload latest
            </button>
            <button onClick={onCompare} type="button">
              Compare changes
            </button>
          </div>
        </div>
      ) : null}
      {state.editState === "saved_pending_agent" ? (
        <p className="border-border/60 border-b px-3 py-2 text-amber-300 text-xs">
          Saved · agent sync pending
        </p>
      ) : null}
      {state.editState === "agent_synced" ? (
        <p className="border-border/60 border-b px-3 py-2 text-emerald-300 text-xs">
          Agent synced at checkpoint {checkpointId ?? "latest"}
        </p>
      ) : null}
      {editing ? (
        <textarea
          aria-label="File contents"
          className="min-h-0 flex-1 resize-none bg-black/15 p-4 font-mono text-[12px] leading-5 outline-none"
          onChange={(event) => onUpdateDraft(event.target.value)}
          spellCheck={false}
          value={state.draft?.content ?? ""}
        />
      ) : (
        <pre className="min-h-0 flex-1 overflow-auto bg-black/15 p-4 font-mono text-[12px] leading-5">
          {state.file?.binary
            ? "Binary file · preview unavailable"
            : state.file?.content}
        </pre>
      )}
    </div>
  );
}
