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
