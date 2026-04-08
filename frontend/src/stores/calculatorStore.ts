import { create } from 'zustand';
import type { Dayjs } from 'dayjs';

export interface CalcInitialValues {
  coin: string;
  longExchange: string;
  shortExchange: string;
  timeRange?: [Dayjs, Dayjs];
}

interface CalculatorState {
  open: boolean;
  initialValues?: CalcInitialValues;
  openCalculator: (initial?: CalcInitialValues) => void;
  closeCalculator: () => void;
}

export const useCalculatorStore = create<CalculatorState>((set) => ({
  open: false,
  initialValues: undefined,
  openCalculator: (initial) => set({ open: true, initialValues: initial }),
  closeCalculator: () => set({ open: false, initialValues: undefined }),
}));
