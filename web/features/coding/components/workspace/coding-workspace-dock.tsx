"use client";

import { Files, GitCompareArrows, PanelRight, Terminal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { CodingProjectionState } from "@/features/coding/types/projection";
import { useCodingWorkspace } from "@/features/coding/workspace/use-coding-workspace";
import { CodingDiffViewer } from "./coding-diff-viewer";
import { CodingFileTree } from "./coding-file-tree";
import { CodingFileViewer } from "./coding-file-viewer";
import { CodingTerminal } from "./coding-terminal";
import {
  clampDockWidth,
  reduceDockKey,
  type WorkspaceDockTab,
} from "./workspace-dock-layout";

const TABS = [
  { id: "files", label: "Files", icon: Files },
  { id: "diff", label: "Diff", icon: GitCompareArrows },
  { id: "terminal", label: "Terminal", icon: Terminal },
] as const;

export function CodingWorkspaceDock({
  taskId,
  projection,
  codingConnection,
  canOpenTerminal = false,
}: {
  taskId: string;
  projection: CodingProjectionState;
  codingConnection: string;
  /**
   * 서버가 준 불리언 그대로. 상태 이름으로 다시 판정하지 않는다.
   * 기본값이 `false` 인 것이 의도다 -- 넘기는 것을 잊으면 터미널이 열리지
   * 않을 뿐, 죽은 샌드박스에 PTY 를 만들지는 않는다.
   */
  canOpenTerminal?: boolean;
}) {
  const api = useCodingWorkspace(taskId);
  const [tab, setTab] = useState<WorkspaceDockTab>("files");
  const [width, setWidth] = useState(440);
  const [mobileOpen, setMobileOpen] = useState(false);
  const dragging = useRef(false);

  useEffect(() => {
    const saved = Number(localStorage.getItem("neos.coding.dock.width"));
    if (Number.isFinite(saved) && saved > 0) {
      setWidth(clampDockWidth(saved, window.innerWidth));
    }
    api.refreshTree();
  }, [api.refreshTree]);

  useEffect(() => {
    for (const edit of projection.workspace.user_edits ?? []) {
      api.applyUserEdit(edit);
    }
  }, [api.applyUserEdit, projection.workspace.user_edits]);

  useEffect(() => {
    if (tab === "diff") {
      api.refreshDiff();
    }
  }, [api.refreshDiff, tab]);

  useEffect(() => {
    const shortcuts = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || !event.shiftKey) {
        return;
      }
      const next =
        event.key.toLowerCase() === "e"
          ? "files"
          : event.key.toLowerCase() === "d"
            ? "diff"
            : event.key === "`"
              ? "terminal"
              : null;
      if (next) {
        event.preventDefault();
        setTab(next);
        setMobileOpen(true);
      }
    };
    window.addEventListener("keydown", shortcuts);
    return () => window.removeEventListener("keydown", shortcuts);
  }, []);

  function setPersistedWidth(next: number) {
    const bounded = clampDockWidth(next, window.innerWidth);
    setWidth(bounded);
    localStorage.setItem("neos.coding.dock.width", String(bounded));
  }

  function content() {
    if (tab === "terminal") {
      return <CodingTerminal canOpenTerminal={canOpenTerminal} taskId={taskId} />;
    }
    if (tab === "diff") {
      return <CodingDiffViewer diff={api.workspace.diff} />;
    }
    return (
      <div className="grid h-full min-h-0 grid-cols-[10rem_minmax(0,1fr)]">
        <CodingFileTree
          entries={api.workspace.tree?.entries ?? []}
          onSelect={api.openFile}
          selectedPath={api.workspace.selectedPath}
        />
        <CodingFileViewer
          checkpointId={api.workspace.syncedCheckpointId}
          onBeginEdit={() => api.beginEdit(api.workspace.file?.content ?? "")}
          onCancel={api.cancelEdit}
          onCompare={() => setTab("diff")}
          onReload={() => {
            api.cancelEdit();
            if (api.workspace.selectedPath) {
              api.openFile(api.workspace.selectedPath);
            }
          }}
          onSave={api.saveDraft}
          onUpdateDraft={api.updateDraft}
          state={api.workspace}
        />
      </div>
    );
  }

  const tabs = (
    <div
      aria-label="Workspace tools"
      className="flex border-border/60 border-b"
      role="tablist"
    >
      {TABS.map(({ id, label, icon: Icon }) => (
        <button
          aria-controls={`workspace-panel-${id}`}
          aria-selected={tab === id}
          className={`flex items-center gap-1.5 border-b-2 px-3 py-2 font-mono text-[10px] uppercase tracking-wider ${
            tab === id
              ? "border-amber-400 text-amber-300"
              : "border-transparent text-muted-foreground"
          }`}
          id={`workspace-tab-${id}`}
          key={id}
          onClick={() => setTab(id)}
          role="tab"
          type="button"
        >
          <Icon className="size-3" />
          {label}
        </button>
      ))}
    </div>
  );

  return (
    <>
      <button
        className="fixed right-4 bottom-4 z-40 rounded-full border border-amber-400/30 bg-background p-3 text-amber-300 shadow-xl lg:hidden"
        onClick={() => setMobileOpen(true)}
        type="button"
      >
        <PanelRight className="size-4" />
        <span className="sr-only">Open workspace</span>
      </button>
      <aside
        className="relative hidden min-h-0 shrink-0 border-border/70 border-l bg-card/20 lg:flex"
        style={{ width }}
      >
        <hr
          aria-label="Resize workspace dock"
          aria-orientation="vertical"
          aria-valuemax={720}
          aria-valuemin={320}
          aria-valuenow={Math.round(width)}
          className="-left-1 absolute inset-y-0 z-10 w-2 cursor-col-resize focus:bg-amber-400/30"
          onKeyDown={(event) => {
            const next = reduceDockKey(width, event.key, window.innerWidth);
            if (next !== width) {
              event.preventDefault();
              setPersistedWidth(next);
            }
          }}
          onPointerDown={(event) => {
            dragging.current = true;
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (dragging.current) {
              setPersistedWidth(window.innerWidth - event.clientX);
            }
          }}
          onPointerUp={() => {
            dragging.current = false;
          }}
          tabIndex={0}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          {tabs}
          <div
            aria-labelledby={`workspace-tab-${tab}`}
            className="min-h-0 flex-1"
            id={`workspace-panel-${tab}`}
            role="tabpanel"
          >
            {content()}
          </div>
          <p className="border-border/60 border-t px-3 py-1.5 font-mono text-[9px] text-muted-foreground uppercase">
            {codingConnection} · rev {api.workspace.workspaceRevision ?? "—"}
          </p>
        </div>
      </aside>
      {mobileOpen ? (
        <div className="fixed inset-0 z-50 bg-black/55 lg:hidden">
          <section className="absolute inset-x-0 bottom-0 flex h-[78dvh] flex-col border-border border-t bg-background">
            <button
              className="self-end px-4 py-2 text-xs"
              onClick={() => setMobileOpen(false)}
              type="button"
            >
              Close
            </button>
            {tabs}
            <div className="min-h-0 flex-1" role="tabpanel">
              {content()}
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
