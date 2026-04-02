import { useState, useEffect, useCallback } from 'react';
import { Card, Tabs, Table, Tag, message, Button, Empty, Space } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined } from '@ant-design/icons';
import { useWsStore } from '../../stores/wsStore';
import {
  unhedgedApi,
  type UnhedgedType1,
  type UnhedgedType2,
  type UnhedgedResponse,
} from '../../api/unhedged';

function colorForSpread(val: number) {
  if (val > 0) return '#22AB94';
  if (val < -0.5) return '#F23645';
  return '#faad14';
}

function colorForFundingDiff(val: number) {
  if (val > 0) return '#22AB94';
  return '#F23645';
}

function colorForBasis(val: number) {
  if (val < -3) return '#F23645';
  if (val < -1) return '#faad14';
  return '#22AB94';
}

function colorForPriceChange(val: number) {
  if (val > 0) return '#22AB94';
  if (val < 0) return '#F23645';
  return undefined;
}

const type1Columns: ColumnsType<UnhedgedType1> = [
  {
    title: '币种名称',
    dataIndex: 'coin',
    key: 'coin',
    width: 120,
    render: (coin: string) => <Tag color="blue">{coin}</Tag>,
  },
  {
    title: '做多交易所',
    dataIndex: 'long_exchange',
    key: 'long_exchange',
    width: 120,
  },
  {
    title: '做空交易所',
    dataIndex: 'short_exchange',
    key: 'short_exchange',
    width: 120,
  },
  {
    title: '开差(%)',
    dataIndex: 'spread',
    key: 'spread',
    width: 120,
    sorter: (a, b) => a.spread - b.spread,
    render: (val: number) => (
      <span style={{ color: colorForSpread(val), fontWeight: 600 }}>
        {val.toFixed(4)}%
      </span>
    ),
  },
  {
    title: '资费差(%)',
    dataIndex: 'funding_diff',
    key: 'funding_diff',
    width: 120,
    sorter: (a, b) => a.funding_diff - b.funding_diff,
    render: (val: number) => (
      <span style={{ color: colorForFundingDiff(val), fontWeight: 600 }}>
        {val.toFixed(4)}%
      </span>
    ),
  },
  {
    title: '做空交易所基差',
    dataIndex: 'short_basis',
    key: 'short_basis',
    width: 140,
    sorter: (a, b) => a.short_basis - b.short_basis,
    render: (val: number) => (
      <span style={{ color: colorForBasis(val), fontWeight: 600 }}>
        {val.toFixed(4)}
      </span>
    ),
  },
  {
    title: '提醒时间',
    dataIndex: 'alert_time',
    key: 'alert_time',
    width: 180,
    defaultSortOrder: 'descend',
    sorter: (a, b) => a.timestamp - b.timestamp,
  },
];

const type2Columns: ColumnsType<UnhedgedType2> = [
  {
    title: '币种名称',
    dataIndex: 'coin',
    key: 'coin',
    width: 120,
    render: (coin: string) => <Tag color="orange">{coin}</Tag>,
  },
  {
    title: '做空交易所',
    dataIndex: 'short_exchange',
    key: 'short_exchange',
    width: 120,
  },
  {
    title: '做多交易所',
    dataIndex: 'long_exchange',
    key: 'long_exchange',
    width: 120,
  },
  {
    title: '开差(%)',
    dataIndex: 'spread',
    key: 'spread',
    width: 120,
    sorter: (a, b) => a.spread - b.spread,
    render: (val: number) => (
      <span style={{ color: colorForSpread(val), fontWeight: 600 }}>
        {val.toFixed(4)}%
      </span>
    ),
  },
  {
    title: '做空交易所基差',
    dataIndex: 'short_basis',
    key: 'short_basis',
    width: 140,
    sorter: (a, b) => a.short_basis - b.short_basis,
    render: (val: number) => (
      <span style={{ color: colorForBasis(val), fontWeight: 600 }}>
        {val.toFixed(4)}
      </span>
    ),
  },
  {
    title: '近5分钟涨幅',
    dataIndex: 'price_change_5m',
    key: 'price_change_5m',
    width: 140,
    sorter: (a, b) => a.price_change_5m - b.price_change_5m,
    render: (val: number) => (
      <span style={{ color: colorForPriceChange(val), fontWeight: 600 }}>
        {val.toFixed(4)}%
      </span>
    ),
  },
  {
    title: '提醒时间',
    dataIndex: 'alert_time',
    key: 'alert_time',
    width: 180,
    defaultSortOrder: 'descend',
    sorter: (a, b) => a.timestamp - b.timestamp,
  },
];

export default function Unhedged() {
  const [activeTab, setActiveTab] = useState('type1');
  const [type1Data, setType1Data] = useState<UnhedgedType1[]>([]);
  const [type2Data, setType2Data] = useState<UnhedgedType2[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState('');

  const wsData = useWsStore((s) => s.unhedged) as unknown as UnhedgedResponse | UnhedgedResponse[] | null;

  // Fetch initial data via REST
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await unhedgedApi.getAlerts();
      setType1Data(res.type1 || []);
      setType2Data(res.type2 || []);
      setLastUpdate(new Date().toLocaleString());
    } catch (err: any) {
      message.error(
        '获取非对冲数据失败: ' +
          (err?.response?.data?.detail || err?.message || '未知错误'),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 60000);
    return () => clearInterval(timer);
  }, [fetchData]);

  // Update from WebSocket
  useEffect(() => {
    if (!wsData) return;

    // wsData can be the object directly or wrapped in an array by the store
    let parsed: UnhedgedResponse | null = null;
    if (Array.isArray(wsData)) {
      // The store wraps broadcast data in an array sometimes
      if (wsData.length > 0 && typeof wsData[0] === 'object') {
        const first = wsData[0] as any;
        if ('type1' in first && 'type2' in first) {
          parsed = first as UnhedgedResponse;
        }
      }
    } else if (typeof wsData === 'object' && 'type1' in wsData && 'type2' in wsData) {
      parsed = wsData;
    }

    if (parsed) {
      setType1Data(parsed.type1 || []);
      setType2Data(parsed.type2 || []);
      setLastUpdate(new Date().toLocaleString());
    }
  }, [wsData]);

  const tabItems = [
    {
      key: 'type1',
      label: `资费差套利 (${type1Data.length})`,
      children: type1Data.length === 0 ? (
        <Empty description="暂无资费差套利机会" />
      ) : (
        <Table<UnhedgedType1>
          columns={type1Columns}
          dataSource={type1Data}
          rowKey={(r) => `${r.coin}-${r.long_exchange}-${r.short_exchange}-${r.timestamp}`}
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
          size="small"
          scroll={{ x: 900 }}
          loading={loading}
        />
      ),
    },
    {
      key: 'type2',
      label: `资费打开价差没打开 (${type2Data.length})`,
      children: type2Data.length === 0 ? (
        <Empty description="暂无资费打开价差没打开机会" />
      ) : (
        <Table<UnhedgedType2>
          columns={type2Columns}
          dataSource={type2Data}
          rowKey={(r) => `${r.coin}-${r.short_exchange}-${r.long_exchange}-${r.timestamp}`}
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
          size="small"
          scroll={{ x: 900 }}
          loading={loading}
        />
      ),
    },
  ];

  return (
    <Card
      title={<span style={{ fontSize: 16, fontWeight: 600 }}>非对冲机会</span>}
      extra={
        <Space align="center">
          {lastUpdate && <span style={{ color: '#999', fontSize: 12 }}>更新时间：{lastUpdate}</span>}
          <Button size="small" icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>
            刷新
          </Button>
        </Space>
      }
    >
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </Card>
  );
}
