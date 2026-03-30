import client from './client';

export interface RankItem {
  coin: string;
  long_exchange: string;
  short_exchange: string;
  long_total_funding: number;
  short_total_funding: number;
  long_settlement_count: number;
  short_settlement_count: number;
  long_settlement_period: number;
  short_settlement_period: number;
  total_diff: number;
  // Realtime fields (merged from /realtime endpoint)
  current_spread?: number;
  current_basis?: number;
  // Price change fields (merged from /price-changes endpoint)
  change_1d?: number;
  change_3d?: number;
}

export interface RealtimeData {
  [key: string]: {
    spread: number;
    basis: number;
  };
}

export interface FundingDetail {
  time: number;
  time_str?: string;
  long_funding: number | null;
  short_funding: number | null;
  diff: number;
}

export interface DaySummary {
  date: string;
  long_total: number;
  short_total: number;
  diff: number;
}

export interface CalculatorResult {
  per_period: FundingDetail[];
  per_day: DaySummary[];
  summary: {
    long_total: number;
    short_total: number;
    total_diff: number;
  };
}

export interface RankingsResponse {
  data: RankItem[];
  start: number;
  end: number;
}

export const fundingApi = {
  getRankings: async (
    start?: number,
    end?: number,
    longExchange?: string,
    shortExchange?: string,
  ): Promise<RankingsResponse> => {
    const params: Record<string, string | number> = {};
    if (start !== undefined) params.start = start;
    if (end !== undefined) params.end = end;
    if (longExchange) params.long_exchange = longExchange;
    if (shortExchange) params.short_exchange = shortExchange;
    const res = await client.get('/api/funding-rank', { params });
    return res.data;
  },

  getRealtime: async (): Promise<RealtimeData> => {
    const res = await client.get('/api/funding-rank/realtime');
    return res.data.data;
  },

  getDetail: async (
    coin: string,
    longExchange: string,
    shortExchange: string,
    start?: number,
    end?: number,
  ): Promise<{ data: FundingDetail[] }> => {
    const params: Record<string, string | number> = {
      coin,
      long_exchange: longExchange,
      short_exchange: shortExchange,
    };
    if (start !== undefined) params.start = start;
    if (end !== undefined) params.end = end;
    const res = await client.get('/api/funding-rank/detail', { params });
    return res.data;
  },

  getPriceChanges: async (): Promise<Record<string, { change_1d?: number; change_3d?: number }>> => {
    const res = await client.get('/api/funding-rank/price-changes');
    return res.data.data;
  },

  getCoins: async (): Promise<string[]> => {
    const res = await client.get('/api/funding-rank/coins');
    return res.data.data;
  },

  calculate: async (
    coin: string,
    longExchange: string,
    shortExchange: string,
    start?: number,
    end?: number,
  ): Promise<{ data: CalculatorResult }> => {
    const res = await client.post('/api/funding-rank/calculator', {
      coin,
      long_exchange: longExchange,
      short_exchange: shortExchange,
      start,
      end,
    });
    return res.data;
  },
};
