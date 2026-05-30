"use client";

import { useCallback, useEffect, useState } from "react";
import type { AutonomyLevel } from "@/lib/types";

const STORAGE_KEY = "neos_autonomy_level";
const DEFAULT_LEVEL: AutonomyLevel = 1;

function parseAutonomyLevel(value: unknown): AutonomyLevel | null {
  const parsed = typeof value === "number" ? value : Number.parseInt(String(value), 10);
  return parsed === 0 || parsed === 1 || parsed === 2
    ? (parsed as AutonomyLevel)
    : null;
}

export function useAgentAutonomy() {
  const [autonomyLevel, setAutonomyLevelState] =
    useState<AutonomyLevel>(DEFAULT_LEVEL);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    const storedLevel = stored === null ? null : parseAutonomyLevel(stored);
    if (storedLevel !== null) {
      setAutonomyLevelState(storedLevel);
    }

    fetch("/api/autonomy-preference")
      .then((response) => response.json())
      .then((data) => {
        const level = parseAutonomyLevel(data.autonomy_level);
        if (level !== null) {
          setAutonomyLevelState(level);
          window.localStorage.setItem(STORAGE_KEY, String(level));
        }
      })
      .catch(() => {
        // Anonymous users keep the local preference only.
      })
      .finally(() => setIsLoading(false));
  }, []);

  const setAutonomyLevel = useCallback((level: AutonomyLevel) => {
    setAutonomyLevelState(level);
    window.localStorage.setItem(STORAGE_KEY, String(level));

    fetch("/api/autonomy-preference", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ autonomy_level: level }),
    }).catch(() => {
      // Preference sync is best-effort; localStorage remains source of truth.
    });
  }, []);

  return { autonomyLevel, setAutonomyLevel, isLoading };
}
