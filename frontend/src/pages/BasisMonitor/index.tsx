import { useEffect, useState, useCallback, useRef } from 'react';
import {
  Card, Table, Tag, Typography, Button, Space, message,
  Timeline, InputNumber, Row, Col, Popover, Modal, Input,
} from 'antd';
import { ClearOutlined, ReloadOutlined, SettingOutlined } from '@ant-design/icons';
import NProgress from 'nprogress';
import type { ColumnsType } from 'antd/es/table';
import { useWsStore } from '../../stores/wsStore';
import {
  basisMonitorApi,
  type BasisRecord,
  type TimelineEvent,
  type BasisConfig,
} from '../../api/basisMonitor';
import { useAuthStore } from '../../stores/authStore';

const { Text } = Typography;

const renderBasis = (val: number | null | undefined) => {
  if (val === null || val === undefined) return <span style={{ color: '#d9d9d9' }}>—</span>;
  const color = val < -1 ? '#F23645' : val < 0 ? '#faad14' : '#22AB94';
  return <span style={{ color, fontWeight: 600 }}>{val.toFixed(4)}%</span>;
};

const renderPercent = (val: number | null | undefined, decimals = 2) => {
  if (val === null || val === undefined) return <span style={{ color: '#d9d9d9' }}>—</span>;
  const color = val > 0 ? '#22AB94' : val < 0 ? '#F23645' : undefined;
  return <span style={{ color }}>{val >= 0 ? '+' : ''}{val.toFixed(decimals)}%</span>;
};

export default function BasisMonitor() {
  const [records, setRecords] = useState<BasisRecord[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true); // only for first load
  const [lastUpdate, setLastUpdate] = useState('');
  const isFirstLoad = useRef(true);
  const [config, setConfig] = useState<BasisConfig>({ basis_threshold: -1, expand_multiplier: 1.1, blocked_coins: '', temp_blocked_coins: '' });
  const [editThreshold, setEditThreshold] = useState(-1);
  const [editMultiplier, setEditMultiplier] = useState(1.1);
  const [editBlocked, setEditBlocked] = useState('');
  const [editTempBlocked, setEditTempBlocked] = useState('');
  const [configOpen, setConfigOpen] = useState(false);

  const [coinAlerts, setCoinAlerts] = useState<TimelineEvent[]>([]);
  const [coinAlertModal, setCoinAlertModal] = useState<string | null>(null);

  const isLoggedIn = useAuthStore((s) => !!s.token);
  const wsData = useWsStore((s) => s.basisMonitor);

  const fetchData = useCallback(async () => {
    if (isFirstLoad.current) {
      setLoading(true);
    } else {
      NProgress.start();
    }
    try {
      const data = await basisMonitorApi.getData();
      setRecords(data.records);
      setTimeline(data.timeline);
      setLastUpdate(new Date().toLocaleString());
    } catch {
      // silent
    } finally {
      if (isFirstLoad.current) {
        setLoading(false);
        isFirstLoad.current = false;
      } else {
        NProgress.done();
      }
    }
  }, []);

  const fetchConfig = useCallback(async () => {
    try {
      const cfg = await basisMonitorApi.getConfig();
      setConfig(cfg);
      setEditThreshold(cfg.basis_threshold);
      setEditMultiplier(cfg.expand_multiplier);
      setEditBlocked(cfg.blocked_coins || '');
      setEditTempBlocked(cfg.temp_blocked_coins || '');
    } catch {
      // use defaults
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchData();
    fetchConfig();
  }, [fetchData, fetchConfig]);

  // Auto refresh every 5 seconds
  useEffect(() => {
    const timer = setInterval(fetchData, 5000);
    return () => clearInterval(timer);
  }, [fetchData]);

  // Also refresh on WebSocket signal
  useEffect(() => {
    if (wsData) {
      fetchData();
    }
  }, [wsData, fetchData]);

  const handleClear = async () => {
    try {
      await basisMonitorApi.clear();
      setRecords([]);
      setTimeline([]);
      message.success('已清除');
    } catch {
      message.error('清除失败');
    }
  };

  const handleSaveConfig = async () => {
    if (!isLoggedIn) {
      message.warning('请先登录');
      return;
    }
    try {
      await basisMonitorApi.updateConfig(editThreshold, editMultiplier, editBlocked, editTempBlocked);
      setConfig({ basis_threshold: editThreshold, expand_multiplier: editMultiplier, blocked_coins: editBlocked, temp_blocked_coins: editTempBlocked });
      setConfigOpen(false);
      message.success('配置已保存');
      fetchData(); // Refresh with new config
    } catch {
      message.error('保存失败');
    }
  };

  const columns: ColumnsType<BasisRecord> = [
    {
      title: '币种名称',
      dataIndex: 'coin_name',
      key: 'coin_name',
      width: 100,
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
      title: '实时基差',
      dataIndex: 'current_basis',
      key: 'current_basis',
      width: 110,
      sorter: (a, b) => (a.current_basis ?? 0) - (b.current_basis ?? 0),
      render: renderBasis,
    },
    {
      title: '最大基差',
      dataIndex: 'min_basis',
      key: 'min_basis',
      width: 110,
      sorter: (a, b) => a.min_basis - b.min_basis,
      render: renderBasis,
    },
    {
      title: '预警次数',
      dataIndex: 'alert_count',
      key: 'alert_count',
      width: 80,
      sorter: (a, b) => a.alert_count - b.alert_count,
      render: (count: number, record: BasisRecord) => (
        <a onClick={async () => {
          try {
            const alerts = await basisMonitorApi.getCoinAlerts(record.coin_name);
            setCoinAlerts(alerts);
            setCoinAlertModal(record.coin_name);
          } catch { message.error('获取详情失败'); }
        }}>
          <Tag color={count > 3 ? 'red' : count > 1 ? 'orange' : 'blue'} style={{ cursor: 'pointer' }}>{count}次</Tag>
        </a>
      ),
    },
    {
      title: '24h涨幅',
      dataIndex: 'change_1d',
      key: 'change_1d',
      width: 100,
      sorter: (a, b) => (a.change_1d ?? 0) - (b.change_1d ?? 0),
      render: (val: number | null) => renderPercent(val),
    },
    {
      title: '最新预警时间',
      dataIndex: 'last_alert_at',
      key: 'last_alert_at',
      width: 160,
    },
  ];

  const configContent = (
    <div style={{ width: 220 }}>
      <div style={{ marginBottom: 12 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>基差阈值(%)</Text>
        <InputNumber
          value={editThreshold}
          onChange={(v) => v !== null && setEditThreshold(v)}
          step={0.5}
          style={{ width: '100%', marginTop: 4 }}
        />
      </div>
      <div style={{ marginBottom: 12 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>扩大倍数</Text>
        <InputNumber
          value={editMultiplier}
          onChange={(v) => v !== null && setEditMultiplier(v)}
          step={0.1}
          min={1.01}
          style={{ width: '100%', marginTop: 4 }}
        />
      </div>
      <div style={{ marginBottom: 12 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>长期不看（清除不会删）</Text>
        <Input
          value={editBlocked}
          onChange={(e) => setEditBlocked(e.target.value)}
          placeholder="如: BTC,ETH"
          style={{ marginTop: 4 }}
        />
      </div>
      <div style={{ marginBottom: 12 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>临时不看（清除会删）</Text>
        <Input
          value={editTempBlocked}
          onChange={(e) => setEditTempBlocked(e.target.value)}
          placeholder="如: SOL,DOGE"
          style={{ marginTop: 4 }}
        />
      </div>
      <Button type="primary" size="small" block onClick={handleSaveConfig}>
        {isLoggedIn ? '保存' : '请先登录'}
      </Button>
    </div>
  );

  return (
    <Card
      title={
        <Space align="center" size={12}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>基差监控</span>
          {lastUpdate && <Text type="secondary" style={{ fontSize: 12 }}>更新时间：{lastUpdate}</Text>}
          <Text type="secondary" style={{ fontSize: 12 }}>
            阈值: {config.basis_threshold}% | 倍数: {config.expand_multiplier}x
          </Text>
        </Space>
      }
      extra={
        <Space>
          <Popover
            content={configContent}
            title="预警配置"
            trigger="click"
            open={configOpen}
            onOpenChange={setConfigOpen}
          >
            <Button size="small" icon={<SettingOutlined />}>配置</Button>
          </Popover>
          <Button size="small" icon={<ReloadOutlined />} onClick={async () => {
            NProgress.start();
            try {
              const data = await basisMonitorApi.refresh();
              setRecords(data.records);
              setTimeline(data.timeline);
              setLastUpdate(new Date().toLocaleString());
            } catch { message.error('刷新失败'); }
            finally { NProgress.done(); }
          }}>刷新</Button>
          <Button size="small" icon={<ClearOutlined />} onClick={handleClear} danger>清除</Button>
        </Space>
      }
    >
      <Row gutter={24}>
        {/* Left: Alert Table */}
        <Col span={14}>
          <Table<BasisRecord>
            columns={columns}
            dataSource={records}
            rowKey="coin_name"
            size="small"
            loading={loading}
            pagination={{ pageSize: 30, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
            locale={{ emptyText: '暂无预警数据' }}
            scroll={{ x: 660 }}
          />
        </Col>

        {/* Right: Timeline */}
        <Col span={10}>
          <Text strong style={{ display: 'block', marginBottom: 12 }}>预警动态</Text>
          <div style={{ height: 'calc(100vh - 320px)', overflowY: 'auto', paddingRight: 8, borderLeft: '1px solid #f0f0f0', paddingLeft: 16 }}>
            {timeline.length === 0 ? (
              <div style={{ color: '#999', textAlign: 'center', padding: 40 }}>暂无动态</div>
            ) : (
              <Timeline
                items={timeline.map((event) => ({
                  color: event.alert_type === '新机会' ? 'green' : 'red',
                  children: (
                    <div>
                      <div style={{ fontSize: 12, color: '#999' }}>{event.time}</div>
                      <div>
                        <strong>{event.coin_name}</strong>
                        {' '}
                        <Tag color={event.alert_type === '新机会' ? 'green' : 'red'} style={{ fontSize: 11 }}>
                          {event.alert_type}
                        </Tag>
                        {' '}
                        <span style={{ color: '#F23645', fontWeight: 600 }}>
                          {event.basis.toFixed(4)}%
                        </span>
                      </div>
                    </div>
                  ),
                }))}
              />
            )}
          </div>
        </Col>
      </Row>
      <Modal
        title={`${coinAlertModal} 预警历史`}
        open={!!coinAlertModal}
        onCancel={() => setCoinAlertModal(null)}
        footer={null}
        width={500}
      >
        <Table<TimelineEvent>
          columns={[
            { title: '预警时间', dataIndex: 'time', key: 'time', width: 170 },
            {
              title: '基差',
              dataIndex: 'basis',
              key: 'basis',
              width: 120,
              render: renderBasis,
            },
            {
              title: '类型',
              dataIndex: 'alert_type',
              key: 'alert_type',
              width: 100,
              render: (type: string) => (
                <Tag color={type === '新机会' ? 'green' : 'red'}>{type}</Tag>
              ),
            },
          ]}
          dataSource={coinAlerts}
          rowKey="timestamp"
          size="small"
          pagination={false}
        />
      </Modal>
    </Card>
  );
}
