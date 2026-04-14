import { useEffect, useState, useMemo, useRef } from 'react';
import { Drawer, Select, Progress, Button, theme as antTheme } from 'antd';
import { FilterOutlined } from '@ant-design/icons';
import { fundingBreakApi, type FundingBreakItem } from '../../api/fundingBreak';
import { useWsStore } from '../../stores/wsStore';

const exchangeOptions = [
  { label: '全部', value: '' },
  { label: 'Binance', value: 'Binance' },
  { label: 'OKX', value: 'OKX' },
  { label: 'Bybit', value: 'Bybit' },
];
const intervalOptions = [
  { label: '全部', value: '' },
  { label: '2h', value: '2h' },
  { label: '4h', value: '4h' },
  { label: '8h', value: '8h' },
];
const breakingOptions = [
  { label: '全部', value: '' },
  { label: '已突破', value: 'yes' },
  { label: '未突破', value: 'no' },
];

function fmt(seconds: number) {
  if (seconds <= 0) return '00:00:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [h, m, s].map((v) => String(v).padStart(2, '0')).join(':');
}

function calcProgress(rate: number, cap: number, floor: number) {
  if (rate >= 0) return cap > 0 ? (rate / cap) * 100 : 0;
  return floor < 0 ? (rate / floor) * 100 : 0;
}

interface DisplayItem extends FundingBreakItem {
  display_countdown: number;
}

export default function MobileFundingBreak() {
  const { token } = antTheme.useToken();
  const [data, setData] = useState<DisplayItem[]>([]);
  const [exchange, setExchange] = useState('');
  const [interval, setInterval_] = useState('');
  const [breakingFilter, setBreakingFilter] = useState('');
  const [filterOpen, setFilterOpen] = useState(false);
  const wsData = useWsStore((s) => s.fundingBreak);
  const tickRef = useRef<ReturnType<typeof setInterval>>(undefined);

  const transform = (items: FundingBreakItem[]): DisplayItem[] =>
    items.map((it) => ({ ...it, display_countdown: it.countdown_seconds }));

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      try {
        const res = await fundingBreakApi.getBreakingCoins();
        if (!cancelled) setData(transform(res.data));
      } catch { /* ignore */ }
    };
    fetchData();
    const t = setInterval(fetchData, 60000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  useEffect(() => {
    if (wsData && Array.isArray(wsData) && wsData.length > 0) {
      setData(transform(wsData as FundingBreakItem[]));
    }
  }, [wsData]);

  useEffect(() => {
    tickRef.current = setInterval(() => {
      setData((prev) => prev.map((it) => ({ ...it, display_countdown: Math.max(0, it.display_countdown - 1) })));
    }, 1000);
    return () => { if (tickRef.current) clearInterval(tickRef.current); };
  }, []);

  const filtered = useMemo(() => {
    let list = data;
    if (exchange) list = list.filter((it) => it.exchange === exchange);
    if (interval) list = list.filter((it) => it.current_interval === interval);
    if (breakingFilter === 'yes') list = list.filter((it) => it.is_breaking);
    if (breakingFilter === 'no') list = list.filter((it) => !it.is_breaking);
    return list.sort((a, b) =>
      calcProgress(b.realtime_funding, b.funding_cap, b.funding_floor) -
      calcProgress(a.realtime_funding, a.funding_cap, a.funding_floor)
    );
  }, [data, exchange, interval, breakingFilter]);

  const breakingCount = data.filter((it) => it.is_breaking).length;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 12, color: token.colorTextTertiary }}>
          已突破 <span style={{ color: token.colorError, fontWeight: 600 }}>{breakingCount}</span> / 共 {data.length}
        </span>
        <Button size="small" icon={<FilterOutlined />} onClick={() => setFilterOpen(true)}>筛选</Button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {filtered.map((it, idx) => {
          const progress = calcProgress(it.realtime_funding, it.funding_cap, it.funding_floor);
          const displayPct = Math.min(progress, 100);
          const color = progress >= 100 ? token.colorError : progress >= 80 ? token.colorWarning : token.colorSuccess;
          const isUrgent = it.display_countdown < 600;
          return (
            <div
              key={`${it.exchange}-${it.coin_name}-${idx}`}
              style={{
                background: token.colorBgContainer,
                border: `1px solid ${token.colorBorderSecondary}`,
                borderRadius: 10,
                padding: 12,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
                <div>
                  <span style={{ fontSize: 16, fontWeight: 700, color: token.colorText }}>{it.coin_name}</span>
                  <span style={{ marginLeft: 8, fontSize: 11, color: token.colorTextSecondary }}>
                    {it.exchange} · {it.current_interval}
                  </span>
                </div>
                {it.is_breaking ? (
                  <span style={{ fontSize: 11, color: token.colorError, fontWeight: 600 }}>已突破</span>
                ) : (
                  <span style={{ fontSize: 11, color: token.colorTextTertiary }}>未突破</span>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <Progress
                  percent={displayPct}
                  showInfo={false}
                  size="small"
                  strokeColor={color}
                  style={{ flex: 1 }}
                />
                <span style={{ fontSize: 12, fontWeight: 600, color, minWidth: 48, textAlign: 'right' }}>
                  {progress.toFixed(1)}%
                </span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', fontSize: 12, gap: 4 }}>
                <span style={{ color: token.colorTextTertiary }}>实时 <span style={{ color: it.realtime_funding > 0 ? token.colorSuccess : token.colorError, fontWeight: 600 }}>{it.realtime_funding > 0 ? '+' : ''}{it.realtime_funding.toFixed(4)}%</span></span>
                <span style={{ color: token.colorTextTertiary, textAlign: 'right' }}>上限 {it.funding_cap > 0 ? '+' : ''}{it.funding_cap.toFixed(4)}%</span>
                <span style={{ color: token.colorTextTertiary }}>基差 <span style={{ color: it.basis >= 0 ? token.colorSuccess : token.colorError }}>{it.basis > 0 ? '+' : ''}{it.basis.toFixed(4)}%</span></span>
                <span style={{ color: isUrgent ? token.colorError : token.colorTextTertiary, textAlign: 'right', fontFamily: 'monospace', fontWeight: isUrgent ? 700 : 400 }}>⏱ {fmt(it.display_countdown)}</span>
              </div>
            </div>
          );
        })}
        {filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: token.colorTextTertiary }}>暂无数据</div>
        )}
      </div>

      <Drawer open={filterOpen} onClose={() => setFilterOpen(false)} placement="bottom" height="auto" title="筛选条件">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Field label="交易所"><Select value={exchange} onChange={setExchange} options={exchangeOptions} style={{ width: '100%' }} /></Field>
          <Field label="结算周期"><Select value={interval} onChange={setInterval_} options={intervalOptions} style={{ width: '100%' }} /></Field>
          <Field label="状态"><Select value={breakingFilter} onChange={setBreakingFilter} options={breakingOptions} style={{ width: '100%' }} /></Field>
          <Button type="primary" block onClick={() => setFilterOpen(false)}>确定</Button>
        </div>
      </Drawer>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  const { token } = antTheme.useToken();
  return (
    <div>
      <div style={{ fontSize: 12, color: token.colorTextSecondary, marginBottom: 6 }}>{label}</div>
      {children}
    </div>
  );
}
