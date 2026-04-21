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
  // Index constituent overlap (0..1) for this (coin, long, short) combo
  index_overlap?: number;
  // Binance index weights
  bn_alpha?: number;
  bn_future?: number;
  // Binance spot availability
  bn_spot?: boolean;
  // OI & LSR
  oi?: number;   // open interest in USDT
  lsr?: number;  // long/short ratio
  // Watchlist
  watched?: boolean;
  // Price trend (MA bullish alignment)
  trend_daily?: boolean;
  trend_h4?: boolean;
  trend_h1?: boolean;
  trend_m15?: boolean;
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

  getIndexOverlap: async (): Promise<Record<string, number>> => {
    const res = await client.get('/api/funding-rank/index-overlap');
    return res.data.data;
  },

  getBnIndexWeights: async (): Promise<Record<string, { alpha?: number; future?: number }>> => {
    const res = await client.get('/api/funding-rank/bn-index-weights');
    return res.data.data;
  },

  getPriceTrend: async (): Promise<Record<string, { daily: boolean; h4: boolean; h1: boolean; m15: boolean }>> => {
    const res = await client.get('/api/price-trend');
    const list = res.data.data as { coin_name: string; daily: boolean; h4: boolean; h1: boolean; m15: boolean }[];
    const map: Record<string, { daily: boolean; h4: boolean; h1: boolean; m15: boolean }> = {};
    for (const item of list) {
      map[item.coin_name] = { daily: item.daily, h4: item.h4, h1: item.h1, m15: item.m15 };
    }
    return map;
  },

  getOiLsr: async (): Promise<Record<string, { oi?: number; lsr?: number }>> => {
    const res = await client.get('/api/funding-rank/oi-lsr');
    return res.data.data;
  },

  getWatchlist: async (): Promise<string[]> => {
    const res = await client.get('/api/funding-rank/watchlist');
    return res.data.data;
  },

  addWatch: async (coin: string): Promise<void> => {
    await client.post(`/api/funding-rank/watchlist/${coin}`);
  },

  removeWatch: async (coin: string): Promise<void> => {
    await client.delete(`/api/funding-rank/watchlist/${coin}`);
  },

  getBnSpot: async (): Promise<string[]> => {
    const res = await client.get('/api/funding-rank/bn-spot');
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
