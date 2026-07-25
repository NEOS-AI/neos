import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  clampDockWidth,
  reduceDockKey,
} from "../../features/coding/components/workspace/workspace-dock-layout";

const TABLIST_PATTERN = /role="tablist"/;
const TAB_PATTERN = /role="tab"/;
const TABPANEL_PATTERN = /role="tabpanel"/;
const SEPARATOR_PATTERN = /<hr/;
const VERTICAL_PATTERN = /aria-orientation="vertical"/;
const FILES_PATTERN = /Files/;
const DIFF_PATTERN = /Diff/;
const TERMINAL_PATTERN = /Terminal/;
const MOBILE_PATTERN = /lg:hidden/;

test("dock width is clamped to accessible desktop bounds", () => {
  assert.equal(clampDockWidth(100, 1200), 320);
  assert.equal(clampDockWidth(900, 1200), 660);
  assert.equal(clampDockWidth(600, 2000), 600);
});

test("separator arrow keys resize in bounded increments", () => {
  assert.equal(reduceDockKey(420, "ArrowLeft", 1200), 404);
  assert.equal(reduceDockKey(420, "ArrowRight", 1200), 436);
  assert.equal(reduceDockKey(420, "Home", 1200), 320);
  assert.equal(reduceDockKey(420, "End", 1200), 660);
});

test("dock preserves ledger and exposes accessible workspace tabs", () => {
  const source = readFileSync(
    "features/coding/components/workspace/coding-workspace-dock.tsx",
    "utf8"
  );
  assert.match(source, TABLIST_PATTERN);
  assert.match(source, TAB_PATTERN);
  assert.match(source, TABPANEL_PATTERN);
  assert.match(source, SEPARATOR_PATTERN);
  assert.match(source, VERTICAL_PATTERN);
  assert.match(source, FILES_PATTERN);
  assert.match(source, DIFF_PATTERN);
  assert.match(source, TERMINAL_PATTERN);
  assert.match(source, MOBILE_PATTERN);
});
