import { useEffect, useState, useCallback } from 'react';
import { Tabs, Tag, Drawer, Button, InputNumber, Input, Popconfirm, message, theme as antTheme } from 'antd';
import { SettingOutlined, ClearOutlined } from '@ant-design/icons';
import { basisMonitorApi, type BasisRecord, type TimelineEvent, type BasisConfig } from '../../api/basisMonitor';
import { useWsStore } from '../../stores/wsStore';
import { useAuthStore } from '../../stores/authStore';

export default function MobileBasisMonitor() {
  const { token } = antTheme.useToken();
  const [records, setRecords] = useState<BasisRecord[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [config, setConfig] = useState<BasisConfig>({ basis_threshold: -1, expand_multiplier: 1.1, blocked_coins: '', temp_blocked_coins: '' });
  const [editThreshold, setEditThreshold] = useState(-1);
  const [editMultiplier, setEditMultiplier] = useState(1.1);
  const [editBlocked, setEditBlocked] = useState('');
  const [editTempBlocked, setEditTempBlocked] = useState('');
  const [configOpen, setConfigOpen] = useState(false);
  const wsData = useWsStore((s) => s.basisMonitor);
  const isLoggedIn = useAuthStore((s) => !!s.token);

  const fetchData = useCallback(async () => {
    try {
      const data = await basisMonitorApi.getData();
      setRecords(data.records);
      setTimeline(data.timeline);
    } catch { /* ignore */ }
  }, []);

  const fetchConfig = useCallback(async () => {
    try {
      const cfg = await basisMonitorApi.getConfig();
      setConfig(cfg);
      setEditThreshold(cfg.basis_threshold);
      setEditMultiplier(cfg.expand_multiplier);
      setEditBlocked(cfg.blocked_coins || '');
      setEditTempBlocked(cfg.temp_blocked_coins || '');
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    fetchData();
    fetchConfig();
    const t = setInterval(fetchData, 5000);
    return () => clearInterval(t);
  }, [fetchData, fetchConfig]);

  useEffect(() => {
    if (wsData) fetchData();
  }, [wsData, fetchData]);

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
      fetchData();
    } catch {
      message.error('保存失败');
    }
  };

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

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, gap: 8 }}>
        <span style={{ fontSize: 12, color: token.colorTextTertiary }}>
          阈值 {config.basis_threshold}% · 倍数 {config.expand_multiplier}x
        </span>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button size="small" icon={<SettingOutlined />} onClick={() => setConfigOpen(true)}>配置</Button>
          <Popconfirm title="确认清除全部?" onConfirm={handleClear}>
            <Button size="small" danger icon={<ClearOutlined />}>清除</Button>
          </Popconfirm>
        </div>
      </div>

    <Tabs
      defaultActiveKey="alerts"
      items={[
        {
          key: 'alerts',
          label: `预警 (${records.length})`,
          children: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {records.map((r) => (
                <div key={r.coin_name} style={{ background: token.colorBgContainer, border: `1px solid ${token.colorBorderSecondary}`, borderRadius: 10, padding: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
                    <span style={{ fontSize: 16, fontWeight: 700, color: token.colorText }}>{r.coin_name}</span>
                    <Tag color={r.alert_count > 3 ? 'red' : r.alert_count > 1 ? 'orange' : 'blue'}>{r.alert_count}次</Tag>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, fontSize: 12 }}>
                    <Stat label="实时基差" value={renderBasis(r.current_basis, token)} />
                    <Stat label="最大基差" value={renderBasis(r.min_basis, token)} />
                    <Stat label="1D 涨幅" value={renderPct(r.change_1d, token)} />
                    <Stat label="最近预警" value={<span style={{ color: token.colorTextSecondary, fontSize: 11 }}>{r.last_alert_at?.slice(5) || '—'}</span>} />
                  </div>
                </div>
              ))}
              {records.length === 0 && (
                <div style={{ textAlign: 'center', padding: 40, color: token.colorTextTertiary }}>暂无预警</div>
              )}
            </div>
          ),
        },
        {
          key: 'timeline',
          label: `动态 (${timeline.length})`,
          children: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {timeline.map((e, i) => (
                <div key={i} style={{ background: token.colorBgContainer, border: `1px solid ${token.colorBorderSecondary}`, borderRadius: 10, padding: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontWeight: 600, color: token.colorText }}>{e.coin_name}</span>
                    <Tag color={e.alert_type === '新机会' ? 'green' : 'red'} style={{ fontSize: 11 }}>{e.alert_type}</Tag>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                    <span style={{ color: token.colorTextTertiary }}>{e.time}</span>
                    <span style={{ color: token.colorError, fontWeight: 600 }}>{e.basis.toFixed(4)}%</span>
                  </div>
                </div>
              ))}
              {timeline.length === 0 && (
                <div style={{ textAlign: 'center', padding: 40, color: token.colorTextTertiary }}>暂无动态</div>
              )}
            </div>
          ),
        },
      ]}
    />

      <Drawer
        open={configOpen}
        onClose={() => setConfigOpen(false)}
        placement="bottom"
        height="auto"
        title="预警配置"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Field label="基差阈值 (%)">
            <InputNumber value={editThreshold} onChange={(v) => v !== null && setEditThreshold(v)} step={0.5} style={{ width: '100%' }} />
          </Field>
          <Field label="扩大倍数">
            <InputNumber value={editMultiplier} onChange={(v) => v !== null && setEditMultiplier(v)} step={0.1} min={1.01} style={{ width: '100%' }} />
          </Field>
          <Field label="长期不看（清除不会删）">
            <Input value={editBlocked} onChange={(e) => setEditBlocked(e.target.value)} placeholder="如: BTC,ETH" />
          </Field>
          <Field label="临时不看（清除会删）">
            <Input value={editTempBlocked} onChange={(e) => setEditTempBlocked(e.target.value)} placeholder="如: SOL,DOGE" />
          </Field>
          <Button type="primary" block onClick={handleSaveConfig}>
            {isLoggedIn ? '保存' : '请先登录'}
          </Button>
        </div>
      </Drawer>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  const { token } = antTheme.useToken();
  return (
    <div>
      <div style={{ fontSize: 12, color: token.colorTextSecondary, marginBottom: 6 }}>{label}</div>
      {children}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  const { token } = antTheme.useToken();
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
      <span style={{ color: token.colorTextTertiary }}>{label}</span>
      <span>{value}</span>
    </div>
  );
}

function renderBasis(val: number | null | undefined, token: any) {
  if (val === null || val === undefined) return <span style={{ color: token.colorTextTertiary }}>—</span>;
  const color = val < -1 ? token.colorError : val < 0 ? token.colorWarning : token.colorSuccess;
  return <span style={{ color, fontWeight: 600 }}>{val.toFixed(4)}%</span>;
}

function renderPct(val: number | null | undefined, token: any) {
  if (val === null || val === undefined) return <span style={{ color: token.colorTextTertiary }}>—</span>;
  const color = val > 0 ? token.colorSuccess : val < 0 ? token.colorError : undefined;
  return <span style={{ color }}>{val >= 0 ? '+' : ''}{val.toFixed(2)}%</span>;
}
