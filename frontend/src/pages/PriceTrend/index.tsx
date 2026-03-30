import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Button, Space, Typography, message } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { priceTrendApi, type PriceTrendItem } from '../../api/priceTrend';
import { useWsStore } from '../../stores/wsStore';

const { Text } = Typography;

export default function PriceTrend() {
  const [data, setData] = useState<PriceTrendItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<string>('');

  const wsData = useWsStore((s) => s.priceTrend) as PriceTrendItem[];

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await priceTrendApi.getData();
      setData(res.data);
      setLastRefresh(new Date().toLocaleString());
    } catch {
      message.error('Failed to fetch price trend data');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleRefresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await priceTrendApi.refresh();
      setData(res.data);
      setLastRefresh(new Date().toLocaleString());
      message.success('Price trend data refreshed');
    } catch {
      message.error('Failed to refresh price trend data');
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Update from WebSocket
  useEffect(() => {
    if (wsData && wsData.length > 0) {
      setData(wsData);
      setLastRefresh(new Date().toLocaleString());
    }
  }, [wsData]);

  const renderBool = (value: boolean) =>
    value ? (
      <CheckCircleOutlined style={{ color: '#22AB94', fontSize: 18 }} />
    ) : (
      <CloseCircleOutlined style={{ color: '#F23645', fontSize: 18 }} />
    );

  const columns: ColumnsType<PriceTrendItem> = [
    {
      title: '币种名称',
      dataIndex: 'coin_name',
      key: 'coin_name',
      width: 120,
      fixed: 'left',
    },
    {
      title: '日线',
      dataIndex: 'daily',
      key: 'daily',
      width: 80,
      align: 'center',
      render: renderBool,
    },
    {
      title: '4小时',
      dataIndex: 'h4',
      key: 'h4',
      width: 80,
      align: 'center',
      render: renderBool,
    },
    {
      title: '1小时',
      dataIndex: 'h1',
      key: 'h1',
      width: 80,
      align: 'center',
      render: renderBool,
    },
    {
      title: '15分钟',
      dataIndex: 'm15',
      key: 'm15',
      width: 80,
      align: 'center',
      render: renderBool,
    },
  ];

  return (
    <Card
      title="价格趋势"
      extra={
        <Space>
          {lastRefresh && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              最后更新: {lastRefresh}
            </Text>
          )}
          <Button
            icon={<ReloadOutlined />}
            onClick={handleRefresh}
            loading={loading}
          >
            刷新
          </Button>
        </Space>
      }
    >
      <Table<PriceTrendItem>
        columns={columns}
        dataSource={data}
        rowKey="coin_name"
        loading={loading}
        size="small"
        pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
        scroll={{ x: 440 }}
      />
    </Card>
  );
}
