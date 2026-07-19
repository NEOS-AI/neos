export type CodingTask = {
  task_id: string;
  status: string;
  version: number;
  last_seq: number;
  created_at: string;
  updated_at: string;
};

export type CodingWsTicket = {
  ticket: string;
  expires_in: number;
  websocket_url: string;
};

import type { CodingProjectionSnapshot } from "@/features/coding/types/projection";

export class CodingAPIError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "CodingAPIError";
    this.status = status;
  }
}

async function responseError(response: Response, fallback: string) {
  const body = await response.json().catch(() => ({}));
  return new CodingAPIError(
    response.status,
    body.error ?? body.detail ?? fallback
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
