import { useEffect, useState } from 'react';
import { Button, message, theme as antTheme } from 'antd';
import {
  WarningOutlined,
  StockOutlined,
  PlusCircleOutlined,
  AimOutlined,
  CalculatorOutlined,
  BulbOutlined,
  LogoutOutlined,
  RightOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useAuthStore } from '../../stores/authStore';
import { useThemeStore } from '../../stores/themeStore';
import { useAuth } from '../../hooks/useAuth';
import { authApi } from '../../api/auth';
import Calculator from '../../pages/FundingRank/Calculator';
import type { MobileRoute } from '../MobileLayout';

interface Props {
  navigate: (r: MobileRoute) => void;
  isLoggedIn: boolean;
}

export default function Me({ navigate, isLoggedIn }: Props) {
  const { token } = antTheme.useToken();
  const { user } = useAuth();
  const openLoginModal = useAuthStore((s) => s.openLoginModal);
  const logout = useAuthStore((s) => s.logout);
  const { theme, toggleTheme } = useThemeStore();
  const [calcOpen, setCalcOpen] = useState(false);

  // Auto-prompt login if not authenticated
  useEffect(() => {
    if (!isLoggedIn) openLoginModal();
  }, [isLoggedIn, openLoginModal]);

  if (!isLoggedIn) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <UserOutlined style={{ fontSize: 48, color: token.colorTextTertiary }} />
        <div style={{ marginTop: 16, color: token.colorTextSecondary }}>请先登录</div>
        <Button type="primary" style={{ marginTop: 20 }} onClick={openLoginModal}>登录</Button>
      </div>
    );
  }

  const handleLogout = async () => {
    try { await authApi.logout(); } catch { /* ignore */ }
    logout();
    message.success('已退出');
  };

  const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div style={{ marginTop: 16 }}>
      <div style={{ fontSize: 12, color: token.colorTextTertiary, padding: '0 12px 6px' }}>{title}</div>
      <div style={{ background: token.colorBgContainer, borderRadius: 10, overflow: 'hidden', border: `1px solid ${token.colorBorderSecondary}` }}>
        {children}
      </div>
    </div>
  );

  const Item = ({
    icon, label, onClick, right,
  }: { icon: React.ReactNode; label: string; onClick?: () => void; right?: React.ReactNode }) => (
    <div
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '14px 14px',
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
        cursor: 'pointer',
        gap: 12,
      }}
    >
      <span style={{ fontSize: 18, color: token.colorPrimary, width: 22, display: 'inline-flex', justifyContent: 'center' }}>{icon}</span>
      <span style={{ flex: 1, fontSize: 15, color: token.colorText }}>{label}</span>
      {right ?? <RightOutlined style={{ fontSize: 12, color: token.colorTextTertiary }} />}
    </div>
  );

  return (
    <div>
      {/* User card */}
      <div
        style={{
          background: token.colorBgContainer,
          borderRadius: 10,
          padding: '20px 16px',
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          border: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        <div
          style={{
            width: 52,
            height: 52,
            borderRadius: '50%',
            background: token.colorPrimary,
            color: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 24,
            fontWeight: 700,
          }}
        >
          {user?.username?.[0]?.toUpperCase() || 'U'}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 17, fontWeight: 600, color: token.colorText }}>{user?.username || '用户'}</div>
          <div style={{ fontSize: 12, color: token.colorTextTertiary, marginTop: 2 }}>已登录</div>
        </div>
      </div>

      <Section title="功能">
        <Item icon={<WarningOutlined />} label="预警配置" onClick={() => navigate('alertConfig')} />
        <Item icon={<StockOutlined />} label="价格趋势" onClick={() => navigate('priceTrend')} />
        <Item icon={<PlusCircleOutlined />} label="新上线列表" onClick={() => navigate('newListing')} />
        <Item icon={<AimOutlined />} label="大额基差" onClick={() => navigate('premiumFilter')} />
      </Section>

      <Section title="工具">
        <Item icon={<CalculatorOutlined />} label="资费计算器" onClick={() => setCalcOpen(true)} />
        <Item
          icon={<BulbOutlined />}
          label="深色模式"
          onClick={toggleTheme}
          right={<span style={{ fontSize: 13, color: token.colorTextTertiary }}>{theme === 'dark' ? '已开启' : '已关闭'}</span>}
        />
      </Section>

      <Section title="账户">
        <Item icon={<LogoutOutlined />} label="退出登录" onClick={handleLogout} right={<span />} />
      </Section>

      <Calculator open={calcOpen} onClose={() => setCalcOpen(false)} />
    </div>
  );
}
