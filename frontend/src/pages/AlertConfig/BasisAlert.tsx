import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Collapse,
  Form,
  InputNumber,
  Input,
  Switch,
  Select,
  Button,
  Table,
  Tag,
  Space,
  message,
  Spin,
} from 'antd';
import { SaveOutlined, SettingOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  getBasisConfig,
  updateBasisConfig,
  getBasisHistory,
  getLarkBots,
} from '../../api/alert';
import type { BasisConfigForm, BasisHistoryItem, LarkBot } from '../../api/alert';
import client from '../../api/client';

export default function BasisAlert() {
  const [bots, setBots] = useState<LarkBot[]>([]);
  const [history, setHistory] = useState<BasisHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [form] = Form.useForm<BasisConfigForm>();

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    try {
      const [config, botsData, monitorConfig] = await Promise.all([
        getBasisConfig(),
        getLarkBots(),
        client.get('/api/basis-monitor/config').then((r) => r.data.data).catch(() => null),
      ]);
      setBots(botsData);
      form.setFieldsValue({
        basis_threshold: config.basis_threshold,
        expand_multiplier: config.expand_multiplier,
        clear_interval_hours: config.clear_interval_hours,
        blocked_coins: config.blocked_coins ? config.blocked_coins.join(',') : '',
        temp_blocked_coins: monitorConfig?.temp_blocked_coins || '',
        sound_enabled: config.sound_enabled,
        popup_enabled: config.popup_enabled,
        lark_bot_id: config.lark_bot_id,
      });
    } catch {
      // Use default form values
    } finally {
      setLoading(false);
    }
  }, [form]);

  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const data = await getBasisHistory();
      setHistory(data);
    } catch {
      // ignore
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
    fetchHistory();
  }, [fetchConfig, fetchHistory]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      // Convert blocked_coins from comma-separated string to array
      const payload = {
        ...values,
        blocked_coins: values.blocked_coins
          ? String(values.blocked_coins).split(',').map((s: string) => s.trim()).filter(Boolean)
          : [],
      };
      // Save permanent config to DB
      await updateBasisConfig(payload as any);
      // Save temp blocked + threshold/multiplier to basis-monitor (in-memory)
      const tempBlocked = values.temp_blocked_coins
        ? String(values.temp_blocked_coins).trim()
        : '';
      await client.put('/api/basis-monitor/config', null, {
        params: {
          basis_threshold: values.basis_threshold,
          expand_multiplier: values.expand_multiplier,
          blocked_coins: values.blocked_coins ? String(values.blocked_coins).trim() : '',
          temp_blocked_coins: tempBlocked,
        },
      });
      message.success('配置已保存');
    } catch {
      // validation or api error
    } finally {
      setSaving(false);
    }
  };

  const alertTypeColor: Record<string, string> = {
    new: 'green',
    expand: 'orange',
    new_opportunity: 'green',
    basis_expand: 'orange',
    default: 'blue',
  };

  const alertTypeLabel: Record<string, string> = {
    new: '新机会',
    expand: '基差扩大',
    new_opportunity: '新机会',
    basis_expand: '基差扩大',
  };

  const historyColumns: ColumnsType<BasisHistoryItem> = [
    {
      title: '时间',
      dataIndex: 'alert_at',
      key: 'alert_at',
      width: 180,
      render: (val: string) => {
        if (!val) return '-';
        const d = new Date(val);
        return d.toLocaleString('zh-CN', { hour12: false });
      },
    },
    {
      title: '币种',
      dataIndex: 'coin_name',
      key: 'coin_name',
      width: 120,
      render: (s: string) => <Tag color="blue">{s}</Tag>,
    },
    {
      title: '预警类型',
      dataIndex: 'alert_type',
      key: 'alert_type',
      width: 120,
      render: (t: string) => (
        <Tag color={alertTypeColor[t] || alertTypeColor.default}>
          {alertTypeLabel[t] || t}
        </Tag>
      ),
    },
    {
      title: '基差值',
      dataIndex: 'basis_value',
      key: 'basis_value',
      width: 120,
      render: (v: number) => (v != null ? v.toFixed(4) : '-'),
    },
  ];

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <Spin />
      </div>
    );
  }

  return (
    <div>
      <Collapse
        size="small"
        style={{ marginBottom: 16 }}
        items={[
          {
            key: 'config',
            label: (
              <span>
                <SettingOutlined style={{ marginRight: 8 }} />
                预警配置
              </span>
            ),
            children: (
              <Form
                form={form}
                layout="vertical"
                initialValues={{
                  basis_threshold: -1,
                  expand_multiplier: 1.1,
                  clear_interval_hours: 4,
                  blocked_coins: '',
                  sound_enabled: true,
                  popup_enabled: true,
                }}
              >
                <Space wrap size="middle">
                  <Form.Item
                    name="basis_threshold"
                    label="新机会基差阈值"
                    rules={[{ required: true, message: '请输入' }]}
                    style={{ width: 200 }}
                  >
                    <InputNumber style={{ width: '100%' }} step={0.1} />
                  </Form.Item>
                  <Form.Item
                    name="expand_multiplier"
                    label="基差扩大倍数"
                    rules={[{ required: true, message: '请输入' }]}
                    style={{ width: 200 }}
                  >
                    <InputNumber style={{ width: '100%' }} step={0.1} min={1} />
                  </Form.Item>
                  <Form.Item
                    name="clear_interval_hours"
                    label="清除预警周期/小时"
                    rules={[{ required: true, message: '请输入' }]}
                    style={{ width: 200 }}
                  >
                    <InputNumber style={{ width: '100%' }} min={1} />
                  </Form.Item>
                </Space>
                <Form.Item
                  name="blocked_coins"
                  label="长期不看的币种（逗号分隔，清除不会删）"
                  style={{ maxWidth: 620 }}
                >
                  <Input placeholder="如：DOGE,SHIB,PEPE" />
                </Form.Item>
                <Form.Item
                  name="temp_blocked_coins"
                  label="临时不看的币种（逗号分隔，清除会删）"
                  style={{ maxWidth: 620 }}
                >
                  <Input placeholder="如：SOL,BTC" />
                </Form.Item>
                <Space size="large">
                  <Form.Item name="sound_enabled" label="声音开关" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                  <Form.Item name="popup_enabled" label="弹窗开关" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                </Space>
                <Form.Item name="lark_bot_id" label="Lark机器人" style={{ maxWidth: 300 }}>
                  <Select
                    allowClear
                    placeholder="选择机器人（可选）"
                    options={bots.map((b) => ({ label: b.name, value: b.id }))}
                  />
                </Form.Item>
                <Button type="primary" icon={<SaveOutlined />} onClick={handleSave} loading={saving}>
                  保存配置
                </Button>
              </Form>
            ),
          },
        ]}
      />

      <Card title="预警历史" size="small">
        <Table
          columns={historyColumns}
          dataSource={history}
          rowKey="id"
          loading={historyLoading}
          size="small"
          pagination={{ pageSize: 20 }}
          scroll={{ x: 600 }}
        />
      </Card>
    </div>
  );
}
