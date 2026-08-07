/**
 * Format seconds as MM:SS (e.g. 65 -> "01:05").
 */
export function formatDuration(seconds: number): string {
  const mm = Math.floor(seconds / 60).toString().padStart(2, "0");
  const ss = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${mm}:${ss}`;
}

/**
 * Convert seconds to a human-readable duration (e.g. "1m 45s").
 */
export function translateDurationType(seconds: number): string {
  if (!seconds) return "0s";
  const mm = Math.floor(seconds / 60);
  const ss = Math.floor(seconds % 60);
  return mm > 0 ? `${mm}m ${ss}s` : `${ss}s`;
}