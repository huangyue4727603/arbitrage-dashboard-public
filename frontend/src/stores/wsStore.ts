import { create } from 'zustand';

export type WsChannel =
  | 'basisMonitor'
  | 'unhedged'
  | 'fundingBreak'
  | 'spreadUpdate'
  | 'newListing'
  | 'priceTrend'
  | 'fundingRank';

interface WsDataState {
  basisMonitor: unknown[];
  unhedged: unknown[];
  fundingBreak: unknown[];
  spreadUpdate: unknown[];
  newListing: unknown[];
  priceTrend: unknown[];
  fundingRank: unknown[];
  setData: (channel: WsChannel, data: unknown[]) => void;
}

export const useWsStore = create<WsDataState>((set) => ({
  basisMonitor: [],
  unhedged: [],
  fundingBreak: [],
  spreadUpdate: [],
  newListing: [],
  priceTrend: [],
  fundingRank: [],

  setData: (channel, data) =>
    set(() => ({ [channel]: data })),
}));
