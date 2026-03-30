import client from './client';

export interface PremiumFilterItem {
  coin_name: string;
  exchange: string;
  raw: string;
  cumulative_funding: number | null;
  realtime_basis: number | null;
  settlement_period: number | null;
}

export async function fetchPremiumFilter(ts: number, premiumThreshold: number): Promise<PremiumFilterItem[]> {
  const res = await client.get('/api/premium-filter', {
    params: { ts, premiumThreshold },
  });
  return res.data.data || [];
}

export async function fetchRealtimeBasis(coins: string[]): Promise<Record<string, number>> {
  const res = await client.get('/api/premium-filter/basis', {
    params: { coins: coins.join(',') },
  });
  return res.data.data || {};
}
