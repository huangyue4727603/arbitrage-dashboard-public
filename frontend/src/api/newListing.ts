import client from './client';

export interface NewListingItem {
  coin_name: string;
  exchange: string;
  listing_days: number;
  current_funding_rate: number | null;
  settlement_period: number;
  price_change: number | null;
  change_1d: number | null;
  funding_1d: number | null;
  funding_3d: number | null;
}

export async function fetchNewListings(): Promise<NewListingItem[]> {
  const response = await client.get<{ data: NewListingItem[] }>('/api/new-listing');
  return response.data.data;
}
