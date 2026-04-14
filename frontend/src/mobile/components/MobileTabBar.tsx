import { theme as antTheme } from 'antd';
import {
  BarChartOutlined,
  ThunderboltOutlined,
  LineChartOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { MobileRoute } from '../MobileLayout';

interface Props {
  active: MobileRoute;
  onChange: (r: MobileRoute) => void;
}

const tabs: { key: MobileRoute; label: string; icon: React.ReactNode }[] = [
  { key: 'fundingRank', label: '资费排行', icon: <BarChartOutlined /> },
  { key: 'fundingBreak', label: '资费突破', icon: <ThunderboltOutlined /> },
  { key: 'basisMonitor', label: '基差监控', icon: <LineChartOutlined /> },
  { key: 'me', label: '我的', icon: <UserOutlined /> },
];

export default function MobileTabBar({ active, onChange }: Props) {
  const { token } = antTheme.useToken();
  return (
    <div
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        background: token.colorBgContainer,
        borderTop: `1px solid ${token.colorBorderSecondary}`,
        display: 'flex',
        zIndex: 100,
        paddingBottom: 'env(safe-area-inset-bottom)',
      }}
    >
      {tabs.map((t) => {
        const isActive = active === t.key;
        return (
          <div
            key={t.key}
            onClick={() => onChange(t.key)}
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '8px 0 6px',
              gap: 2,
              color: isActive ? token.colorPrimary : token.colorTextTertiary,
              cursor: 'pointer',
            }}
          >
            <span style={{ fontSize: 22, lineHeight: 1 }}>{t.icon}</span>
            <span style={{ fontSize: 11, fontWeight: isActive ? 600 : 400 }}>{t.label}</span>
          </div>
        );
      })}
    </div>
  );
}
