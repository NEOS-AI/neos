export type CodingTask = {
  task_id: string;
  status: string;
  version: number;
  last_seq: number;
  created_at: string;
  updated_at: string;
};

export type CodingTaskListItem = CodingTask & {
  prompt: string;
};

export type CodingTaskList = {
  tasks: CodingTaskListItem[];
};

export type CodingWsTicket = {
  ticket: string;
  expires_in: number;
  websocket_url: string;
};

import type {
  CodingApprovalView,
  CodingProjectionSnapshot,
} from "@/features/coding/types/projection";
import type { CodingSandboxStatus } from "@/features/coding/sandbox/types";
import type {
  WorkspaceDiff,
  WorkspaceFile,
  WorkspaceFileSaveRequest,
  WorkspaceFileSaveResult,
  WorkspaceTree,
  WorkspaceWsTicket,
} from "@/features/coding/workspace/types";

export class CodingAPIError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "CodingAPIError";
    this.status = status;
  }
}

function extractErrorMessage(
  body: { error?: unknown; detail?: unknown },
  fallback: string
): string {
  if (typeof body.error === "string" && body.error) {
    return body.error;
  }
  const detail = body.detail;
  if (typeof detail === "string" && detail) {
    return detail;
  }
  if (
    detail &&
    typeof detail === "object" &&
    "message" in detail &&
    typeof detail.message === "string" &&
    detail.message
  ) {
    return detail.message;
  }
  return fallback;
}

async function responseError(response: Response, fallback: string) {
  const body = await response.json().catch(() => ({}));
  return new CodingAPIError(
    response.status,
    extractErrorMessage(body, fallback)
  );
}

export async function createCodingTask(prompt: string): Promise<CodingTask> {
  const response = await fetch("/api/coding/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  if (!response.ok) {
    throw await responseError(response, "Could not start coding task");
  }
  return response.json();
}

export async function listCodingTasks(
  limit = 20
): Promise<CodingTaskList> {
  const query = new URLSearchParams({ limit: String(limit) });
  const response = await fetch(`/api/coding/tasks?${query}`);
  if (!response.ok) {
    throw await responseError(response, "Could not load coding tasks");
  }
  return response.json();
}

export async function getCodingWsTicket(
  taskId: string
): Promise<CodingWsTicket> {
  const response = await fetch(
    `/api/coding/tasks/${encodeURIComponent(taskId)}/ws-ticket`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw await responseError(response, "Could not authorize coding stream");
  }
  return response.json();
}

export async function getCodingTaskSnapshot(
  taskId: string
): Promise<CodingProjectionSnapshot> {
  const response = await fetch(
    `/api/coding/tasks/${encodeURIComponent(taskId)}/snapshot`
  );
  if (!response.ok) {
    throw await responseError(response, "Could not restore coding task");
  }
  return response.json();
}

export async function getCodingSandboxStatus(
  taskId: string
): Promise<CodingSandboxStatus> {
  // GET 전용이다 -- 이 경로에는 할당을 만들거나 되살리는 메서드를 두지 않는다
  // (BFF 라우트 주석 참조).
  const response = await fetch(
    `/api/coding/tasks/${encodeURIComponent(taskId)}/sandbox-status`
  );
  if (!response.ok) {
    throw await responseError(response, "Could not read sandbox status");
  }
  return response.json();
}

export async function stopCodingTask(
  taskId: string
): Promise<{ task_id: string; status: "cancelled" }> {
  const response = await fetch(
    `/api/coding/tasks/${encodeURIComponent(taskId)}/stop`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw await responseError(response, "Could not stop coding task");
  }
  return response.json();
}

export async function steerCodingTask(
  taskId: string,
  instruction: string,
  mode: "safe_point" | "interrupt_now"
): Promise<{ steering_id: string; mode: string }> {
  const response = await fetch(
    `/api/coding/tasks/${encodeURIComponent(taskId)}/steer`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction, mode }),
    }
  );
  if (!response.ok) {
    throw await responseError(response, "Could not steer coding task");
  }
  return response.json();
}

export async function decideCodingApproval(
  taskId: string,
  approvalId: string,
  decision: "approve" | "deny",
  answers: string[] = [],
  remember = false
): Promise<CodingApprovalView> {
  const response = await fetch(
    `/api/coding/tasks/${encodeURIComponent(taskId)}/approvals/${encodeURIComponent(approvalId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, answers, remember }),
    }
  );
  if (!response.ok) {
    throw await responseError(response, "Could not resolve coding approval");
  }
  return response.json();
}

function workspaceUrl(taskId: string, operation: string) {
  return `/api/coding/tasks/${encodeURIComponent(taskId)}/workspace/${operation}`;
}

export async function getCodingWorkspaceTree(
  taskId: string,
  path = "."
): Promise<WorkspaceTree> {
  const query = new URLSearchParams({ path });
  const response = await fetch(`${workspaceUrl(taskId, "tree")}?${query}`);
  if (!response.ok) {
    throw await responseError(response, "Could not load workspace tree");
  }
  return response.json();
}

export async function getCodingWorkspaceFile(
  taskId: string,
  path: string
): Promise<WorkspaceFile> {
  const query = new URLSearchParams({ path });
  const response = await fetch(`${workspaceUrl(taskId, "files")}?${query}`);
  if (!response.ok) {
    throw await responseError(response, "Could not load workspace file");
  }
  return response.json();
}

export async function getCodingWorkspaceDiff(
  taskId: string
): Promise<WorkspaceDiff> {
  const response = await fetch(workspaceUrl(taskId, "diff"));
  if (!response.ok) {
    throw await responseError(response, "Could not load workspace diff");
  }
  return response.json();
}

export async function saveCodingWorkspaceFile(
  taskId: string,
  request: WorkspaceFileSaveRequest
): Promise<WorkspaceFileSaveResult> {
  const response = await fetch(workspaceUrl(taskId, "files"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw await responseError(response, "Could not save workspace file");
  }
  return response.json();
}

export async function getCodingWorkspaceWsTicket(
  taskId: string,
  kind: "watcher" | "pty"
): Promise<WorkspaceWsTicket> {
  const query = new URLSearchParams({ kind });
  const response = await fetch(
    `${workspaceUrl(taskId, "ws-ticket")}?${query}`,
    {
      method: "POST",
    }
  );
  if (!response.ok) {
    throw await responseError(response, "Could not authorize workspace stream");
  }
  return response.json();
}
