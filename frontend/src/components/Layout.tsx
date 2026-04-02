import { useState } from 'react';
import { Layout as AntLayout, Button, Dropdown, Space, Tabs, Result } from 'antd';
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
    <AntLayout style={{ minHeight: '100vh' }}>
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 32px',
          position: 'sticky',
          top: 0,
          zIndex: 100,
          boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="logo" style={{ width: 32, height: 32 }} />
          <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
            <span style={{ color: '#fff', fontSize: 20, fontWeight: 700, letterSpacing: 1 }}>
              诸葛信号看板
            </span>
            <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: 10, fontStyle: 'italic', textAlign: 'right' }}>
              臣本散户，躬耕于K线，苟全仓位于乱市，但求套利于价差
            </span>
          </div>
        </div>
        <Space size={12}>
          <ThemeSwitch />
          {isLoggedIn ? (
            <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
              <Button type="text" icon={<UserOutlined />} style={{ color: '#fff' }}>
                {user?.username || '用户'}
              </Button>
            </Dropdown>
          ) : (
            <Space>
              <Button type="text" style={{ color: '#fff' }} onClick={openLoginModal}>
                登录
              </Button>
              <Button type="primary" ghost onClick={openRegisterModal}>
                注册
              </Button>
            </Space>
          )}
        </Space>
      </Header>
      <Content style={{ padding: '20px 32px', maxWidth: 1600, margin: '0 auto', width: '100%' }}>
        {isLoggedIn ? (
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={tabItems}
            type="card"
            size="large"
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
