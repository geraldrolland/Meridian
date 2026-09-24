const STORAGE_KEY = "meridian.accessToken";

let memoryToken: string | null = null;

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return memoryToken;
  try {
    return window.sessionStorage.getItem(STORAGE_KEY) ?? memoryToken;
  } catch {
    return memoryToken;
  }
}

export function setAccessToken(token: string | null): void {
  memoryToken = token;
  if (typeof window === "undefined") return;
  try {
    if (token) window.sessionStorage.setItem(STORAGE_KEY, token);
    else window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

let refreshPromise: Promise<string | null> | null = null;
let refreshBlockedUntil = 0;

export async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise;
  if (Date.now() < refreshBlockedUntil) return null;

  refreshPromise = (async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE || "http://localhost:3001"}/api/auth/refresh-token`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      if (res.status === 429) {
        const retryAfter = Number(res.headers.get("Retry-After"));
        const seconds = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : 5;
        refreshBlockedUntil = Date.now() + Math.min(30_000, Math.max(1_000, seconds * 1000));
        return null;
      }
      if (!res.ok) {
        setAccessToken(null);
        return null;
      }
      const data = (await res.json()) as { accessToken?: string };
      if (data.accessToken) {
        setAccessToken(data.accessToken);
        return data.accessToken;
      }
      setAccessToken(null);
      return null;
    } catch {
      setAccessToken(null);
      return null;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}
