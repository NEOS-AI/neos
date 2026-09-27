import "../dom-setup";
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { act } from "react";
import { CodingSteerComposer } from "@/features/coding/components/coding-steer-composer";
import { renderComponent } from "../render";

/**
 * 입력기는 하나, 목적지는 둘이다. 카탈로그에 있는 이름만 커맨드로 가고
 * 나머지는 steer 로 간다(`features/coding/commands/route-input.ts`).
 * 여기서는 그 분기가 **실제 요청**까지 이어지는지를 본다.
 */

let calls: Array<{ url: string; body: unknown }> = [];

beforeEach(() => {
  calls = [];
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, body });
    if (url === "/api/coding/commands") {
      return Response.json({
        commands: [
          {
            name: "plan",
            aliases: [],
            family: "prompt",
            description: "Switch to a read-only implementation plan.",
            usage: "/plan [focus]",
            enabled: true,
            requires_task: true,
          },
        ],
      });
    }
    if (url.endsWith("/commands")) {
      return Response.json({
        name: "plan",
        status: "queued",
        message: "Plan mode queued for the next safe point.",
        args: "",
        payload: {},
      });
    }
    return Response.json({ steering_id: "st_1", mode: "safe_point" }, { status: 202 });
  };
});

function typeInto(textarea: HTMLTextAreaElement, value: string) {
  const nativeSetter = Object.getOwnPropertyDescriptor(
    Object.getPrototypeOf(textarea),
    "value"
  )?.set;
  if (!nativeSetter) {
    throw new Error("textarea.value 네이티브 setter를 찾지 못했다");
  }
  nativeSetter.call(textarea, value);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

async function renderAndType(value: string) {
  const host = await renderComponent(
    <CodingSteerComposer disabled={false} taskId="ct_1" />
  );
  // SWR 가 카탈로그 fetch 를 끝낼 때까지 마이크로태스크를 비운다.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  const textarea = host.querySelector(
    '[aria-label="Steer coding agent"]'
  ) as HTMLTextAreaElement;
  await act(async () => {
    typeInto(textarea, value);
  });
  return host;
}

async function submit(host: HTMLElement) {
  const form = host.querySelector("form") as HTMLFormElement;
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

test("a catalog command goes to the command route and shows its reply", async () => {
  const host = await renderAndType("/plan parser only");
  await submit(host);

  const sent = calls.filter((call) => call.url !== "/api/coding/commands");
  assert.deepEqual(sent, [
    { url: "/api/coding/tasks/ct_1/commands", body: { text: "/plan parser only" } },
  ]);
  assert.match(host.textContent ?? "", /Plan mode queued for the next safe point\./);
});

test("a slash path is steered as an instruction", async () => {
  const host = await renderAndType("/src/app.py 고쳐줘");
  await submit(host);

  const sent = calls.filter((call) => call.url !== "/api/coding/commands");
  assert.deepEqual(sent, [
    {
      url: "/api/coding/tasks/ct_1/steer",
      body: { instruction: "/src/app.py 고쳐줘", mode: "safe_point" },
    },
  ]);
});

test("the composer says where the input will go before it is sent", async () => {
  const host = await renderAndType("/plan");
  assert.match(host.textContent ?? "", /Run \/plan/);
});
