const KEY = "meridian.videoIds";
const MAX = 50;

export function getTrackedVideoIds(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function trackVideoId(id: string): void {
  if (typeof window === "undefined") return;
  try {
    const ids = getTrackedVideoIds().filter((x) => x !== id);
    ids.unshift(id);
    window.localStorage.setItem(KEY, JSON.stringify(ids.slice(0, MAX)));
  } catch {
    /* ignore */
  }
}

export function clearTrackedVideoIds(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
