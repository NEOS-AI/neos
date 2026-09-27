/**
 * `GET /api/v1/coding/commands` 의 한 줄 (`neos/coding/commands/catalog.py`
 * `catalog_listings()`). 이름·별칭이 분기의 근거이고 나머지는 표시용이다.
 */
export type CodingCommandListing = {
  name: string;
  aliases: string[];
  family: "control" | "prompt" | "channel" | "disabled" | (string & {});
  description: string;
  usage: string;
  enabled: boolean;
  requires_task: boolean;
};

/** `POST /api/v1/coding/tasks/{id}/commands` 응답 (`CodingCommandResponse`). */
export type CodingCommandResult = {
  name: string;
  status:
    | "ok"
    | "queued"
    | "denied"
    | "unknown"
    | "unavailable"
    | "channel"
    | "chat";
  message: string;
  args: string;
  payload: Record<string, unknown>;
};
