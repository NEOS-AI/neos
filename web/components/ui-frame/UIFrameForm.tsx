"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import type { UIFramePayload, UIFrameComponent } from "@/lib/open-responses-types";
import { submitUIFrameClient } from "@/lib/ui-frame-client";
import { readSseStream } from "@/lib/sse-stream";
import { TextField } from "./components/TextField";
import { DatePicker } from "./components/DatePicker";
import { TimePicker } from "./components/TimePicker";
import { SelectField } from "./components/SelectField";
import { MultiSelect } from "./components/MultiSelect";
import { SliderField } from "./components/SliderField";
import { CheckboxField } from "./components/CheckboxField";
import { ButtonField } from "./components/ButtonField";

interface Props {
  uiFrame: UIFramePayload;
  onSubmitted?: () => void;
}

type FormValues = Record<string, unknown>;

function getDefaultValue(component: UIFrameComponent): unknown {
  if (component.default_value !== undefined) return component.default_value;
  switch (component.type) {
    case "checkbox":      return false;
    case "multi_select":  return [];
    case "slider":        return component.min ?? 0;
    default:              return "";
  }
}

export function UIFrameForm({ uiFrame, onSubmitted }: Props) {
  const inputComponents = uiFrame.components.filter(
    (c) => c.type !== "divider" && c.type !== "button"
  );
  const buttonComponents = uiFrame.components.filter((c) => c.type === "button");

  const initialValues: FormValues = Object.fromEntries(
    inputComponents.map((c) => [c.id, getDefaultValue(c)])
  );

  const [values, setValues] = useState<FormValues>(initialValues);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resultText, setResultText] = useState<string | null>(null);

  const setValue = (id: string, value: unknown) => {
    setValues((prev) => ({ ...prev, [id]: value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // required 필드 검증 — 타입별 falsy 오탐 방지
    const missing = inputComponents
      .filter((c) => {
        if (!c.required) return false;
        const v = values[c.id];
        // checkbox: false도 유효한 선택 → 항상 통과
        if (c.type === "checkbox") return false;
        // multi_select: 빈 배열만 오류
        if (c.type === "multi_select") return Array.isArray(v) && v.length === 0;
        // slider/number: 0을 포함한 숫자는 유효
        if (typeof v === "number") return false;
        // 나머지: null, undefined, "" 만 오류
        return v === null || v === undefined || v === "";
      })
      .map((c) => c.label ?? c.id);

    if (missing.length > 0) {
      setError(`필수 항목을 입력하세요: ${missing.join(", ")}`);
      return;
    }

    setError(null);
    setSubmitting(true);

    try {
      const response = await submitUIFrameClient(
        uiFrame.frame_id,
        uiFrame.session_id ?? "",
        values as Record<string, unknown>,
        uiFrame.conversation_id
      );
      setSubmitted(true);
      onSubmitted?.();

      // SSE 스트림 읽어 최종 워크플로우 응답 추출
      if (response.body) {
        const text = await readSseStream(response.body);
        if (text) setResultText(text);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "제출 중 오류가 발생했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">제출이 완료되었습니다.</p>
        {resultText ? (
          <p className="text-sm">{resultText}</p>
        ) : (
          <p className="text-xs text-muted-foreground animate-pulse">
            응답을 기다리는 중...
          </p>
        )}
      </div>
    );
  }

  const disabled = submitting || submitted;

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      {inputComponents.map((component) => {
        switch (component.type) {
          case "text_field":
            return (
              <TextField
                key={component.id}
                component={component}
                value={(values[component.id] as string) ?? ""}
                onChange={(v) => setValue(component.id, v)}
                disabled={disabled}
              />
            );
          case "date_picker":
            return (
              <DatePicker
                key={component.id}
                component={component}
                value={(values[component.id] as string) ?? ""}
                onChange={(v) => setValue(component.id, v)}
                disabled={disabled}
              />
            );
          case "time_picker":
            return (
              <TimePicker
                key={component.id}
                component={component}
                value={(values[component.id] as string) ?? ""}
                onChange={(v) => setValue(component.id, v)}
                disabled={disabled}
              />
            );
          case "select":
            return (
              <SelectField
                key={component.id}
                component={component}
                value={(values[component.id] as string) ?? ""}
                onChange={(v) => setValue(component.id, v)}
                disabled={disabled}
              />
            );
          case "multi_select":
            return (
              <MultiSelect
                key={component.id}
                component={component}
                value={(values[component.id] as string[]) ?? []}
                onChange={(v) => setValue(component.id, v)}
                disabled={disabled}
              />
            );
          case "slider":
            return (
              <SliderField
                key={component.id}
                component={component}
                value={(values[component.id] as number) ?? (component.min ?? 0)}
                onChange={(v) => setValue(component.id, v)}
                disabled={disabled}
              />
            );
          case "checkbox":
            return (
              <CheckboxField
                key={component.id}
                component={component}
                value={(values[component.id] as boolean) ?? false}
                onChange={(v) => setValue(component.id, v)}
                disabled={disabled}
              />
            );
          case "divider":
            return <Separator key={component.id} />;
          default:
            return null;
        }
      })}

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="flex gap-2 flex-wrap">
        {buttonComponents.map((btn) => (
          <ButtonField key={btn.id} component={btn} disabled={disabled} />
        ))}
        <Button type="submit" disabled={disabled}>
          {submitting ? "제출 중…" : "제출"}
        </Button>
      </div>
    </form>
  );
}
