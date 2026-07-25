import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const PRE_PATTERN = /<pre/;
const INPUT_PATTERN = /<input/;
const RESIZE_PATTERN = /ResizeObserver/;
const TICKET_PATTERN = /getCodingWorkspaceWsTicket/;
const PTY_PROTOCOL_PATTERN = /neos\.coding\.pty\.v1/;
const RAW_HTML_PATTERN = /dangerouslySetInnerHTML/;
const RECONNECT_STATE_PATTERN = /terminalRef\.current/;

test("terminal is a bounded text surface with its own connection", () => {
  const source = readFileSync(
    "features/coding/components/workspace/coding-terminal.tsx",
    "utf8"
  );
  assert.match(source, PRE_PATTERN);
  assert.match(source, INPUT_PATTERN);
  assert.match(source, RESIZE_PATTERN);
  assert.match(source, TICKET_PATTERN);
  assert.match(source, PTY_PROTOCOL_PATTERN);
  assert.match(source, RECONNECT_STATE_PATTERN);
  assert.doesNotMatch(source, RAW_HTML_PATTERN);
});
