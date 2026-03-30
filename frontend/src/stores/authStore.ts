import { create } from 'zustand';
import type { UserInfo } from '../api/auth';

interface AuthState {
  user: UserInfo | null;
  token: string | null;
  isLoggedIn: boolean;
  loginModalOpen: boolean;
  registerModalOpen: boolean;
  setUser: (user: UserInfo | null) => void;
  login: (token: string, user: UserInfo) => void;
  logout: () => void;
  openLoginModal: () => void;
  closeLoginModal: () => void;
  openRegisterModal: () => void;
  closeRegisterModal: () => void;
}

const savedToken = localStorage.getItem('token');

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: savedToken,
  isLoggedIn: !!savedToken,
  loginModalOpen: false,
  registerModalOpen: false,

  setUser: (user) => set({ user }),

  login: (token, user) => {
    localStorage.setItem('token', token);
    set({ token, user, isLoggedIn: true, loginModalOpen: false, registerModalOpen: false });
  },

  logout: () => {
    localStorage.removeItem('token');
    set({ token: null, user: null, isLoggedIn: false });
  },

  openLoginModal: () => set({ loginModalOpen: true, registerModalOpen: false }),
  closeLoginModal: () => set({ loginModalOpen: false }),
  openRegisterModal: () => set({ registerModalOpen: true, loginModalOpen: false }),
  closeRegisterModal: () => set({ registerModalOpen: false }),
}));
