import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { DatePicker, message, Select, InputNumber } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { fundingApi, type RankItem, type RealtimeData } from '../../api/funding';
import RankTable from './RankTable';
import { useCalculatorStore } from '../../stores/calculatorStore';
import { useAuthStore } from '../../stores/authStore';
import s from './FundingRank.module.css';

const { RangePicker } = DatePicker;

const exchangeOptions = [
  { label: '全部', value: '' },
  { label: 'Binance (BN)', value: 'BN' },
  { label: 'OKX', value: 'OKX' },
  { label: 'Bybit (BY)', value: 'BY' },
];

const periodOptions = [
  { label: '1h', value: 1 },
  { label: '2h', value: 2 },
  { label: '4h', value: 4 },
  { label: '8h', value: 8 },
];

export default function FundingRank() {
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>([
    dayjs().subtract(1, 'day').startOf('hour'),
    dayjs().startOf('hour'),
  ]);
  const [rankings, setRankings] = useState<RankItem[]>([]);
  const [realtimeData, setRealtimeData] = useState<RealtimeData>({});
  const [priceChanges, setPriceChanges] = useState<Record<string, { change_1d?: number; change_3d?: number }>>({});
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState('');

  // Filters
  const [longExchange, setLongExchange] = useState('');
  const [shortExchange, setShortExchange] = useState('');
  const [longPeriods, setLongPeriods] = useState<number[]>([]);
  const [shortPeriods, setShortPeriods] = useState<number[]>([]);
  const [minSpread, setMinSpread] = useState<number | null>(null);
  const [maxSpread, setMaxSpread] = useState<number | null>(null);
  const [minBasis, setMinBasis] = useState<number | null>(null);
  const [maxBasis, setMaxBasis] = useState<number | null>(null);
  const [watchFilter, setWatchFilter] = useState<string>('');      // '' | 'yes' | 'no'
  const [watchlist, setWatchlist] = useState<Set<string>>(new Set());
  const [bnSpotFilter, setBnSpotFilter] = useState<string>('');  // '' | 'yes' | 'no'
  const [trendFilter, setTrendFilter] = useState<string[]>([]);   // ['daily','h4','h1','m15']
  const [minLsr, setMinLsr] = useState<number | null>(null);
  const [maxLsr, setMaxLsr] = useState<number | null>(null);
  const [coinFilter, setCoinFilter] = useState<string>('');
  const [coinOptions, setCoinOptions] = useState<{ label: string; value: string }[]>([]);
  const [indexOverlap, setIndexOverlap] = useState<Record<string, number>>({});
  const [bnIndexWeights, setBnIndexWeights] = useState<Record<string, { alpha?: number; future?: number }>>({});
  const [bnSpotCoins, setBnSpotCoins] = useState<Set<string>>(new Set());
  const [oiLsr, setOiLsr] = useState<Record<string, { oi?: number; lsr?: number }>>({});
  const [priceTrend, setPriceTrend] = useState<Record<string, { daily: boolean; h4: boolean; h1: boolean; m15: boolean }>>({});

  useEffect(() => {
    fundingApi.getCoins().then((list) => {
      setCoinOptions(list.map((c) => ({ label: c, value: c })));
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const fetchOverlap = () => {
      fundingApi.getIndexOverlap().then(setIndexOverlap).catch(() => {});
    };
    fetchOverlap();
    const timer = setInterval(fetchOverlap, 60000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const fetchBnWeights = () => {
      fundingApi.getBnIndexWeights().then(setBnIndexWeights).catch(() => {});
    };
    fetchBnWeights();
    const timer = setInterval(fetchBnWeights, 300000); // 5min
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    fundingApi.getBnSpot().then((list) => setBnSpotCoins(new Set(list))).catch(() => {});
  }, []);

  // Watchlist — reload when auth changes
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);
  const refreshWatchlist = useCallback(() => {
    fundingApi.getWatchlist().then((list) => setWatchlist(new Set(list))).catch(() => {});
  }, []);
  useEffect(() => { refreshWatchlist(); }, [isLoggedIn, refreshWatchlist]);

  const toggleWatch = useCallback(async (coin: string, longEx: string, shortEx: string) => {
    const key = `${coin}_${longEx}_${shortEx}`;
    try {
      if (watchlist.has(key)) {
        await fundingApi.removeWatch(coin, longEx, shortEx);
      } else {
        await fundingApi.addWatch(coin, longEx, shortEx);
      }
      refreshWatchlist();
    } catch {
      // silent — user not logged in
    }
  }, [watchlist, refreshWatchlist]);

  // Poll price trend every 5 minutes
  useEffect(() => {
    const fetch = () => { fundingApi.getPriceTrend().then(setPriceTrend).catch(() => {}); };
    fetch();
    const timer = setInterval(fetch, 300000);
    return () => clearInterval(timer);
  }, []);

  // Poll OI/LSR every 5 minutes
  useEffect(() => {
    const fetchOiLsr = () => {
      fundingApi.getOiLsr().then(setOiLsr).catch(() => {});
    };
    fetchOiLsr();
    const timer = setInterval(fetchOiLsr, 300000);
    return () => clearInterval(timer);
  }, []);

  const openCalculator = useCalculatorStore((s) => s.openCalculator);

  const realtimeRef = useRef<RealtimeData>({});

  const fetchRankings = useCallback(async () => {
    setLoading(true);
    try {
      const start = dateRange[0].valueOf();
      const end = dateRange[1].valueOf();
      const res = await fundingApi.getRankings(start, end);
      setRankings(res.data);
      setLastUpdate(new Date().toLocaleString());
    } catch (err: any) {
      message.error('获取排行数据失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'));
    } finally {
      setLoading(false);
    }
  }, [dateRange]);

  const fetchRealtime = useCallback(async () => {
    try {
      const data = await fundingApi.getRealtime();
      realtimeRef.current = data;
      setRealtimeData(data);
    } catch {
      // Silent fail for polling
    }
  }, []);

  useEffect(() => {
    fetchRankings();
    const timer = setInterval(fetchRankings, 60000);
    return () => clearInterval(timer);
  }, [fetchRankings]);

  // Poll realtime every 5 seconds
  useEffect(() => {
    fetchRealtime();
    const timer = setInterval(fetchRealtime, 5000);
    return () => clearInterval(timer);
  }, [fetchRealtime]);

  // Poll price changes every 60 seconds
  useEffect(() => {
    const fetchPriceChanges = () => {
      fundingApi.getPriceChanges().then(setPriceChanges).catch(() => {});
    };
    fetchPriceChanges();
    const timer = setInterval(fetchPriceChanges, 60000);
    return () => clearInterval(timer);
  }, []);

  // Independent rankings for KPI card (24h, not tied to user filter)
  const [last24hData, setLast24hData] = useState<RankItem[]>([]);
  useEffect(() => {
    const fetchKpiRanges = async () => {
      const now = Date.now();
      try {
        const h24 = await fundingApi.getRankings(now - 24 * 60 * 60 * 1000, now);
        setLast24hData(h24.data);
      } catch {
        // silent
      }
    };
    fetchKpiRanges();
    const timer = setInterval(fetchKpiRanges, 60000);
    return () => clearInterval(timer);
  }, []);

  // Merge realtime data into rankings and apply filters
  const filteredData = rankings
    .map((item) => {
      const key = `${item.coin}_${item.long_exchange}_${item.short_exchange}`;
      const rt = realtimeData[key];
      const pc = priceChanges[item.coin];
      const overlapKey = `${item.coin}_${item.long_exchange}_${item.short_exchange}`;
      return {
        ...item,
        current_spread: rt?.spread ?? item.current_spread,
        current_basis: rt?.basis ?? item.current_basis,
        change_1d: pc?.change_1d,
        change_3d: pc?.change_3d,
        index_overlap: indexOverlap[overlapKey],
        bn_alpha: bnIndexWeights[item.coin]?.alpha,
        bn_future: bnIndexWeights[item.coin]?.future,
        watched: watchlist.has(`${item.coin}_${item.long_exchange}_${item.short_exchange}`),
        bn_spot: bnSpotCoins.has(item.coin),
        oi: oiLsr[item.coin]?.oi,
        lsr: oiLsr[item.coin]?.lsr,
        trend_daily: priceTrend[item.coin]?.daily,
        trend_h4: priceTrend[item.coin]?.h4,
        trend_h1: priceTrend[item.coin]?.h1,
        trend_m15: priceTrend[item.coin]?.m15,
      };
    })
    .filter((item) => {
      if (coinFilter && item.coin !== coinFilter) return false;
      if (longExchange && item.long_exchange !== longExchange) return false;
      if (shortExchange && item.short_exchange !== shortExchange) return false;
      if (longPeriods.length > 0 && !longPeriods.includes(item.long_settlement_period)) return false;
      if (shortPeriods.length > 0 && !shortPeriods.includes(item.short_settlement_period)) return false;
      if (minSpread !== null && (item.current_spread ?? 0) < minSpread) return false;
      if (maxSpread !== null && (item.current_spread ?? 0) > maxSpread) return false;
      if (minBasis !== null && (item.current_basis ?? 0) < minBasis) return false;
      if (maxBasis !== null && (item.current_basis ?? 0) > maxBasis) return false;
      if (watchFilter === 'yes' && !item.watched) return false;
      if (watchFilter === 'no' && item.watched) return false;
      if (bnSpotFilter === 'yes' && !item.bn_spot) return false;
      if (bnSpotFilter === 'no' && item.bn_spot) return false;
      if (trendFilter.length > 0) {
        for (const t of trendFilter) {
          if (t === 'daily' && !item.trend_daily) return false;
          if (t === 'h4' && !item.trend_h4) return false;
          if (t === 'h1' && !item.trend_h1) return false;
          if (t === 'm15' && !item.trend_m15) return false;
        }
      }
      if (minLsr !== null && (item.lsr ?? 999) < minLsr) return false;
      if (maxLsr !== null && (item.lsr ?? 0) > maxLsr) return false;
      return true;
    });

  const handleDiffClick = (record: RankItem) => {
    openCalculator({
      coin: record.coin,
      longExchange: record.long_exchange,
      shortExchange: record.short_exchange,
      timeRange: [dateRange[0], dateRange[1]],
    });
  };

  const handleDateChange = (dates: [Dayjs | null, Dayjs | null] | null) => {
    if (dates && dates[0] && dates[1]) {
      setDateRange([dates[0], dates[1]]);
    }
  };

  // KPI metrics
  const kpi = useMemo(() => {
    // Card 1: 最负基差 (realtime, across all rankings merged with latest basis)
    let mostNegBasis: { coin: string; value: number } | null = null;
    for (const item of rankings) {
      const key = `${item.coin}_${item.long_exchange}_${item.short_exchange}`;
      const rt = realtimeData[key];
      const basis = rt?.basis ?? item.current_basis;
      if (basis === undefined || basis === null) continue;
      if (!mostNegBasis || basis < mostNegBasis.value) {
        mostNegBasis = { coin: item.coin, value: basis };
      }
    }

    // Card 2: 1D 最大涨幅 (从排行榜币种中选)
    let maxChange1d: { coin: string; value: number } | null = null;
    const seenCoins = new Set<string>();
    for (const item of rankings) {
      if (seenCoins.has(item.coin)) continue;
      seenCoins.add(item.coin);
      const v = priceChanges[item.coin]?.change_1d;
      if (v === undefined || v === null) continue;
      if (!maxChange1d || v > maxChange1d.value) {
        maxChange1d = { coin: item.coin, value: v };
      }
    }

    // Card 3: 24H 最大资费差 (做空 BN)
    let last24hBest: { coin: string; value: number; longEx: string } | null = null;
    for (const item of last24hData) {
      if (item.short_exchange !== 'BN') continue;
      const v = item.total_diff ?? 0;
      if (!last24hBest || v > last24hBest.value) {
        last24hBest = { coin: item.coin, value: v, longEx: item.long_exchange };
      }
    }

    return { mostNegBasis, maxChange1d, last24hBest };
  }, [rankings, realtimeData, priceChanges, last24hData]);

  return (
    <div className={s.page}>
      {/* Floating top actions (aligns with Tabs bar) */}
      {lastUpdate && (
        <div className={s.topActions}>
          <span className={s.updateLabel}>更新 {lastUpdate}</span>
        </div>
      )}

      {/* ===== KPI Strip ===== */}
      <div className={s.kpiStrip}>
        {/* Card 1: 最负基差 */}
        <div className={s.kpi}>
          <div className={s.kpiLabel}>最负基差</div>
          {kpi.mostNegBasis ? (
            <>
              <div className={s.kpiCoin}>
                <span className={s.kpiCoinName}>{kpi.mostNegBasis.coin}</span>
              </div>
              <div className={`${s.kpiValue} ${s.kpiValueDown}`}>
                {kpi.mostNegBasis.value.toFixed(4)}%
              </div>
              <div className={s.kpiMeta}>实时基差</div>
            </>
          ) : (
            <div className={s.kpiEmpty}>暂无数据</div>
          )}
        </div>

        {/* Card 2: 1D 最大涨幅 */}
        <div className={s.kpi}>
          <div className={s.kpiLabel}>1D 最大涨幅</div>
          {kpi.maxChange1d ? (
            <>
              <div className={s.kpiCoin}>
                <span className={s.kpiCoinName}>{kpi.maxChange1d.coin}</span>
              </div>
              <div className={`${s.kpiValue} ${kpi.maxChange1d.value >= 0 ? s.kpiValueUp : s.kpiValueDown}`}>
                {kpi.maxChange1d.value >= 0 ? '+' : ''}{kpi.maxChange1d.value.toFixed(2)}%
              </div>
              <div className={s.kpiMeta}>24 小时涨幅</div>
            </>
          ) : (
            <div className={s.kpiEmpty}>暂无数据</div>
          )}
        </div>

        {/* Card 3: 24H 最大资费差 (空 BN) */}
        <div className={s.kpi}>
          <div className={s.kpiLabel}>24H 最大资费差</div>
          {kpi.last24hBest ? (
            <>
              <div className={s.kpiCoin}>
                <span className={s.kpiCoinName}>{kpi.last24hBest.coin}</span>
              </div>
              <div className={`${s.kpiValue} ${kpi.last24hBest.value >= 0 ? s.kpiValueUp : s.kpiValueDown}`}>
                {kpi.last24hBest.value >= 0 ? '+' : ''}{kpi.last24hBest.value.toFixed(4)}%
              </div>
              <div className={s.kpiMeta}>
                <span className={`${s.kpiSide} ${s.kpiSideUp}`}>
                  <span className={s.kpiSideArrow}>▲</span>多 {kpi.last24hBest.longEx}
                </span>
                <span className={`${s.kpiSide} ${s.kpiSideDown}`}>
                  <span className={s.kpiSideArrow}>▼</span>空 BN
                </span>
              </div>
            </>
          ) : (
            <div className={s.kpiEmpty}>暂无数据</div>
          )}
        </div>
      </div>

      {/* ===== Filter Bar ===== */}
      <div className={s.filterBar}>
        <div className={s.filterGroup}>
          <span className={s.filterLabel}>时间</span>
          <RangePicker
            showTime={{ format: 'HH:00' }}
            format="YYYY-MM-DD HH:00"
            value={dateRange}
            onChange={handleDateChange}
            presets={[
              { label: '1H', value: [dayjs().subtract(1, 'hour'), dayjs()] },
              { label: '4H', value: [dayjs().subtract(4, 'hour'), dayjs()] },
              { label: '8H', value: [dayjs().subtract(8, 'hour'), dayjs()] },
              { label: '24H', value: [dayjs().subtract(1, 'day'), dayjs()] },
              { label: '3D', value: [dayjs().subtract(3, 'day'), dayjs()] },
              { label: '7D', value: [dayjs().subtract(7, 'day'), dayjs()] },
              { label: '30D', value: [dayjs().subtract(30, 'day'), dayjs()] },
            ]}
          />
        </div>

        <div className={s.filterDivider} />

        <div className={s.filterGroup}>
          <span className={s.filterLabel}>币种</span>
          <Select
            showSearch
            allowClear
            value={coinFilter || undefined}
            onChange={(v) => setCoinFilter(v || '')}
            options={coinOptions}
            placeholder="搜索"
            style={{ width: 120 }}
            filterOption={(input, option) =>
              (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
            }
          />
        </div>

        <div className={s.filterGroup}>
          <span className={s.filterLabel}>做多</span>
          <Select value={longExchange} onChange={setLongExchange} options={exchangeOptions} style={{ width: 140 }} />
        </div>

        <div className={s.filterGroup}>
          <span className={s.filterLabel}>做空</span>
          <Select value={shortExchange} onChange={setShortExchange} options={exchangeOptions} style={{ width: 140 }} />
        </div>

        <div className={s.filterDivider} />

        <div className={s.filterGroup}>
          <span className={s.filterLabel}>多周期</span>
          <Select
            mode="multiple"
            value={longPeriods}
            onChange={setLongPeriods}
            options={periodOptions}
            placeholder="全部"
            allowClear
            style={{ minWidth: 110, maxWidth: 180 }}
          />
        </div>

        <div className={s.filterGroup}>
          <span className={s.filterLabel}>空周期</span>
          <Select
            mode="multiple"
            value={shortPeriods}
            onChange={setShortPeriods}
            options={periodOptions}
            placeholder="全部"
            allowClear
            style={{ minWidth: 110, maxWidth: 180 }}
          />
        </div>

        <div className={s.filterDivider} />

        <div className={s.filterGroup}>
          <span className={s.filterLabel}>开差</span>
          <InputNumber value={minSpread} onChange={(v) => setMinSpread(v)} placeholder="最小" style={{ width: 72 }} />
          <span style={{ color: 'var(--text-3)' }}>–</span>
          <InputNumber value={maxSpread} onChange={(v) => setMaxSpread(v)} placeholder="最大" style={{ width: 72 }} />
        </div>

        <div className={s.filterGroup}>
          <span className={s.filterLabel}>基差</span>
          <InputNumber value={minBasis} onChange={(v) => setMinBasis(v)} placeholder="最小" style={{ width: 72 }} />
          <span style={{ color: 'var(--text-3)' }}>–</span>
          <InputNumber value={maxBasis} onChange={(v) => setMaxBasis(v)} placeholder="最大" style={{ width: 72 }} />
        </div>

        <div className={s.filterDivider} />

        <div className={s.filterGroup}>
          <span className={s.filterLabel}>关注</span>
          <Select value={watchFilter || undefined} onChange={(v) => setWatchFilter(v || '')} allowClear placeholder="全部" style={{ width: 90 }}
            options={[{ label: '已关注', value: 'yes' }, { label: '未关注', value: 'no' }]} />
        </div>

        <div className={s.filterGroup}>
          <span className={s.filterLabel}>BN现货</span>
          <Select value={bnSpotFilter || undefined} onChange={(v) => setBnSpotFilter(v || '')} allowClear placeholder="全部" style={{ width: 90 }}
            options={[{ label: '有', value: 'yes' }, { label: '无', value: 'no' }]} />
        </div>

        <div className={s.filterGroup}>
          <span className={s.filterLabel}>价格趋势</span>
          <Select
            mode="multiple"
            value={trendFilter}
            onChange={setTrendFilter}
            allowClear
            placeholder="全部"
            style={{ minWidth: 100, maxWidth: 220 }}
            options={[
              { label: '日线多头', value: 'daily' },
              { label: '4h多头', value: 'h4' },
              { label: '1h多头', value: 'h1' },
              { label: '15m多头', value: 'm15' },
            ]}
          />
        </div>

        <div className={s.filterGroup}>
          <span className={s.filterLabel}>多空比</span>
          <InputNumber value={minLsr} onChange={(v) => setMinLsr(v)} placeholder="最小" style={{ width: 72 }} />
          <span style={{ color: 'var(--text-3)' }}>–</span>
          <InputNumber value={maxLsr} onChange={(v) => setMaxLsr(v)} placeholder="最大" style={{ width: 72 }} />
        </div>

      </div>

      {/* ===== Table ===== */}
      <div className={s.tableWrap}>
        <RankTable
          data={filteredData}
          loading={loading}
          onDiffClick={handleDiffClick}
          onWatchToggle={toggleWatch}
        />
      </div>

    </div>
  );
}
