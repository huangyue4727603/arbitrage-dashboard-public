import axios from 'axios';

const client = axios.create({
  baseURL: '/arbitrage',
  timeout: 120000,
  headers: {
    'Content-Type': 'application/json',
  },
});

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    // Only clear token on explicit auth errors, not on network/server errors
    if (error.response?.status === 401) {
      const detail = error.response?.data?.detail || '';
      // Only logout if the token is actually invalid/expired, not on transient errors
      if (detail === 'Invalid or expired token' || detail === 'User not found') {
        const token = localStorage.getItem('token');
        if (token) {
          localStorage.removeItem('token');
          import('../stores/authStore').then(({ useAuthStore }) => {
            useAuthStore.getState().logout();
          });
        }
      }
    }
    return Promise.reject(error);
  },
);

export default client;
