"use client";

import { formatDistanceToNow } from "date-fns";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  listCodingTasks,
  type CodingTaskListItem,
} from "@/features/coding/api/coding-api";

type CodingTaskListProps = {
  compact?: boolean;
};

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return formatDistanceToNow(date, { addSuffix: true });
}

export function CodingTaskList({ compact = false }: CodingTaskListProps) {
  const [tasks, setTasks] = useState<CodingTaskListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listCodingTasks()
      .then((result) => {
        if (!cancelled) {
          setTasks(result.tasks);
          setError(null);
        }
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(
            cause instanceof Error ? cause.message : "Could not load tasks"
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <p
        className={
          compact
            ? "px-2 text-destructive text-xs"
            : "text-destructive text-sm"
        }
      >
        {error}
      </p>
    );
  }

  if (tasks === null) {
    return (
      <p
        className={
          compact
            ? "px-2 text-muted-foreground text-xs"
            : "text-muted-foreground text-sm"
        }
      >
        Loading recent tasks…
      </p>
    );
  }

  if (tasks.length === 0) {
    return (
      <p
        className={
          compact
            ? "px-2 text-muted-foreground text-xs"
            : "text-muted-foreground text-sm"
        }
      >
        No recent tasks.
      </p>
    );
  }

  return (
    <ul className={compact ? "grid gap-0.5 px-1" : "grid gap-2"}>
      {tasks.map((task) => (
        <li key={task.task_id}>
          <Link
            className={
              compact
                ? "flex flex-col gap-0.5 rounded-md px-2 py-1.5 text-sidebar-foreground hover:bg-sidebar-accent"
                : "flex items-center justify-between gap-3 border-amber-400/30 border-l-2 bg-amber-400/5 px-4 py-3 text-sm hover:bg-amber-400/10"
            }
            href={`/code/tasks/${task.task_id}`}
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span
                  className={
                    compact
                      ? "font-mono text-[10px] text-amber-400 uppercase tracking-[0.16em]"
                      : "font-mono text-amber-400 text-xs uppercase tracking-[0.16em]"
                  }
                >
                  {task.status}
                </span>
                <span
                  className={
                    compact
                      ? "truncate text-sidebar-foreground/80 text-xs"
                      : "truncate text-foreground"
                  }
                >
                  {task.prompt}
                </span>
              </div>
            </div>
            <time
              className={
                compact
                  ? "shrink-0 text-[10px] text-muted-foreground"
                  : "shrink-0 text-muted-foreground text-xs"
              }
              dateTime={task.updated_at}
            >
              {formatUpdatedAt(task.updated_at)}
            </time>
          </Link>
        </li>
      ))}
    </ul>
  );
}
