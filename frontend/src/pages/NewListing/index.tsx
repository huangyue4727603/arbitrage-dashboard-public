import { useEffect, useState, useCallback, useMemo } from 'react';
import { Card, Table, Tag, Space, Select, Row, Col, Button } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';

const exchangeTagColor: Record<string, string> = {
  BN: 'gold',
  OKX: 'blue',
  BY: 'green',
};

const periodTagColor: Record<number, string> = {
  8: 'green',
  4: 'cyan',
  2: 'purple',
  1: 'magenta',
};
import type { ColumnsType } from 'antd/es/table';
import { fetchNewListings, type NewListingItem } from '../../api/newListing';

const REFRESH_INTERVAL = 60 * 1000;

const exchangeLabel: Record<string, string> = {
  BN: 'Binance',
  OKX: 'OKX',
  BY: 'Bybit',
};

const exchangeOptions = [
  { label: '全部', value: '' },
  { label: 'Binance', value: 'BN' },
  { label: 'OKX', value: 'OKX' },
  { label: 'Bybit', value: 'BY' },
];

const periodOptions = [
  { label: '全部', value: 0 },
  { label: '1h', value: 1 },
  { label: '2h', value: 2 },
  { label: '4h', value: 4 },
  { label: '8h', value: 8 },
];

const renderPercent = (val: number | null, decimals = 3) => {
  if (val === null || val === undefined) return <span style={{ color: '#d9d9d9' }}>—</span>;
  const color = val > 0 ? '#22AB94' : val < 0 ? '#F23645' : undefined;
  return <span style={{ color }}>{val >= 0 ? '+' : ''}{val.toFixed(decimals)}%</span>;
};

export default function NewListing() {
  const [data, setData] = useState<NewListingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [exchange, setExchange] = useState('');
  const [period, setPeriod] = useState(0);
  const [lastUpdate, setLastUpdate] = useState('');

  const loadData = useCallback(async () => {
    try {
      const result = await fetchNewListings();
      setData(result);
      setLastUpdate(new Date().toLocaleString());
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, REFRESH_INTERVAL);
    return () => clearInterval(timer);
  }, [loadData]);

  const filteredData = useMemo(() => {
    let list = data;
    if (exchange) list = list.filter((item) => item.exchange === exchange);
    if (period) list = list.filter((item) => item.settlement_period === period);
    return list;
  }, [data, exchange, period]);

  const columns: ColumnsType<NewListingItem> = [
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
      render: (ex: string) => <Tag color={exchangeTagColor[ex] || 'default'}>{exchangeLabel[ex] || ex}</Tag>,
    },
    {
      title: '上线天数',
      dataIndex: 'listing_days',
      key: 'listing_days',
      width: 90,
      sorter: (a, b) => a.listing_days - b.listing_days,
      defaultSortOrder: 'ascend',
      render: (days: number) => (
        <span style={{ fontWeight: days <= 3 ? 'bold' : 'normal', color: days <= 3 ? '#F23645' : undefined }}>
          {days} 天
        </span>
      ),
    },
    {
      title: '实时资费',
      dataIndex: 'current_funding_rate',
      key: 'current_funding_rate',
      width: 100,
      sorter: (a, b) => (a.current_funding_rate ?? 0) - (b.current_funding_rate ?? 0),
      render: (rate: number | null) => renderPercent(rate),
    },
    {
      title: '结算周期',
      dataIndex: 'settlement_period',
      key: 'settlement_period',
      width: 80,
      align: 'center',
      render: (p: number) => <Tag color={periodTagColor[p] || 'default'}>{p}h</Tag>,
    },
    {
      title: '1d资费累计',
      dataIndex: 'funding_1d',
      key: 'funding_1d',
      width: 100,
      sorter: (a, b) => (a.funding_1d ?? 0) - (b.funding_1d ?? 0),
      render: (val: number | null) => renderPercent(val),
    },
    {
      title: '3d资费累计',
      dataIndex: 'funding_3d',
      key: 'funding_3d',
      width: 100,
      sorter: (a, b) => (a.funding_3d ?? 0) - (b.funding_3d ?? 0),
      render: (val: number | null) => renderPercent(val),
    },
    {
      title: '上线后涨幅',
      dataIndex: 'price_change',
      key: 'price_change',
      width: 110,
      sorter: (a, b) => (a.price_change ?? 0) - (b.price_change ?? 0),
      render: (val: number | null) => renderPercent(val, 2),
    },
    {
      title: '1d涨幅',
      dataIndex: 'change_1d',
      key: 'change_1d',
      width: 90,
      sorter: (a, b) => (a.change_1d ?? 0) - (b.change_1d ?? 0),
      render: (val: number | null) => renderPercent(val, 2),
    },
  ];

  return (
    <Card title="新上线币种" extra={
      <Space>
        {lastUpdate && <span style={{ color: '#999', fontSize: 12 }}>更新时间：{lastUpdate}</span>}
        <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading}>刷新</Button>
      </Space>
    }>
      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col>
          <Space size={4}>
            <span>交易所：</span>
            <Select
              value={exchange}
              onChange={setExchange}
              options={exchangeOptions}
              style={{ width: 100 }}
            />
          </Space>
        </Col>
        <Col>
          <Space size={4}>
            <span>结算周期：</span>
            <Select
              value={period}
              onChange={setPeriod}
              options={periodOptions}
              style={{ width: 80 }}
            />
          </Space>
        </Col>
      </Row>
      <Table<NewListingItem>
        columns={columns}
        dataSource={filteredData}
        loading={loading}
        rowKey={(record) => `${record.coin_name}_${record.exchange}`}
        pagination={{ pageSize: 100, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
        size="small"
        scroll={{ x: 960 }}
      />
    </Card>
  );
}
