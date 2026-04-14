import { useEffect, useState, useCallback, useMemo } from 'react';
import { Button, Drawer, Select, DatePicker, InputNumber, theme as antTheme, message } from 'antd';
import { FilterOutlined, SortAscendingOutlined } from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import { fundingApi, type RankItem, type RealtimeData } from '../../api/funding';

const { RangePicker } = DatePicker;

const exchangeOptions = [
  { label: '全部', value: '' },
  { label: 'Binance (BN)', value: 'BN' },
  { label: 'OKX', value: 'OKX' },
  { label: 'Bybit (BY)', value: 'BY' },
];

export default function MobileFundingRank() {
  const { token } = antTheme.useToken();
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>([
    dayjs().subtract(1, 'day').startOf('hour'),
    dayjs().startOf('hour'),
  ]);
  const [rankings, setRankings] = useState<RankItem[]>([]);
  const [realtime, setRealtime] = useState<RealtimeData>({});
  const [priceChanges, setPriceChanges] = useState<Record<string, { change_1d?: number }>>({});
  const [longExchange, setLongExchange] = useState('');
  const [shortExchange, setShortExchange] = useState('');
  const [minDiff, setMinDiff] = useState<number | null>(null);
  const [sortKey, setSortKey] = useState<'total_diff' | 'current_basis' | 'current_spread'>('total_diff');
  const [sortOrder, setSortOrder] = useState<'desc' | 'asc'>('desc');
  const [filterOpen, setFilterOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const fetchRankings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fundingApi.getRankings(dateRange[0].valueOf(), dateRange[1].valueOf());
      setRankings(res.data);
    } catch (err: any) {
      message.error('获取失败: ' + (err?.message || ''));
    } finally {
      setLoading(false);
    }
  }, [dateRange]);

  useEffect(() => {
    fetchRankings();
    const t = setInterval(fetchRankings, 60000);
    return () => clearInterval(t);
  }, [fetchRankings]);

  useEffect(() => {
    const fetchRT = () => fundingApi.getRealtime().then(setRealtime).catch(() => {});
    fetchRT();
    const t = setInterval(fetchRT, 5000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const fetchPC = () => fundingApi.getPriceChanges().then(setPriceChanges).catch(() => {});
    fetchPC();
    const t = setInterval(fetchPC, 60000);
    return () => clearInterval(t);
  }, []);

  const merged = useMemo(() => {
    return rankings
      .map((item) => {
        const key = `${item.coin}_${item.long_exchange}_${item.short_exchange}`;
        const rt = realtime[key];
        return {
          ...item,
          current_basis: rt?.basis ?? item.current_basis,
          current_spread: rt?.spread ?? item.current_spread,
          change_1d: priceChanges[item.coin]?.change_1d,
        };
      })
      .filter((it) => {
        if (longExchange && it.long_exchange !== longExchange) return false;
        if (shortExchange && it.short_exchange !== shortExchange) return false;
        if (minDiff !== null && (it.total_diff ?? 0) < minDiff) return false;
        return true;
      })
      .sort((a, b) => {
        const av = (a[sortKey] ?? 0) as number;
        const bv = (b[sortKey] ?? 0) as number;
        return sortOrder === 'desc' ? bv - av : av - bv;
      });
  }, [rankings, realtime, priceChanges, longExchange, shortExchange, minDiff, sortKey, sortOrder]);

  const kpi = useMemo(() => {
    let mostNegBasis: { coin: string; value: number } | null = null;
    for (const it of merged) {
      const v = it.current_basis;
      if (v === undefined || v === null) continue;
      if (!mostNegBasis || v < mostNegBasis.value) mostNegBasis = { coin: it.coin, value: v };
    }
    let maxChange1d: { coin: string; value: number } | null = null;
    const seen = new Set<string>();
    for (const it of merged) {
      if (seen.has(it.coin)) continue;
      seen.add(it.coin);
      const v = it.change_1d;
      if (v === undefined || v === null) continue;
      if (!maxChange1d || v > maxChange1d.value) maxChange1d = { coin: it.coin, value: v };
    }
    return { mostNegBasis, maxChange1d };
  }, [merged]);

  const renderColored = (val: number | null | undefined, decimals = 3, suffix = '%') => {
    if (val === null || val === undefined) return <span style={{ color: token.colorTextTertiary }}>—</span>;
    const color = val > 0 ? token.colorSuccess : val < 0 ? token.colorError : token.colorText;
    return <span style={{ color, fontWeight: 600 }}>{val >= 0 ? '+' : ''}{val.toFixed(decimals)}{suffix}</span>;
  };

  return (
    <div>
      {/* KPI */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        <KpiCard label="最负基差" coin={kpi.mostNegBasis?.coin} value={kpi.mostNegBasis?.value} negative />
        <KpiCard label="1D 最大涨幅" coin={kpi.maxChange1d?.coin} value={kpi.maxChange1d?.value} decimals={2} />
      </div>

      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, gap: 8 }}>
        <span style={{ fontSize: 12, color: token.colorTextTertiary, flexShrink: 0 }}>共 {merged.length} 条{loading && ' ·加载中'}</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <Select
            size="small"
            value={sortKey}
            onChange={setSortKey}
            options={[
              { label: '资费差', value: 'total_diff' },
              { label: '基差', value: 'current_basis' },
              { label: '价差', value: 'current_spread' },
            ]}
            style={{ width: 90 }}
            suffixIcon={<SortAscendingOutlined />}
          />
          <Button
            size="small"
            onClick={() => setSortOrder(sortOrder === 'desc' ? 'asc' : 'desc')}
            style={{ minWidth: 36 }}
          >
            {sortOrder === 'desc' ? '↓' : '↑'}
          </Button>
          <Button size="small" icon={<FilterOutlined />} onClick={() => setFilterOpen(true)}>筛选</Button>
        </div>
      </div>

      {/* Card list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {merged.map((it) => (
          <div
            key={`${it.coin}_${it.long_exchange}_${it.short_exchange}`}
            style={{
              background: token.colorBgContainer,
              border: `1px solid ${token.colorBorderSecondary}`,
              borderRadius: 10,
              padding: 12,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: token.colorText }}>{it.coin}</div>
              <div style={{ fontSize: 12, color: token.colorTextSecondary }}>
                <span style={{ color: token.colorSuccess }}>▲多 {it.long_exchange}</span>
                {' / '}
                <span style={{ color: token.colorError }}>▼空 {it.short_exchange}</span>
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, fontSize: 13 }}>
              <Stat label="资费差" value={renderColored(it.total_diff)} />
              <Stat label="实时基差" value={renderColored(it.current_basis, 4)} />
              <Stat label="实时价差" value={renderColored(it.current_spread, 4)} />
              <Stat label="1D 涨幅" value={renderColored(it.change_1d, 2)} />
            </div>
          </div>
        ))}
        {merged.length === 0 && !loading && (
          <div style={{ textAlign: 'center', padding: 40, color: token.colorTextTertiary }}>暂无数据</div>
        )}
      </div>

      {/* Filter Drawer */}
      <Drawer
        open={filterOpen}
        onClose={() => setFilterOpen(false)}
        placement="bottom"
        height="auto"
        title="筛选条件"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Field label="时间范围">
            <RangePicker
              showTime={{ format: 'HH:mm' }}
              format="MM-DD HH:mm"
              value={dateRange}
              onChange={(v) => v && v[0] && v[1] && setDateRange([v[0], v[1]])}
              style={{ width: '100%' }}
            />
          </Field>
          <Field label="做多">
            <Select value={longExchange} onChange={setLongExchange} options={exchangeOptions} style={{ width: '100%' }} />
          </Field>
          <Field label="做空">
            <Select value={shortExchange} onChange={setShortExchange} options={exchangeOptions} style={{ width: '100%' }} />
          </Field>
          <Field label="最小总资费差 (%)">
            <InputNumber
              value={minDiff}
              onChange={(v) => setMinDiff(v)}
              step={0.1}
              placeholder="不限"
              style={{ width: '100%' }}
            />
          </Field>
          <Button type="primary" block onClick={() => setFilterOpen(false)}>确定</Button>
        </div>
      </Drawer>
    </div>
  );
}

function KpiCard({
  label, coin, value, negative, decimals = 4,
}: { label: string; coin?: string; value?: number; negative?: boolean; decimals?: number }) {
  const { token } = antTheme.useToken();
  const color = value === undefined ? token.colorTextTertiary
    : negative ? token.colorError
    : value >= 0 ? token.colorSuccess : token.colorError;
  return (
    <div
      style={{
        background: token.colorBgContainer,
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: 10,
        padding: 12,
      }}
    >
      <div style={{ fontSize: 11, color: token.colorTextTertiary, fontWeight: 600, letterSpacing: 0.5 }}>
        {label.toUpperCase()}
      </div>
      {value !== undefined && coin ? (
        <>
          <div style={{ fontSize: 18, fontWeight: 700, marginTop: 4, color: token.colorText }}>{coin}</div>
          <div style={{ fontSize: 16, fontWeight: 700, color, marginTop: 2 }}>
            {value >= 0 ? '+' : ''}{value.toFixed(decimals)}%
          </div>
        </>
      ) : (
        <div style={{ marginTop: 12, fontSize: 13, color: token.colorTextTertiary }}>暂无</div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  const { token } = antTheme.useToken();
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
      <span style={{ color: token.colorTextTertiary, fontSize: 12 }}>{label}</span>
      <span>{value}</span>
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
