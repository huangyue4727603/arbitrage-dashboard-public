import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Table,
  Button,
  Modal,
  Form,
  AutoComplete,
  Select,
  InputNumber,
  Switch,
  Space,
  Popconfirm,
  message,
  Spin,
  Tag,
} from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  getMonitors,
  createMonitor,
  updateMonitor,
  toggleMonitor,
  deleteMonitor,
  getLarkBots,
  getAvailableCoins,
} from '../../api/alert';
import type { Monitor, MonitorForm, LarkBot, AvailableCoins } from '../../api/alert';

export default function PostInvestment() {
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [bots, setBots] = useState<LarkBot[]>([]);
  const [availableCoins, setAvailableCoins] = useState<AvailableCoins>({});
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingMonitor, setEditingMonitor] = useState<Monitor | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [selectedCoin, setSelectedCoin] = useState('');
  const [form] = Form.useForm<MonitorForm>();

  const fetchData = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const [monitorsData, botsData] = await Promise.all([getMonitors(), getLarkBots()]);
      monitorsData.sort((a, b) => (a.is_active === b.is_active ? 0 : a.is_active ? -1 : 1));
      setMonitors(monitorsData);
      setBots(botsData);
    } catch {
      if (showLoading) message.error('获取数据失败');
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

  const fetchAvailableCoins = useCallback(async () => {
    try {
      const data = await getAvailableCoins();
      setAvailableCoins(data);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchData(true);
    fetchAvailableCoins();
  }, [fetchData, fetchAvailableCoins]);

  // Poll every 5s, but pause when modal is open
  useEffect(() => {
    if (modalOpen) return;
    const timer = setInterval(() => fetchData(false), 5000);
    return () => clearInterval(timer);
  }, [fetchData, modalOpen]);

  // Coin options for autocomplete
  const coinOptions = useMemo(
    () => Object.keys(availableCoins).sort().map((c) => ({ value: c, label: c })),
    [availableCoins],
  );

  // Available exchange pairs for the selected coin
  const exchangePairs = useMemo(() => {
    const coin = selectedCoin.toUpperCase();
    return availableCoins[coin] || [];
  }, [availableCoins, selectedCoin]);

  const longExchangeOptions = useMemo(() => {
    const set = new Set(exchangePairs.map((p) => p.long_exchange));
    return Array.from(set).map((e) => ({ label: e, value: e }));
  }, [exchangePairs]);

  const shortExchangeOptions = useMemo(() => {
    const longEx = form.getFieldValue('long_exchange');
    const pairs = longEx
      ? exchangePairs.filter((p) => p.long_exchange === longEx)
      : exchangePairs;
    const set = new Set(pairs.map((p) => p.short_exchange));
    return Array.from(set).map((e) => ({ label: e, value: e }));
  }, [exchangePairs, form]);

  const handleCoinChange = (value: string) => {
    setSelectedCoin(value);
    // Clear exchange selections when coin changes
    form.setFieldsValue({ long_exchange: undefined, short_exchange: undefined });
  };

  const handleLongExchangeChange = () => {
    // Clear short exchange when long exchange changes
    form.setFieldsValue({ short_exchange: undefined });
  };

  const openAddModal = () => {
    setEditingMonitor(null);
    setSelectedCoin('');
    form.resetFields();
    form.setFieldsValue({ sound_enabled: true, popup_enabled: true });
    fetchAvailableCoins();
    setModalOpen(true);
  };

  const openEditModal = (monitor: Monitor) => {
    setEditingMonitor(monitor);
    setSelectedCoin(monitor.coin_name);
    form.setFieldsValue({
      coin_name: monitor.coin_name,
      long_exchange: monitor.long_exchange,
      short_exchange: monitor.short_exchange,
      spread_threshold: monitor.spread_threshold,
      price_threshold: monitor.price_threshold,
      oi_drop_1h_threshold: monitor.oi_drop_1h_threshold,
      oi_drop_4h_threshold: monitor.oi_drop_4h_threshold,
      sound_enabled: monitor.sound_enabled,
      popup_enabled: monitor.popup_enabled,
      lark_bot_id: monitor.lark_bot_id,
    });
    fetchAvailableCoins();
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      // Ensure coin_name is uppercase
      values.coin_name = values.coin_name.toUpperCase();
      setSubmitting(true);
      if (editingMonitor) {
        await updateMonitor(editingMonitor.id, values);
        message.success('更新成功');
      } else {
        await createMonitor(values);
        message.success('添加成功');
      }
      setModalOpen(false);
      form.resetFields();
      setEditingMonitor(null);
      fetchData();
    } catch {
      // validation or api error
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggle = async (id: number) => {
    try {
      await toggleMonitor(id);
      fetchData();
    } catch {
      message.error('操作失败');
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteMonitor(id);
      message.success('删除成功');
      fetchData();
    } catch {
      message.error('删除失败');
    }
  };

  const isTriggered = (r: Monitor): boolean => {
    if (!r.is_active) return false;
    if (r.spread_threshold != null && r.current_spread != null && r.current_spread < r.spread_threshold) return true;
    if (r.price_threshold != null && r.current_price != null && r.current_price < r.price_threshold) return true;
    if (r.oi_drop_1h_threshold != null && r.current_oi_drop_1h != null && r.current_oi_drop_1h < r.oi_drop_1h_threshold) return true;
    if (r.oi_drop_4h_threshold != null && r.current_oi_drop_4h != null && r.current_oi_drop_4h < r.oi_drop_4h_threshold) return true;
    return false;
  };

  const renderThresholdCell = (threshold: number | null, current: number | null, suffix?: string) => {
    const thresholdStr = threshold != null ? `${threshold}${suffix || ''}` : '-';
    const currentStr = current != null ? `${current}${suffix || ''}` : '-';
    return (
      <span>
        <span>{thresholdStr}</span>
        <span style={{ color: '#888', margin: '0 4px' }}>/</span>
        <span style={{ color: current != null && threshold != null ? '#1890ff' : undefined }}>
          {currentStr}
        </span>
      </span>
    );
  };

  const columns: ColumnsType<Monitor> = [
    {
      title: '币种名称',
      dataIndex: 'coin_name',
      key: 'coin_name',
      width: 120,
      render: (name: string) => <Tag color="blue">{name}</Tag>,
    },
    {
      title: '开差阈值/实时',
      key: 'spread',
      width: 150,
      render: (_, r) => renderThresholdCell(r.spread_threshold, r.current_spread),
    },
    {
      title: '价格阈值/实时',
      key: 'price',
      width: 150,
      render: (_, r) => renderThresholdCell(r.price_threshold, r.current_price),
    },
    {
      title: '1h持仓跌幅阈值/实时',
      key: 'oi_1h',
      width: 180,
      render: (_, r) => renderThresholdCell(r.oi_drop_1h_threshold, r.current_oi_drop_1h, '%'),
    },
    {
      title: '4h持仓跌幅阈值/实时',
      key: 'oi_4h',
      width: 180,
      render: (_, r) => renderThresholdCell(r.oi_drop_4h_threshold, r.current_oi_drop_4h, '%'),
    },
    {
      title: '状态',
      key: 'status',
      width: 80,
      render: (_, record) => (
        <Switch
          checked={record.is_active}
          size="small"
          onChange={() => handleToggle(record.id)}
        />
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_, record) => (
        <Popconfirm
          title="确定删除此监测？"
          onConfirm={() => handleDelete(record.id)}
          okText="确定"
          cancelText="取消"
        >
          <Button type="text" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  if (loading && monitors.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <Spin />
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontWeight: 600, fontSize: 15 }}>投后监测列表</span>
        <Button type="primary" icon={<PlusOutlined />} onClick={openAddModal}>
          添加监测
        </Button>
      </div>
      <Table
        columns={columns}
        dataSource={monitors}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={false}
        scroll={{ x: 900 }}
        onRow={(record) => ({
          onDoubleClick: () => openEditModal(record),
          style: {
            cursor: 'pointer',
            backgroundColor: isTriggered(record) ? '#fff1f0' : undefined,
          },
        })}
      />
      <Modal
        title={editingMonitor ? '编辑监测' : '添加监测'}
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false);
          form.resetFields();
          setEditingMonitor(null);
          setSelectedCoin('');
        }}
        onOk={handleSubmit}
        confirmLoading={submitting}
        okText="确定"
        cancelText="取消"
        destroyOnClose
        width={520}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="coin_name"
            label="币种名称"
            rules={[{ required: true, message: '请输入币种名称' }]}
          >
            <AutoComplete
              options={coinOptions}
              placeholder="输入币种搜索，如：BTC"
              onChange={handleCoinChange}
              filterOption={(input, option) =>
                (option?.value as string).includes(input.toUpperCase())
              }
            />
          </Form.Item>
          <Space style={{ width: '100%' }} size="middle">
            <Form.Item
              name="long_exchange"
              label="做多交易所"
              rules={[{ required: true, message: '请选择' }]}
              style={{ width: 200 }}
            >
              <Select
                options={longExchangeOptions}
                placeholder={selectedCoin ? '选择交易所' : '请先选择币种'}
                disabled={longExchangeOptions.length === 0}
                onChange={handleLongExchangeChange}
              />
            </Form.Item>
            <Form.Item
              name="short_exchange"
              label="做空交易所"
              rules={[{ required: true, message: '请选择' }]}
              style={{ width: 200 }}
            >
              <Select
                options={shortExchangeOptions}
                placeholder={selectedCoin ? '选择交易所' : '请先选择币种'}
                disabled={shortExchangeOptions.length === 0}
              />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} size="middle">
            <Form.Item name="spread_threshold" label="开差阈值" style={{ width: 200 }}>
              <InputNumber placeholder="可选" style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="price_threshold" label="价格阈值" style={{ width: 200 }}>
              <InputNumber placeholder="可选" style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} size="middle">
            <Form.Item name="oi_drop_1h_threshold" label="1小时持仓跌幅阈值" style={{ width: 200 }}>
              <InputNumber placeholder="如 -20" style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="oi_drop_4h_threshold" label="4小时持仓跌幅阈值" style={{ width: 200 }}>
              <InputNumber placeholder="可选" style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Space size="large">
            <Form.Item name="sound_enabled" label="声音开关" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="popup_enabled" label="弹窗开关" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
          <Form.Item name="lark_bot_id" label="Lark机器人">
            <Select
              allowClear
              placeholder="选择机器人（可选）"
              options={bots.map((b) => ({ label: b.name, value: b.id }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
