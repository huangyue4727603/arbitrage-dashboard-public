import client from './client';

export interface BasisRecord {
  coin_name: string;
  current_basis: number | null;
  min_basis: number;
  alert_count: number;
  change_1d: number | null;
  last_alert_at: string;
}

export interface TimelineEvent {
  coin_name: string;
  alert_type: '新机会' | '基差扩大';
  basis: number;
  time: string;
  timestamp: number;
}

export interface BasisMonitorData {
  records: BasisRecord[];
  timeline: TimelineEvent[];
}

export interface BasisConfig {
  basis_threshold: number;
  expand_multiplier: number;
  blocked_coins: string;
  temp_blocked_coins: string;
}

export const basisMonitorApi = {
  getData: async (): Promise<BasisMonitorData> => {
    const res = await client.get('/api/basis-monitor');
    return res.data.data;
  },

  refresh: async (): Promise<BasisMonitorData> => {
    const res = await client.post('/api/basis-monitor/refresh');
    return res.data.data;
  },

  clear: async (): Promise<void> => {
    await client.post('/api/basis-monitor/clear');
  },

  getConfig: async (): Promise<BasisConfig> => {
    const res = await client.get('/api/basis-monitor/config');
    return res.data.data;
  },

  getCoinAlerts: async (coin: string): Promise<TimelineEvent[]> => {
    const res = await client.get('/api/basis-monitor/coin-alerts', { params: { coin } });
    return res.data.data || [];
  },

  updateConfig: async (threshold: number, multiplier: number, blockedCoins: string, tempBlockedCoins: string): Promise<void> => {
    await client.put('/api/basis-monitor/config', null, {
      params: {
        basis_threshold: threshold,
        expand_multiplier: multiplier,
        blocked_coins: blockedCoins,
        temp_blocked_coins: tempBlockedCoins,
      },
    });
  },
};
