import client from './client';

export interface FundingBreakItem {
  coin_name: string;
  exchange: string;
  funding_cap: number;
  funding_floor: number;
  realtime_funding: number;
  current_interval: string;
  basis: number;
  countdown_seconds: number;
  is_breaking: boolean;
}

export interface FundingBreakResponse {
  data: FundingBreakItem[];
}

export const fundingBreakApi = {
  getBreakingCoins: async (): Promise<FundingBreakResponse> => {
    const res = await client.get('/api/funding-break');
    return res.data;
  },
};
