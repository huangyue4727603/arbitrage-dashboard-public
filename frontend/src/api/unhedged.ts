import client from './client';

export interface UnhedgedType1 {
  type: 'type1';
  coin: string;
  long_exchange: string;
  short_exchange: string;
  spread: number;
  funding_diff: number;
  short_basis: number;
  alert_time: string;
  timestamp: number;
}

export interface UnhedgedType2 {
  type: 'type2';
  coin: string;
  short_exchange: string;
  long_exchange: string;
  spread: number;
  short_basis: number;
  price_change_5m: number;
  alert_time: string;
  timestamp: number;
}

export interface UnhedgedResponse {
  type1: UnhedgedType1[];
  type2: UnhedgedType2[];
}

export const unhedgedApi = {
  getAlerts: async (): Promise<UnhedgedResponse> => {
    const res = await client.get('/api/unhedged');
    return res.data;
  },
};
