import { create } from 'zustand';

interface IngestStore {
  backgroundRepoUrl: string | null;
  setBackgroundRepo: (url: string) => void;
  clearBackgroundRepo: () => void;
}

export const useIngestStore = create<IngestStore>((set) => ({
  backgroundRepoUrl: null,
  setBackgroundRepo: (url) => set({ backgroundRepoUrl: url }),
  clearBackgroundRepo: () => set({ backgroundRepoUrl: null }),
}));
