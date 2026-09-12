import "../dom-setup";
import assert from "node:assert/strict";
import test from "node:test";
import { act } from "react";
import { CodingApprovalCard } from "@/features/coding/components/coding-approval-card";
import type { CodingApprovalView } from "@/features/coding/types/projection";
import { renderComponent } from "../render";

const baseApproval = (
  overrides: Partial<CodingApprovalView> & {
    display_summary?: Record<string, unknown>;
  } = {}
): CodingApprovalView => ({
  approval_id: "ca_1",
  tool_name: "ask_user.v1",
  risk: "user_question",
  status: "pending",
  requested_at: "2026-07-21T00:00:00Z",
  expires_at: "2026-07-21T00:15:00Z",
  display_summary: {
    questions: ["Which runner?"],
    options: [["pytest", "unittest"]],
  },
  ...overrides,
});

test("ask-user approve stays disabled until every question has a value", async () => {
  const host = await renderComponent(
    <CodingApprovalCard
      approval={baseApproval()}
      live
      taskId="ct_1"
    />
  );
  const approve = host.querySelector(
    '[aria-label="Approve tool request"]'
  ) as HTMLButtonElement;
  const deny = host.querySelector(
    '[aria-label="Deny tool request"]'
  ) as HTMLButtonElement;

  assert.equal(approve.disabled, true);
  assert.equal(deny.disabled, false);

  const radio = host.querySelector('input[type="radio"][value="pytest"]') as HTMLInputElement;
  await act(async () => {
    radio.click();
  });

  assert.equal(approve.disabled, false);
});

test("Other counts as an answer only when its text is non-empty", async () => {
  const host = await renderComponent(
    <CodingApprovalCard
      approval={baseApproval()}
      live
      taskId="ct_1"
    />
  );
  const approve = host.querySelector(
    '[aria-label="Approve tool request"]'
  ) as HTMLButtonElement;
  const other = host.querySelector('input[aria-label="Other"]') as HTMLInputElement;

  assert.equal(approve.disabled, true);
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value"
    )?.set;
    setter?.call(other, "nose");
    other.dispatchEvent(new Event("input", { bubbles: true }));
  });
  assert.equal(approve.disabled, false);
});

test("multi_select questions use checkboxes and allow several options", async () => {
  const host = await renderComponent(
    <CodingApprovalCard
      approval={baseApproval({
        display_summary: {
          questions: [
            {
              prompt: "Which files?",
              options: ["a.py", "b.py", "c.py"],
              multi_select: true,
            },
          ],
        },
      })}
      live
      taskId="ct_1"
    />
  );

  const boxes = [
    ...host.querySelectorAll('input[type="checkbox"]'),
  ] as HTMLInputElement[];
  assert.equal(boxes.length >= 3, true);
  assert.equal(host.querySelectorAll('input[type="radio"]').length, 0);

  const approve = host.querySelector(
    '[aria-label="Approve tool request"]'
  ) as HTMLButtonElement;
  assert.equal(approve.disabled, true);

  await act(async () => {
    boxes[0].click();
    boxes[1].click();
  });
  assert.equal(approve.disabled, false);
  assert.equal(boxes[0].checked, true);
  assert.equal(boxes[1].checked, true);
});

test("set_phase implement approval renders plan body fields when present", async () => {
  const host = await renderComponent(
    <CodingApprovalCard
      approval={baseApproval({
        tool_name: "set_phase.v1",
        risk: "workspace_write",
        display_summary: {
          phase: "implement",
          path: "PLAN.md",
          plan_preview: "Edit auth and add tests.",
          plan: "1. Read auth.py\n2. Patch login",
          critical_files: ["src/auth.py", "tests/test_auth.py"],
        },
      })}
      live
      taskId="ct_1"
    />
  );

  assert.match(host.textContent ?? "", /Edit auth and add tests/);
  assert.match(host.textContent ?? "", /Patch login/);
  assert.match(host.textContent ?? "", /src\/auth\.py/);
  assert.match(host.textContent ?? "", /PLAN\.md/);
});

test("set_phase implement approval does not invent a plan when fields are absent", async () => {
  const host = await renderComponent(
    <CodingApprovalCard
      approval={baseApproval({
        tool_name: "set_phase.v1",
        risk: "workspace_write",
        display_summary: { phase: "implement", path: "app.py" },
      })}
      live
      taskId="ct_1"
    />
  );

  assert.match(host.textContent ?? "", /app\.py/);
  assert.doesNotMatch(host.textContent ?? "", /Critical Files/);
  assert.equal((host.textContent ?? "").includes("plan_preview"), false);
});
