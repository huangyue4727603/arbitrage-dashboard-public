import client from './client';

export interface PriceTrendItem {
  coin_name: string;
  daily: boolean;
  h4: boolean;
  h1: boolean;
  m15: boolean;
  sort_score: number;
}

export interface PriceTrendResponse {
  data: PriceTrendItem[];
}

export const priceTrendApi = {
  getData: async (): Promise<PriceTrendResponse> => {
    const res = await client.get('/api/price-trend');
    return res.data;
  },

  refresh: async (): Promise<PriceTrendResponse> => {
    const res = await client.post('/api/price-trend/refresh');
    return res.data;
  },
};
