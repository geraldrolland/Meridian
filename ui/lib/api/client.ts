import { getAccessToken, refreshAccessToken, setAccessToken } from "@/lib/auth/token-store";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:3001";



export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function extractMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const b = body as { error?: string; detail?: string; message?: string };
    if (b.error) return b.error;
    if (b.detail) return b.detail;
    if (b.message) return b.message;
    if (Array.isArray(b.detail)) {
      return b.detail
        .map((d) => (typeof d === "string" ? d : (d as { msg?: string })?.msg ?? ""))
        .filter(Boolean)
        .join(", ");
    }
  }
  return fallback;
}

export interface RequestOptions extends Omit<RequestInit, "body" | "headers"> {
  body?: unknown;
  headers?: Record<string, string>;
  auth?: boolean;
}

async function rawRequest(path: string, options: RequestOptions, retried = false): Promise<Response> {
  const { body, headers = {}, auth = true, ...rest } = options;
  const token = getAccessToken();

  const finalHeaders: Record<string, string> = {
    ...headers,
  };
  if (body !== undefined && !(body instanceof FormData)) {
    finalHeaders["Content-Type"] = finalHeaders["Content-Type"] ?? "application/json";
  }
  if (auth && token) {
    finalHeaders["Authorization"] = `Bearer ${token}`;
  }

  const payload =
    body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body);

  const res = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: finalHeaders,
    body: payload,
    credentials: "include",
  });

  if (res.status === 401 && auth && !retried) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      return rawRequest(path, options, true);
    }
  }

  return res;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const res = await rawRequest(path, options);
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }

  if (!res.ok) {
    throw new ApiError(res.status, extractMessage(parsed, `Request failed (${res.status})`), parsed);
  }

  return parsed as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    apiRequest<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiRequest<T>(path, { ...options, method: "POST", body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiRequest<T>(path, { ...options, method: "PUT", body }),
};

export { setAccessToken };
