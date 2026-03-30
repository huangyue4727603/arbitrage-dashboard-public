import dayjs from 'dayjs';

export function formatPercent(value: number | null | undefined, decimals = 2): string {
  if (value == null || isNaN(value)) return '-';
  return `${(value * 100).toFixed(decimals)}%`;
}

export function formatNumber(value: number | null | undefined, decimals = 2): string {
  if (value == null || isNaN(value)) return '-';
  return value.toFixed(decimals);
}

export function formatTime(timestamp: string | number | null | undefined): string {
  if (timestamp == null) return '-';
  return dayjs(timestamp).format('YYYY-MM-DD HH:mm:ss');
}
