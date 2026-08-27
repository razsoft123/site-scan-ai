import { create } from "zustand";
import { api, getReadableError } from "../lib/api";
import type { AuditDetail, AuditInput, AuditSummary } from "../lib/schemas";

interface AuditState {
  audits: AuditSummary[];
  selectedAudit: AuditDetail | null;
  isLoadingList: boolean;
  isLoadingDetail: boolean;
  isCreating: boolean;
  error: string | null;
  loadAudits: (token: string) => Promise<void>;
  selectAudit: (token: string, auditId: number) => Promise<void>;
  createAudit: (token: string, input: AuditInput) => Promise<void>;
  clear: () => void;
  clearError: () => void;
}

export const useAuditStore = create<AuditState>((set) => ({
  audits: [],
  selectedAudit: null,
  isLoadingList: false,
  isLoadingDetail: false,
  isCreating: false,
  error: null,

  loadAudits: async (token) => {
    set({ isLoadingList: true, error: null });
    try {
      const audits = await api.listAudits(token);
      set({ audits, isLoadingList: false });
    } catch (error) {
      set({ isLoadingList: false, error: getReadableError(error) });
    }
  },

  selectAudit: async (token, auditId) => {
    set({ isLoadingDetail: true, error: null });
    try {
      const selectedAudit = await api.getAudit(token, auditId);
      set({ selectedAudit, isLoadingDetail: false });
    } catch (error) {
      set({ isLoadingDetail: false, error: getReadableError(error) });
    }
  },

  createAudit: async (token, input) => {
    set({ isCreating: true, error: null });
    try {
      const created = await api.createAudit(token, input);
      set((state) => ({
        selectedAudit: created,
        audits: [created, ...state.audits.filter((audit) => audit.id !== created.id)],
        isCreating: false,
      }));
    } catch (error) {
      const message = getReadableError(error);
      set({ isCreating: false, error: message });
      throw error;
    }
  },

  clear: () => {
    set({
      audits: [],
      selectedAudit: null,
      isLoadingList: false,
      isLoadingDetail: false,
      isCreating: false,
      error: null,
    });
  },

  clearError: () => set({ error: null }),
}));
