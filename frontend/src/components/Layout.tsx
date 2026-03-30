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
import Unhedged from '../pages/Unhedged';
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
          padding: '0 24px',
        }}
      >
        <div style={{ color: '#fff', fontSize: 18, fontWeight: 600 }}>
          Arbitrage Dashboard
        </div>
        <Space>
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
      <Content style={{ padding: '16px 24px' }}>
        {isLoggedIn ? (
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={tabItems}
            type="card"
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
