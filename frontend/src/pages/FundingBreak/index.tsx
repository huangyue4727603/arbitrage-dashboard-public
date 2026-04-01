import { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import { Card, Table, Tag, Space, Select, Row, Col, Progress, Button } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { useWsStore } from '../../stores/wsStore';
import { fundingBreakApi } from '../../api/fundingBreak';
import type { FundingBreakItem } from '../../api/fundingBreak';

function formatCountdown(seconds: number): string {
  if (seconds <= 0) return '00:00:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [h, m, s].map((v) => String(v).padStart(2, '0')).join(':');
}

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

/** Calculate breaking progress: realtime_funding / cap or floor */
function calcProgress(rate: number, cap: number, floor: number): number {
  if (rate >= 0) {
    return cap > 0 ? (rate / cap) * 100 : 0;
  }
  return floor < 0 ? (rate / floor) * 100 : 0;
}

interface DisplayItem extends FundingBreakItem {
  key: string;
  display_countdown: number;
}

export default function FundingBreak() {
  const [data, setData] = useState<DisplayItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [exchange, setExchange] = useState('');
  const [interval, setInterval_] = useState('');
  const [breakingFilter, setBreakingFilter] = useState('');
  const [updateTime, setUpdateTime] = useState('');
  const countdownRef = useRef<ReturnType<typeof setInterval>>(undefined);
  const wsData = useWsStore((s) => s.fundingBreak);

  const transformData = useCallback((items: FundingBreakItem[]): DisplayItem[] => {
    return items.map((item, idx) => ({
      ...item,
      key: `${item.exchange}-${item.coin_name}-${idx}`,
      display_countdown: item.countdown_seconds,
    }));
  }, []);

  const markUpdateTime = useCallback(() => {
    setUpdateTime(dayjs().format('HH:mm:ss'));
  }, []);

  // Initial fetch
  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      try {
        const res = await fundingBreakApi.getBreakingCoins();
        if (!cancelled) {
          setData(transformData(res.data));
          markUpdateTime();
        }
      } catch {
        // ignore
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchData();
    const timer = setInterval(fetchData, 60000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [transformData, markUpdateTime]);

  // Update from WebSocket
  useEffect(() => {
    if (wsData && Array.isArray(wsData) && wsData.length > 0) {
      setData(transformData(wsData as FundingBreakItem[]));
      setLoading(false);
      markUpdateTime();
    }
  }, [wsData, transformData, markUpdateTime]);

  // Countdown ticker
  useEffect(() => {
    countdownRef.current = setInterval(() => {
      setData((prev) =>
        prev.map((item) => ({
          ...item,
          display_countdown: Math.max(0, item.display_countdown - 1),
        }))
      );
    }, 1000);
    return () => { if (countdownRef.current) clearInterval(countdownRef.current); };
  }, []);

  const filteredData = useMemo(() => {
    let list = data;
    if (exchange) list = list.filter((item) => item.exchange === exchange);
    if (interval) list = list.filter((item) => item.current_interval === interval);
    if (breakingFilter === 'yes') list = list.filter((item) => item.is_breaking);
    if (breakingFilter === 'no') list = list.filter((item) => !item.is_breaking);
    return list;
  }, [data, exchange, interval, breakingFilter]);

  const breakingCount = useMemo(() => data.filter((item) => item.is_breaking).length, [data]);

  const columns: ColumnsType<DisplayItem> = [
    {
      title: '代币名称',
      dataIndex: 'coin_name',
      key: 'coin_name',
      width: 100,
      fixed: 'left',
      render: (name: string) => (
        <a
          href={`https://www.coinglass.com/tv/zh/Binance_${name}USDT`}
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontWeight: 600 }}
        >
          {name}
        </a>
      ),
    },
    {
      title: '交易所',
      dataIndex: 'exchange',
      key: 'exchange',
      width: 90,
      render: (ex: string) => {
        const colorMap: Record<string, string> = { Binance: 'gold', OKX: 'blue', Bybit: 'green' };
        return <Tag color={colorMap[ex] || 'default'}>{ex}</Tag>;
      },
    },
    {
      title: '状态',
      dataIndex: 'is_breaking',
      key: 'is_breaking',
      width: 80,
      align: 'center',
      render: (breaking: boolean) =>
        breaking ? <Tag color="red">已突破</Tag> : <Tag>未突破</Tag>,
    },
    {
      title: '资费上限/下限',
      key: 'funding_cap',
      width: 140,
      render: (_, record) => (
        <span>
          {record.funding_cap > 0 ? '+' : ''}{record.funding_cap.toFixed(4)}% / {record.funding_floor.toFixed(4)}%
        </span>
      ),
    },
    {
      title: '实时资费',
      dataIndex: 'realtime_funding',
      key: 'realtime_funding',
      width: 110,
      sorter: (a, b) => a.realtime_funding - b.realtime_funding,
      render: (rate: number, record: DisplayItem) => {
        const isBreaking = rate >= record.funding_cap || rate <= record.funding_floor;
        return (
          <span style={{ color: isBreaking ? '#F23645' : rate > 0 ? '#22AB94' : rate < 0 ? '#F23645' : undefined, fontWeight: isBreaking ? 700 : 400 }}>
            {rate > 0 ? '+' : ''}{rate.toFixed(4)}%
          </span>
        );
      },
    },
    {
      title: '突破进度',
      key: 'progress',
      width: 160,
      defaultSortOrder: 'descend',
      sorter: (a, b) =>
        calcProgress(a.realtime_funding, a.funding_cap, a.funding_floor) -
        calcProgress(b.realtime_funding, b.funding_cap, b.funding_floor),
      render: (_, record) => {
        const progress = calcProgress(record.realtime_funding, record.funding_cap, record.funding_floor);
        const displayPct = Math.min(progress, 100);
        const color = progress >= 100 ? '#F23645' : progress >= 80 ? '#faad14' : '#22AB94';
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Progress
              percent={displayPct}
              showInfo={false}
              size="small"
              strokeColor={color}
              trailColor="#f0f0f0"
              style={{ flex: 1, minWidth: 60 }}
            />
            <span style={{ color, fontWeight: progress >= 100 ? 700 : 400, fontSize: 12, whiteSpace: 'nowrap' }}>
              {progress.toFixed(2)}%
            </span>
          </div>
        );
      },
    },
    {
      title: '基差',
      dataIndex: 'basis',
      key: 'basis',
      width: 90,
      sorter: (a, b) => a.basis - b.basis,
      render: (val: number) => (
        <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>
          {val > 0 ? '+' : ''}{val.toFixed(4)}%
        </span>
      ),
    },
    {
      title: '结算周期',
      dataIndex: 'current_interval',
      key: 'current_interval',
      width: 80,
      align: 'center',
      render: (val: string) => {
        const colorMap: Record<string, string> = { '8h': 'green', '4h': 'cyan', '2h': 'purple' };
        return <Tag color={colorMap[val] || 'default'}>{val}</Tag>;
      },
    },
    {
      title: '倒计时',
      dataIndex: 'display_countdown',
      key: 'countdown',
      width: 100,
      sorter: (a, b) => a.display_countdown - b.display_countdown,
      render: (seconds: number) => {
        const isUrgent = seconds < 600;
        return (
          <span style={{ color: isUrgent ? '#F23645' : undefined, fontWeight: isUrgent ? 700 : 400, fontFamily: 'monospace' }}>
            {formatCountdown(seconds)}
          </span>
        );
      },
    },
  ];

  return (
    <Card
      title="资费突破"
      extra={
        <Space size={16}>
          {updateTime && <span style={{ color: '#999', fontSize: 12 }}>更新时间：{updateTime}</span>}
          <span style={{ color: '#999', fontSize: 12 }}>共 {data.length} 个币种，{breakingCount} 个突破</span>
          <Button icon={<ReloadOutlined />} onClick={async () => { const res = await fundingBreakApi.getBreakingCoins(); setData(transformData(res.data)); markUpdateTime(); }} loading={loading}>刷新</Button>
        </Space>
      }
    >
      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col>
          <Space size={4}>
            <span>交易所：</span>
            <Select value={exchange} onChange={setExchange} options={exchangeOptions} style={{ width: 100 }} />
          </Space>
        </Col>
        <Col>
          <Space size={4}>
            <span>结算周期：</span>
            <Select value={interval} onChange={setInterval_} options={intervalOptions} style={{ width: 80 }} />
          </Space>
        </Col>
        <Col>
          <Space size={4}>
            <span>状态：</span>
            <Select value={breakingFilter} onChange={setBreakingFilter} options={breakingOptions} style={{ width: 90 }} />
          </Space>
        </Col>
      </Row>
      <Table<DisplayItem>
        columns={columns}
        dataSource={filteredData}
        loading={loading}
        rowKey="key"
        pagination={{ pageSize: 100, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
        size="small"
        scroll={{ x: 1060 }}
      />
    </Card>
  );
}
