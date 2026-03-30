import { useState, useEffect, useCallback } from 'react';
import { Card, Switch, Space, Typography, Divider, message, Spin } from 'antd';
import { SoundOutlined, NotificationOutlined } from '@ant-design/icons';
import { updateNotification } from '../../api/alert';
import type { NotificationSettings as NotificationSettingsType } from '../../api/alert';
import LarkBotManager from './LarkBotManager';
import client from '../../api/client';

const { Text } = Typography;

export default function NotificationSettings() {
  const [settings, setSettings] = useState<NotificationSettingsType>({
    sound_enabled: true,
    popup_enabled: true,
  });
  const [loading, setLoading] = useState(true);

  const fetchSettings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await client.get<NotificationSettingsType>('/api/settings/notification');
      setSettings(res.data);
    } catch {
      // Use defaults if API fails
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const handleToggle = async (field: keyof NotificationSettingsType, checked: boolean) => {
    const newSettings = { ...settings, [field]: checked };
    setSettings(newSettings);
    try {
      await updateNotification(newSettings);
      message.success('设置已保存');
    } catch {
      setSettings(settings);
      message.error('保存失败');
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
    <div>
      <Card title="全局通知设置" size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <SoundOutlined />
              <Text>声音通知</Text>
            </Space>
            <Switch
              checked={settings.sound_enabled}
              onChange={(checked) => handleToggle('sound_enabled', checked)}
            />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <NotificationOutlined />
              <Text>弹窗通知</Text>
            </Space>
            <Switch
              checked={settings.popup_enabled}
              onChange={(checked) => handleToggle('popup_enabled', checked)}
            />
          </div>
        </Space>
      </Card>

      <Divider />

      <Card size="small">
        <LarkBotManager />
      </Card>
    </div>
  );
}
