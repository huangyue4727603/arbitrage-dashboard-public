import client from './client';

// ---- Types ----

export interface LarkBot {
  id: number;
  name: string;
  webhook_url: string;
  created_at: string;
}

export interface LarkBotForm {
  name: string;
  webhook_url: string;
}

export interface Monitor {
  id: number;
  coin_name: string;
  long_exchange: string;
  short_exchange: string;
  spread_threshold: number | null;
  price_threshold: number | null;
  oi_drop_1h_threshold: number | null;
  oi_drop_4h_threshold: number | null;
  sound_enabled: boolean;
  popup_enabled: boolean;
  lark_bot_id: number | null;
  is_active: boolean;
  created_at: string;
  // Real-time values (populated via WebSocket or polling, may be undefined)
  current_spread?: number | null;
  current_price?: number | null;
  current_oi_drop_1h?: number | null;
  current_oi_drop_4h?: number | null;
}

export interface MonitorForm {
  coin_name: string;
  long_exchange: string;
  short_exchange: string;
  spread_threshold?: number | null;
  price_threshold?: number | null;
  oi_drop_1h_threshold?: number | null;
  oi_drop_4h_threshold?: number | null;
  sound_enabled: boolean;
  popup_enabled: boolean;
  lark_bot_id?: number | null;
}

export interface BasisConfig {
  id: number;
  basis_threshold: number;
  expand_multiplier: number;
  clear_interval_hours: number;
  blocked_coins: string[] | null;
  sound_enabled: boolean;
  popup_enabled: boolean;
  lark_bot_id: number | null;
}

export interface BasisConfigForm {
  basis_threshold: number;
  expand_multiplier: number;
  clear_interval_hours: number;
  blocked_coins?: string[] | string;
  temp_blocked_coins?: string;
  sound_enabled: boolean;
  popup_enabled: boolean;
  lark_bot_id?: number | null;
}

export interface BasisHistoryItem {
  id: number;
  alert_at: string;
  coin_name: string;
  alert_type: string;
  basis_value: number;
}

export interface UnhedgedConfig {
  id: number;
  sound_enabled: boolean;
  popup_enabled: boolean;
  lark_bot_id: number | null;
}

export interface UnhedgedConfigForm {
  sound_enabled: boolean;
  popup_enabled: boolean;
  lark_bot_id?: number | null;
}

export interface NotificationSettings {
  sound_enabled: boolean;
  popup_enabled: boolean;
}

// ---- Lark Bot CRUD ----

export const getLarkBots = () =>
  client.get<LarkBot[]>('/api/alert/lark-bots').then((r) => r.data);

export const createLarkBot = (data: LarkBotForm) =>
  client.post<LarkBot>('/api/alert/lark-bots', data).then((r) => r.data);

export const updateLarkBot = (id: number, data: Partial<LarkBotForm>) =>
  client.put<LarkBot>(`/api/alert/lark-bots/${id}`, data).then((r) => r.data);

export const deleteLarkBot = (id: number) =>
  client.delete(`/api/alert/lark-bots/${id}`).then((r) => r.data);

// ---- Post-Investment Monitor CRUD ----

export const getMonitors = () =>
  client.get<Monitor[]>('/api/alert/post-investment').then((r) => r.data);

export const createMonitor = (data: MonitorForm) =>
  client.post<Monitor>('/api/alert/post-investment', data).then((r) => r.data);

export const updateMonitor = (id: number, data: MonitorForm) =>
  client.put<Monitor>(`/api/alert/post-investment/${id}`, data).then((r) => r.data);

export const toggleMonitor = (id: number) =>
  client.patch<Monitor>(`/api/alert/post-investment/${id}/toggle`).then((r) => r.data);

export const deleteMonitor = (id: number) =>
  client.delete(`/api/alert/post-investment/${id}`).then((r) => r.data);

export interface CoinExchangePair {
  long_exchange: string;
  short_exchange: string;
}

export type AvailableCoins = Record<string, CoinExchangePair[]>;

export const getAvailableCoins = () =>
  client.get<AvailableCoins>('/api/alert/post-investment/available-coins').then((r) => r.data);

// ---- Basis Alert Config ----

export const getBasisConfig = () =>
  client.get<BasisConfig>('/api/alert/basis').then((r) => r.data);

export const updateBasisConfig = (data: BasisConfigForm) =>
  client.put<BasisConfig>('/api/alert/basis', data).then((r) => r.data);

export const getBasisHistory = () =>
  client.get<BasisHistoryItem[]>('/api/alert/basis/history').then((r) => r.data);

export const clearBasisData = () =>
  client.post('/api/alert/basis/clear').then((r) => r.data);

// ---- Unhedged Alert Config ----

export const getUnhedgedConfig = () =>
  client.get<UnhedgedConfig>('/api/alert/unhedged').then((r) => r.data);

export const updateUnhedgedConfig = (data: UnhedgedConfigForm) =>
  client.put<UnhedgedConfig>('/api/alert/unhedged', data).then((r) => r.data);

// ---- New Listing Alert Config ----

export interface NewListingAlertConfig {
  sound_enabled: boolean;
  popup_enabled: boolean;
  lark_bot_id: number | null;
}

export interface NewListingAlert {
  coin_name: string;
  exchange: string;
  alert_time: string;
  timestamp: number;
}

export const getNewListingAlertConfig = () =>
  client.get('/api/alert/new-listing/config').then((r) => r.data.data as NewListingAlertConfig);

export const updateNewListingAlertConfig = (data: NewListingAlertConfig) =>
  client.put('/api/alert/new-listing/config', data).then((r) => r.data);

export const getNewListingAlerts = () =>
  client.get('/api/alert/new-listing/alerts').then((r) => r.data.data as NewListingAlert[]);

// ---- Funding Break Alert Config ----

export interface FundingBreakAlertConfig {
  sound_enabled: boolean;
  popup_enabled: boolean;
  lark_bot_id: number | null;
}

export interface FundingBreakAlert {
  coin_name: string;
  exchange: string;
  realtime_funding: number;
  funding_cap: number;
  basis: number;
  alert_time: string;
  timestamp: number;
}

export const getFundingBreakAlertConfig = () =>
  client.get('/api/alert/funding-break/config').then((r) => r.data.data as FundingBreakAlertConfig);

export const updateFundingBreakAlertConfig = (data: FundingBreakAlertConfig) =>
  client.put('/api/alert/funding-break/config', data).then((r) => r.data);

export const getFundingBreakAlerts = () =>
  client.get('/api/alert/funding-break/alerts').then((r) => r.data.data as FundingBreakAlert[]);

// ---- Settings ----

export const updateNotification = (data: NotificationSettings) =>
  client.put('/api/settings/notification', data).then((r) => r.data);
