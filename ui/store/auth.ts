import { create } from "zustand";
import { fetchMe, login as apiLogin, logout as apiLogout, register as apiRegister } from "@/lib/api/auth";
import { getAccessToken, refreshAccessToken, setAccessToken } from "@/lib/auth/token-store";
import { clearTrackedVideoIds } from "@/lib/video/library";
import type { User } from "@/lib/types";

interface AuthState {
  user: User | null;
  accessToken: string | null;
  hydrated: boolean;
  loading: boolean;
  error: string | null;
  hydrate: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  accessToken: typeof window === "undefined" ? null : getAccessToken(),
  hydrated: false,
  loading: false,
  error: null,

  hydrate: async () => {
    try {
      let token = getAccessToken();
      if (!token) token = await refreshAccessToken();
      if (!token) {
        set({ user: null, accessToken: null, hydrated: true });
        return;
      }
      const me = await fetchMe();
      set({ user: me.user, accessToken: token, hydrated: true, error: null });
    } catch {
      set({ user: null, accessToken: null, hydrated: true });
    }
  },

  login: async (email, password) => {
    set({ loading: true, error: null });
    try {
      const res = await apiLogin(email, password);
      set({ user: res.user, accessToken: res.accessToken, loading: false });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : "Login failed" });
      throw e;
    }
  },

  register: async (email, password) => {
    set({ loading: true, error: null });
    try {
      await apiRegister(email, password);
      set({ loading: false });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : "Registration failed" });
      throw e;
    }
  },

  logout: async () => {
    try {
      await apiLogout();
    } finally {
      setAccessToken(null);
      clearTrackedVideoIds();
      set({ user: null, accessToken: null });
    }
  },

  clearError: () => set({ error: null }),
}));
