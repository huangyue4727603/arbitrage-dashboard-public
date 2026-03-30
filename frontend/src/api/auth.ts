import client from './client';

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  password: string;
  confirm_password: string;
}

export interface UserInfo {
  id: number;
  username: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: UserInfo;
}

export const authApi = {
  async register(username: string, password: string, confirmPassword: string, inviteCode: string): Promise<AuthResponse> {
    const res = await client.post<AuthResponse>('/api/auth/register', {
      username,
      password,
      confirm_password: confirmPassword,
      invite_code: inviteCode,
    });
    return res.data;
  },

  async login(username: string, password: string): Promise<AuthResponse> {
    const res = await client.post<AuthResponse>('/api/auth/login', {
      username,
      password,
    });
    return res.data;
  },

  async logout(): Promise<void> {
    await client.post('/api/auth/logout');
  },

  async getMe(): Promise<UserInfo> {
    const res = await client.get<UserInfo>('/api/auth/me');
    return res.data;
  },
};
