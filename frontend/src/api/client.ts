import axios from 'axios';

const client = axios.create({
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
    if (error.response?.status === 401) {
      const token = localStorage.getItem('token');
      if (token) {
        localStorage.removeItem('token');
        // Use store to logout properly
        import('../stores/authStore').then(({ useAuthStore }) => {
          useAuthStore.getState().logout();
        });
      }
    }
    return Promise.reject(error);
  },
);

export default client;
