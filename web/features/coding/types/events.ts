export type CodingEvent = {
  v: 1;
  task_id: string;
  seq: number;
  event_id: string;
  type: string;
  ts: string;
  payload: Record<string, unknown>;
  run_id?: string | null;
  turn_id?: string | null;
  tool_call_id?: string | null;
  checkpoint_id?: string | null;
};
