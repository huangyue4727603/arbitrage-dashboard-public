import { useState, useEffect, useCallback } from 'react';
import { Card, Switch, Select, Table, Tag, Space, Typography, message, Spin } from 'antd';
import { SoundOutlined, NotificationOutlined, RobotOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  getLarkBots,
  getFundingBreakAlertConfig,
  updateFundingBreakAlertConfig,
  getFundingBreakAlerts,
  type LarkBot,
  type FundingBreakAlertConfig,
  type FundingBreakAlert,
} from '../../api/alert';

const { Text } = Typography;

const exchangeColor: Record<string, string> = {
  Binance: 'gold',
  OKX: 'blue',
  Bybit: 'green',
};

const renderPercent = (val: number | null | undefined) => {
  if (val === null || val === undefined) return <span style={{ color: '#d9d9d9' }}>—</span>;
  const color = val > 0 ? '#22AB94' : val < 0 ? '#F23645' : undefined;
  return <span style={{ color, fontWeight: 600 }}>{val > 0 ? '+' : ''}{val.toFixed(4)}%</span>;
};

export default function FundingBreakAlertPage() {
  const [config, setConfig] = useState<FundingBreakAlertConfig>({
    sound_enabled: true,
    popup_enabled: true,
    lark_bot_id: null,
  });
  const [alerts, setAlerts] = useState<FundingBreakAlert[]>([]);
  const [bots, setBots] = useState<LarkBot[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    try {
      const [cfg, alertList, botList] = await Promise.all([
        getFundingBreakAlertConfig(),
        getFundingBreakAlerts(),
        getLarkBots(),
      ]);
      setConfig(cfg);
      setAlerts(alertList);
      setBots(botList);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const timer = setInterval(async () => {
      try {
        const alertList = await getFundingBreakAlerts();
        setAlerts(alertList);
      } catch {
        // silent
      }
    }, 10000);
    return () => clearInterval(timer);
  }, [fetchAll]);

  const handleSave = async (newConfig: FundingBreakAlertConfig) => {
    setConfig(newConfig);
    try {
      await updateFundingBreakAlertConfig(newConfig);
      message.success('配置已保存');
    } catch {
      message.error('保存失败');
    }
  };

  const columns: ColumnsType<FundingBreakAlert> = [
    {
      title: '币种',
      dataIndex: 'coin_name',
      key: 'coin_name',
      width: 100,
      render: (name: string) => <strong>{name}</strong>,
    },
    {
      title: '交易所',
      dataIndex: 'exchange',
      key: 'exchange',
      width: 90,
      render: (ex: string) => <Tag color={exchangeColor[ex] || 'default'}>{ex}</Tag>,
    },
    {
      title: '预警时间',
      dataIndex: 'alert_time',
      key: 'alert_time',
      width: 170,
    },
    {
      title: '实时资费',
      dataIndex: 'realtime_funding',
      key: 'realtime_funding',
      width: 110,
      render: renderPercent,
    },
    {
      title: '资费上限',
      dataIndex: 'funding_cap',
      key: 'funding_cap',
      width: 110,
      render: renderPercent,
    },
    {
      title: '实时基差',
      dataIndex: 'basis',
      key: 'basis',
      width: 110,
      render: renderPercent,
    },
  ];

  if (loading) {
    return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>;
  }

  return (
    <div>
      <Card title="预警配置" size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <SoundOutlined />
              <Text>声音提醒</Text>
            </Space>
            <Switch
              checked={config.sound_enabled}
              onChange={(checked) => handleSave({ ...config, sound_enabled: checked })}
            />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <NotificationOutlined />
              <Text>弹窗提醒</Text>
            </Space>
            <Switch
              checked={config.popup_enabled}
              onChange={(checked) => handleSave({ ...config, popup_enabled: checked })}
            />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <RobotOutlined />
              <Text>飞书机器人</Text>
            </Space>
            <Select
              value={config.lark_bot_id}
              onChange={(val) => handleSave({ ...config, lark_bot_id: val })}
              allowClear
              placeholder="选择机器人"
              style={{ width: 180 }}
              options={[
                { label: '不使用', value: null },
                ...bots.map((b) => ({ label: b.name, value: b.id })),
              ]}
            />
          </div>
        </Space>
      </Card>

      <Card title="预警记录" size="small">
        <Table<FundingBreakAlert>
          columns={columns}
          dataSource={alerts}
          rowKey={(r) => `${r.coin_name}-${r.exchange}-${r.timestamp}`}
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
          locale={{ emptyText: '暂无资费突破预警' }}
        />
      </Card>
    </div>
  );
}
