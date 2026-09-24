import { api, setAccessToken } from "@/lib/api/client";
import type { User } from "@/lib/types";

export interface LoginResponse {
  user: User;
  accessToken: string;
}

export interface RegisterResponse {
  user: User;
}

export interface MeResponse {
  user: User;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const res = await api.post<LoginResponse>("/api/auth/login", { email, password }, { auth: false });
  setAccessToken(res.accessToken);
  return res;
}

export async function register(email: string, password: string): Promise<RegisterResponse> {
  return api.post<RegisterResponse>(
    "/api/auth/register",
    { email, password },
    { auth: false },
  );
}

export async function fetchMe(): Promise<MeResponse> {
  return api.get<MeResponse>("/api/auth/me");
}

export async function logout(): Promise<void> {
  try {
    await api.post("/api/auth/logout");
  } finally {
    setAccessToken(null);
  }
}
