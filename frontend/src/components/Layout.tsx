import { useState } from 'react';
import { Layout as AntLayout, Button, Dropdown, Space, Tabs, Result, theme as antTheme } from 'antd';
import { useThemeStore } from '../stores/themeStore';
import { LockOutlined } from '@ant-design/icons';
import { UserOutlined, LogoutOutlined } from '@ant-design/icons';
import ThemeSwitch from './ThemeSwitch';
import LoginModal from './LoginModal';
import RegisterModal from './RegisterModal';
import { useAuth } from '../hooks/useAuth';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAuthStore } from '../stores/authStore';
import { authApi } from '../api/auth';

import FundingRank from '../pages/FundingRank';
import NewListing from '../pages/NewListing';
import FundingBreak from '../pages/FundingBreak';
import PriceTrend from '../pages/PriceTrend';
import BasisMonitor from '../pages/BasisMonitor';
import AlertConfig from '../pages/AlertConfig';
import PremiumFilter from '../pages/PremiumFilter';

const { Header, Content } = AntLayout;

const tabItems = [
  { key: 'fundingRank', label: '资费排行', children: <FundingRank /> },
  { key: 'newListing', label: '新上线', children: <NewListing /> },
  { key: 'fundingBreak', label: '资费突破', children: <FundingBreak /> },
  { key: 'priceTrend', label: '价格趋势', children: <PriceTrend /> },
  { key: 'premiumFilter', label: '大额基差', children: <PremiumFilter /> },
  { key: 'basisMonitor', label: '基差监控', children: <BasisMonitor /> },
  { key: 'alertConfig', label: '预警配置', children: <AlertConfig /> },
];

export default function Layout() {
  const { user, isLoggedIn, token } = useAuth();
  const { openLoginModal, openRegisterModal } = useAuthStore();
  const logout = useAuthStore((s) => s.logout);
  const [activeTab, setActiveTab] = useState('fundingRank');
  const { theme: themeMode } = useThemeStore();
  const isDark = themeMode === 'dark';
  const { token: tk } = antTheme.useToken();

  useWebSocket(token);

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } catch {
      // ignore
    }
    logout();
  };

  const userMenuItems = [
    {
      key: 'logout',
      label: '退出登录',
      icon: <LogoutOutlined />,
      onClick: handleLogout,
    },
  ];

  return (
    <AntLayout style={{ minHeight: '100vh', background: tk.colorBgLayout }}>
      <Header
        className="app-header"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 32px',
          height: 64,
          lineHeight: '64px',
          position: 'sticky',
          top: 0,
          zIndex: 100,
          background: isDark ? 'rgba(11,14,17,0.92)' : 'rgba(255,255,255,0.92)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
          <span
            className="brand-title"
            style={{
              fontSize: 24,
              fontWeight: 800,
              letterSpacing: 0.6,
              fontFamily: '"Playfair Display", "Cormorant Garamond", "Times New Roman", Georgia, serif',
              fontStyle: 'italic',
              background: isDark
                ? 'linear-gradient(135deg, #FFFFFF 0%, #F0B90B 50%, #FFFFFF 100%)'
                : 'linear-gradient(135deg, #1E2329 0%, #C99400 50%, #1E2329 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
              backgroundSize: '200% auto',
              animation: 'shimmer 6s linear infinite',
              lineHeight: 1.1,
            }}
          >
            Crypto Arbitrage
          </span>
          <div className="live-badge">
            <span className="live-dot" />
            <span className="live-text">LIVE</span>
          </div>
        </div>
        <Space size={10}>
          <ThemeSwitch />
          {isLoggedIn ? (
            <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
              <Button
                type="text"
                icon={<UserOutlined />}
                style={{ fontWeight: 500, height: 36, padding: '0 12px' }}
              >
                {user?.username || '用户'}
              </Button>
            </Dropdown>
          ) : (
            <Space size={6}>
              <Button type="text" onClick={openLoginModal} style={{ height: 36 }}>登录</Button>
              <Button type="primary" onClick={openRegisterModal} style={{ height: 36, fontWeight: 600 }}>
                注册
              </Button>
            </Space>
          )}
        </Space>
      </Header>
      <Content style={{ padding: '0 24px 20px', maxWidth: 1600, margin: '0 auto', width: '100%' }}>
        {isLoggedIn ? (
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={tabItems}
            size="middle"
          />
        ) : (
          <Result
            icon={<LockOutlined />}
            title="请先登录"
            subTitle="本站需要注册登录后才能使用"
            extra={
              <Space>
                <Button type="primary" onClick={openLoginModal}>登录</Button>
                <Button onClick={openRegisterModal}>注册</Button>
              </Space>
            }
          />
        )}
      </Content>
      <LoginModal />
      <RegisterModal />
    </AntLayout>
  );
}
