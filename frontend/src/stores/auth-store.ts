import { create } from "zustand";
import { persist } from "zustand/middleware";
import { api, getReadableError } from "../lib/api";
import type { LoginInput, RegisterInput, User } from "../lib/schemas";

interface AuthState {
  token: string | null;
  user: User | null;
  initialized: boolean;
  isInitializing: boolean;
  isSubmitting: boolean;
  error: string | null;
  initialize: () => Promise<void>;
  login: (input: LoginInput) => Promise<void>;
  register: (input: RegisterInput) => Promise<void>;
  logout: () => void;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      initialized: false,
      isInitializing: false,
      isSubmitting: false,
      error: null,

      initialize: async () => {
        const { token, initialized, isInitializing } = get();
        if (initialized || isInitializing) return;

        if (!token) {
          set({ initialized: true });
          return;
        }

        set({ isInitializing: true, error: null });
        try {
          const user = await api.me(token);
          set({ user, initialized: true, isInitializing: false });
        } catch {
          set({
            token: null,
            user: null,
            initialized: true,
            isInitializing: false,
            error: null,
          });
        }
      },

      login: async (input) => {
        set({ isSubmitting: true, error: null });
        try {
          const session = await api.login(input);
          const user = await api.me(session.access_token);
          set({
            token: session.access_token,
            user,
            initialized: true,
            isSubmitting: false,
          });
        } catch (error) {
          const message = getReadableError(error);
          set({ isSubmitting: false, error: message });
          throw error;
        }
      },

      register: async (input) => {
        set({ isSubmitting: true, error: null });
        try {
          const { confirmPassword: _, ...registration } = input;
          await api.register(registration);
          const session = await api.login({ email: input.email, password: input.password });
          const user = await api.me(session.access_token);
          set({
            token: session.access_token,
            user,
            initialized: true,
            isSubmitting: false,
          });
        } catch (error) {
          const message = getReadableError(error);
          set({ isSubmitting: false, error: message });
          throw error;
        }
      },

      logout: () => {
        set({ token: null, user: null, initialized: true, error: null });
      },

      clearError: () => set({ error: null }),
    }),
    {
      name: "site-scan-session",
      partialize: (state) => ({ token: state.token }),
    },
  ),
);
