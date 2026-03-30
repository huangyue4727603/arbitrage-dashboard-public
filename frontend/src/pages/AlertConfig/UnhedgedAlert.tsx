import { useState, useEffect, useCallback } from 'react';
import { Card, Form, Switch, Select, Button, Space, message, Spin } from 'antd';
import { SaveOutlined } from '@ant-design/icons';
import { getUnhedgedConfig, updateUnhedgedConfig, getLarkBots } from '../../api/alert';
import type { UnhedgedConfigForm, LarkBot } from '../../api/alert';

export default function UnhedgedAlert() {
  const [bots, setBots] = useState<LarkBot[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<UnhedgedConfigForm>();

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    try {
      const [config, botsData] = await Promise.all([getUnhedgedConfig(), getLarkBots()]);
      setBots(botsData);
      form.setFieldsValue({
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

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      await updateUnhedgedConfig(values);
      message.success('配置已保存');
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <Spin />
      </div>
    );
  }

  return (
    <Card title="非对冲预警配置" size="small">
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          sound_enabled: true,
          popup_enabled: true,
        }}
        style={{ maxWidth: 400 }}
      >
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
        <Form.Item>
          <Button type="primary" icon={<SaveOutlined />} onClick={handleSave} loading={saving}>
            保存配置
          </Button>
        </Form.Item>
      </Form>
    </Card>
  );
}
