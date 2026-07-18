export function reconnectDelayMs(
  attempt: number,
  random: () => number = Math.random
): number {
  const base = Math.min(15_000, 500 * 2 ** Math.max(0, attempt));
  return Math.min(15_000, Math.round(base + base * 0.2 * random()));
}

export function nextContiguousSeq(current: number, received: number): number {
  return received === current + 1 ? received : current;
}
