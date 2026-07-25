export type WorkspaceDockTab = "files" | "diff" | "terminal";

export function clampDockWidth(width: number, viewport: number): number {
  return Math.min(Math.max(width, 320), Math.min(720, viewport * 0.55));
}

export function reduceDockKey(
  width: number,
  key: string,
  viewport: number
): number {
  if (key === "Home") {
    return clampDockWidth(320, viewport);
  }
  if (key === "End") {
    return clampDockWidth(720, viewport);
  }
  if (key === "ArrowLeft") {
    return clampDockWidth(width - 16, viewport);
  }
  if (key === "ArrowRight") {
    return clampDockWidth(width + 16, viewport);
  }
  return width;
}
