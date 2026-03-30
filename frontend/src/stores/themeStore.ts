import { create } from 'zustand';

type ThemeMode = 'light' | 'dark';

interface ThemeState {
  theme: ThemeMode;
  toggleTheme: () => void;
}

const savedTheme = (localStorage.getItem('theme') as ThemeMode) || 'light';

export const useThemeStore = create<ThemeState>((set) => ({
  theme: savedTheme,

  toggleTheme: () =>
    set((state) => {
      const next = state.theme === 'light' ? 'dark' : 'light';
      localStorage.setItem('theme', next);
      return { theme: next };
    }),
}));
