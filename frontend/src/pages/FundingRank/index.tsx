import { useState, useEffect, useCallback, useRef } from 'react';
import { Card, DatePicker, Button, Space, message, Select, InputNumber, Row, Col, Typography, Input } from 'antd';
import { CalculatorOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { fundingApi, type RankItem, type RealtimeData } from '../../api/funding';
import RankTable from './RankTable';
import Calculator, { type CalcInitialValues } from './Calculator';

const { RangePicker } = DatePicker;
const { Text } = Typography;

const exchangeOptions = [
  { label: '全部', value: '' },
  { label: 'BN', value: 'BN' },
  { label: 'OKX', value: 'OKX' },
  { label: 'BY', value: 'BY' },
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
  const [coinFilter, setCoinFilter] = useState<string>('');
  const [coinOptions, setCoinOptions] = useState<{ label: string; value: string }[]>([]);
  const [indexOverlap, setIndexOverlap] = useState<Record<string, number>>({});

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

  // Calculator modal state
  const [calcOpen, setCalcOpen] = useState(false);
  const [calcInitial, setCalcInitial] = useState<CalcInitialValues | undefined>();

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
      return true;
    });

  const handleDiffClick = (record: RankItem) => {
    setCalcInitial({
      coin: record.coin,
      longExchange: record.long_exchange,
      shortExchange: record.short_exchange,
      timeRange: [dateRange[0], dateRange[1]],
    });
    setCalcOpen(true);
  };

  const handleDateChange = (dates: [Dayjs | null, Dayjs | null] | null) => {
    if (dates && dates[0] && dates[1]) {
      setDateRange([dates[0], dates[1]]);
    }
  };

  return (
    <Card
      title={<span style={{ fontSize: 16, fontWeight: 600 }}>资费排行</span>}
      extra={
        <Space align="center">
          {lastUpdate && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              更新时间: {lastUpdate}
            </Text>
          )}
          <Button size="small" icon={<ReloadOutlined />} onClick={fetchRankings} loading={loading}>
            刷新
          </Button>
          <Button
            size="small"
            type="primary"
            icon={<CalculatorOutlined />}
            onClick={() => { setCalcInitial(undefined); setCalcOpen(true); }}
          >
            资费计算器
          </Button>
        </Space>
      }
    >
      {/* Filter row 1: Time + Exchanges */}
      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col>
          <Space size={4}>
            <span>时间：</span>
            <RangePicker
              showTime={{ format: 'HH:00' }}
              format="YYYY-MM-DD HH:00"
              value={dateRange}
              onChange={handleDateChange}
              presets={[
                { label: '最近1H', value: [dayjs().subtract(1, 'hour'), dayjs()] },
                { label: '最近4H', value: [dayjs().subtract(4, 'hour'), dayjs()] },
                { label: '最近8H', value: [dayjs().subtract(8, 'hour'), dayjs()] },
                { label: '最近12H', value: [dayjs().subtract(12, 'hour'), dayjs()] },
                { label: '最近24H', value: [dayjs().subtract(1, 'day'), dayjs()] },
                { label: '最近3天', value: [dayjs().subtract(3, 'day'), dayjs()] },
                { label: '最近7天', value: [dayjs().subtract(7, 'day'), dayjs()] },
                { label: '最近30天', value: [dayjs().subtract(30, 'day'), dayjs()] },
              ]}
            />
          </Space>
        </Col>
        <Col>
          <Space size={4}>
            <span>做多交易所：</span>
            <Select
              value={longExchange}
              onChange={setLongExchange}
              options={exchangeOptions}
              style={{ width: 90 }}
            />
          </Space>
        </Col>
        <Col>
          <Space size={4}>
            <span>做空交易所：</span>
            <Select
              value={shortExchange}
              onChange={setShortExchange}
              options={exchangeOptions}
              style={{ width: 90 }}
            />
          </Space>
        </Col>
        <Col>
          <Button type="primary" icon={<SearchOutlined />} onClick={fetchRankings} loading={loading}>
            查询
          </Button>
        </Col>
      </Row>

      {/* Filter row 2: Period + Spread + Basis + Coin */}
      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col>
          <Space size={4}>
            <span>币种：</span>
            <Select
              showSearch
              allowClear
              value={coinFilter || undefined}
              onChange={(v) => setCoinFilter(v || '')}
              options={coinOptions}
              placeholder="搜索币种"
              style={{ width: 130 }}
              filterOption={(input, option) =>
                (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
              }
            />
          </Space>
        </Col>
        <Col>
          <Space size={4}>
            <span>做多结算周期：</span>
            <Select
              mode="multiple"
              value={longPeriods}
              onChange={setLongPeriods}
              options={periodOptions}
              placeholder="全部"
              allowClear
              style={{ minWidth: 100 }}
            />
          </Space>
        </Col>
        <Col>
          <Space size={4}>
            <span>做空结算周期：</span>
            <Select
              mode="multiple"
              value={shortPeriods}
              onChange={setShortPeriods}
              options={periodOptions}
              placeholder="全部"
              allowClear
              style={{ minWidth: 100 }}
            />
          </Space>
        </Col>
        <Col>
          <Space size={4}>
            <span>开差：</span>
            <InputNumber
              value={minSpread}
              onChange={(v) => setMinSpread(v)}
              placeholder="最小"
              style={{ width: 80 }}
              size="small"
            />
            <span>~</span>
            <InputNumber
              value={maxSpread}
              onChange={(v) => setMaxSpread(v)}
              placeholder="最大"
              style={{ width: 80 }}
              size="small"
            />
            <span>%</span>
          </Space>
        </Col>
        <Col>
          <Space size={4}>
            <span>基差：</span>
            <InputNumber
              value={minBasis}
              onChange={(v) => setMinBasis(v)}
              placeholder="最小"
              style={{ width: 80 }}
              size="small"
            />
            <span>~</span>
            <InputNumber
              value={maxBasis}
              onChange={(v) => setMaxBasis(v)}
              placeholder="最大"
              style={{ width: 80 }}
              size="small"
            />
            <span>%</span>
          </Space>
        </Col>
      </Row>

      <RankTable
        data={filteredData}
        loading={loading}
        onDiffClick={handleDiffClick}
      />

      <Calculator
        open={calcOpen}
        onClose={() => { setCalcOpen(false); setCalcInitial(undefined); }}
        initialValues={calcInitial}
      />
    </Card>
  );
}
