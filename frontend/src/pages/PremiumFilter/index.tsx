import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Button, Space, Select, InputNumber, message, Row, Col } from 'antd';
import { SearchOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { fetchPremiumFilter, fetchRealtimeBasis, type PremiumFilterItem } from '../../api/premiumFilter';
import { fundingApi } from '../../api/funding';
import Calculator, { type CalcInitialValues } from '../FundingRank/Calculator';

const timeOptions = [
  { label: '过去1小时', value: 1 },
  { label: '过去4小时', value: 4 },
  { label: '过去12小时', value: 12 },
  { label: '过去1天', value: 24 },
  { label: '过去3天', value: 72 },
];

const renderPercent = (val: number | null | undefined, decimals = 3) => {
  if (val === null || val === undefined) return <span style={{ color: '#d9d9d9' }}>—</span>;
  const color = val > 0 ? '#22AB94' : val < 0 ? '#F23645' : undefined;
  return <span style={{ color }}>{val >= 0 ? '+' : ''}{val.toFixed(decimals)}%</span>;
};

interface DisplayItem extends PremiumFilterItem {
  change_1d?: number;
}

export default function PremiumFilter() {
  const [data, setData] = useState<DisplayItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [hours, setHours] = useState(24);
  const [threshold, setThreshold] = useState(-2);
  const [lastUpdate, setLastUpdate] = useState('');
  const [basisData, setBasisData] = useState<Record<string, number>>({});
  const [priceChanges, setPriceChanges] = useState<Record<string, { change_1d?: number }>>({});

  // Calculator
  const [calcOpen, setCalcOpen] = useState(false);
  const [calcInitial, setCalcInitial] = useState<CalcInitialValues | undefined>();

  const handleQuery = useCallback(async () => {
    const ts = Date.now() - hours * 3600 * 1000;
    setLoading(true);
    try {
      const result = await fetchPremiumFilter(ts, threshold / 100);
      setData(result);
      setLastUpdate(new Date().toLocaleString());
    } catch {
      message.error('查询失败');
    } finally {
      setLoading(false);
    }
  }, [hours, threshold]);

  // 页面加载时自动查询 + 1分钟定时刷新
  useEffect(() => {
    handleQuery();
    const timer = setInterval(handleQuery, 60000);
    return () => clearInterval(timer);
  }, [handleQuery]);

  // 轮询实时基差（5秒），仅在有数据时
  useEffect(() => {
    if (data.length === 0) return;
    const coins = data.map((d) => d.coin_name);
    const fetchBasis = async () => {
      try {
        const result = await fetchRealtimeBasis(coins);
        setBasisData(result);
      } catch {
        // silent
      }
    };
    fetchBasis();
    const timer = setInterval(fetchBasis, 10000);
    return () => clearInterval(timer);
  }, [data]);

  // 轮询涨跌幅（60秒）
  useEffect(() => {
    const fetchPrices = () => {
      fundingApi.getPriceChanges().then(setPriceChanges).catch(() => {});
    };
    fetchPrices();
    const timer = setInterval(fetchPrices, 60000);
    return () => clearInterval(timer);
  }, []);

  // 合并实时数据
  const mergedData: DisplayItem[] = data.map((item) => {
    // 优先用轮询的基差，其次用查询时返回的
    const basis = basisData[item.coin_name] ?? item.realtime_basis ?? undefined;
    const pc = priceChanges[item.coin_name];
    return {
      ...item,
      realtime_basis: basis,
      change_1d: pc?.change_1d,
    };
  });

  const handleFundingClick = (coin: string) => {
    const start = dayjs().subtract(hours, 'hour');
    const end = dayjs();
    setCalcInitial({
      coin,
      longExchange: 'BN',
      shortExchange: 'BN',
      timeRange: [start, end],
    });
    setCalcOpen(true);
  };

  const columns: ColumnsType<DisplayItem> = [
    {
      title: '#',
      key: 'index',
      width: 50,
      render: (_, __, index) => index + 1,
    },
    {
      title: '代币名称',
      dataIndex: 'coin_name',
      key: 'coin_name',
      width: 120,
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
      title: '累计资费',
      dataIndex: 'cumulative_funding',
      key: 'cumulative_funding',
      width: 120,
      sorter: (a, b) => (a.cumulative_funding ?? 0) - (b.cumulative_funding ?? 0),
      render: (val: number | null, record: DisplayItem) => (
        <a onClick={() => handleFundingClick(record.coin_name)} style={{ cursor: 'pointer' }}>
          {renderPercent(val)}
        </a>
      ),
    },
    {
      title: '结算周期',
      dataIndex: 'settlement_period',
      key: 'settlement_period',
      width: 90,
      sorter: (a, b) => (a.settlement_period ?? 8) - (b.settlement_period ?? 8),
      render: (val: number | null) => val ? `${val}h` : '—',
    },
    {
      title: '24h涨幅',
      dataIndex: 'change_1d',
      key: 'change_1d',
      width: 100,
      sorter: (a, b) => (a.change_1d ?? 0) - (b.change_1d ?? 0),
      render: (val: number | undefined) => renderPercent(val ?? null, 2),
    },
    {
      title: '实时基差',
      dataIndex: 'realtime_basis',
      key: 'realtime_basis',
      width: 110,
      sorter: (a, b) => (a.realtime_basis ?? 0) - (b.realtime_basis ?? 0),
      render: (val: number | undefined) => {
        if (val === undefined) return <span style={{ color: '#d9d9d9' }}>—</span>;
        const color = val < -1 ? '#F23645' : val < 0 ? '#faad14' : '#22AB94';
        return <span style={{ color, fontWeight: 600 }}>{val.toFixed(4)}%</span>;
      },
    },
  ];

  return (
    <Card
      title={<span style={{ fontSize: 16, fontWeight: 600 }}>大额基差</span>}
      extra={
        <Space align="center">
          {lastUpdate && <span style={{ color: '#999', fontSize: 12 }}>更新时间：{lastUpdate}</span>}
          <Button size="small" icon={<ReloadOutlined />} onClick={handleQuery} loading={loading}>刷新</Button>
        </Space>
      }
    >
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col>
          <Space size={4}>
            <span>时间范围：</span>
            <Select
              value={hours}
              onChange={setHours}
              options={timeOptions}
              style={{ width: 130 }}
            />
          </Space>
        </Col>
        <Col>
          <Space size={4}>
            <span>最小基差(%)：</span>
            <InputNumber
              value={threshold}
              onChange={(v) => v !== null && setThreshold(v)}
              step={0.5}
              style={{ width: 100 }}
            />
          </Space>
        </Col>
        <Col>
          <Button
            type="primary"
            icon={<SearchOutlined />}
            onClick={handleQuery}
            loading={loading}
          >
            查询
          </Button>
        </Col>
      </Row>

      <Table<DisplayItem>
        columns={columns}
        dataSource={mergedData}
        rowKey="raw"
        loading={loading}
        size="small"
        pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
        locale={{ emptyText: '点击查询获取数据' }}
      />

      <Calculator
        open={calcOpen}
        onClose={() => { setCalcOpen(false); setCalcInitial(undefined); }}
        initialValues={calcInitial}
      />
    </Card>
  );
}
