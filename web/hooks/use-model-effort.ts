"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { effortRequest } from "@/lib/ai/effort";

type Row = { model: string; effort: string };

/** 사용자 × 모델 effort 선호. 저장은 백엔드 DB 이고 채팅 요청은 바뀌지 않는다. */
export function useModelEffort() {
  const [efforts, setEfforts] = useState<Record<string, string>>({});
  const latest = useRef(efforts);
  latest.current = efforts;

  useEffect(() => {
    fetch("/api/model-preferences")
      .then((response) => response.json())
      .then((rows: Row[]) => {
        if (Array.isArray(rows)) {
          setEfforts(
            Object.fromEntries(rows.map((row) => [row.model, row.effort]))
          );
        }
      })
      .catch(() => {
        // 선호를 못 읽으면 모든 모델이 기본값으로 보인다. 채팅은 영향 없다.
      });
  }, []);

  const setEffort = useCallback(
    async (catalogId: string, effort: string | null) => {
      const previous = latest.current;
      const next = { ...previous };
      if (effort === null) {
        delete next[catalogId];
      } else {
        next[catalogId] = effort;
      }
      setEfforts(next);
      const { url, init } = effortRequest(catalogId, effort);
      const response = await fetch(url, init).catch(() => null);
      if (!response || !response.ok) {
        setEfforts(previous);
        toast.error("Failed to save effort setting");
      }
    },
    []
  );

  return { efforts, setEffort };
}
