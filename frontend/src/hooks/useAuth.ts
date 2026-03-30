import { useEffect } from 'react';
import { useAuthStore } from '../stores/authStore';
import { authApi } from '../api/auth';

export function useAuth() {
  const store = useAuthStore();

  useEffect(() => {
    if (store.token) {
      authApi.getMe().then((user) => {
        store.setUser(user);
      }).catch(() => {
        // Token invalid, force logout without reload loop
        localStorage.removeItem('token');
        store.logout();
      });
    }
  }, []);

  const requireAuth = (): boolean => {
    if (!store.isLoggedIn) {
      store.openLoginModal();
      return false;
    }
    return true;
  };

  return {
    user: store.user,
    token: store.token,
    isLoggedIn: store.isLoggedIn,
    login: store.login,
    logout: store.logout,
    requireAuth,
    openLoginModal: store.openLoginModal,
    openRegisterModal: store.openRegisterModal,
  };
}
