import { useState } from 'react';
import { Layout as AntLayout, theme as antTheme } from 'antd';
import { useAuth } from '../hooks/useAuth';
import { useWebSocket } from '../hooks/useWebSocket';
import LoginModal from '../components/LoginModal';
import RegisterModal from '../components/RegisterModal';
import MobileTabBar from './components/MobileTabBar';
import MobileTopBar from './components/MobileTopBar';
import FundingRank from './pages/FundingRank';
import FundingBreak from './pages/FundingBreak';
import BasisMonitor from './pages/BasisMonitor';
import Me from './pages/Me';
import AlertConfig from './pages/AlertConfig';
import PriceTrend from './pages/PriceTrend';
import NewListing from './pages/NewListing';
import PremiumFilter from './pages/PremiumFilter';

const { Content } = AntLayout;

export type MobileRoute =
  | 'fundingRank' | 'fundingBreak' | 'basisMonitor' | 'me'
  | 'alertConfig' | 'priceTrend' | 'newListing' | 'premiumFilter';

const tabRoutes: MobileRoute[] = ['fundingRank', 'fundingBreak', 'basisMonitor', 'me'];

const titleMap: Record<MobileRoute, string> = {
  fundingRank: '资费排行',
  fundingBreak: '资费突破',
  basisMonitor: '基差监控',
  me: '我的',
  alertConfig: '预警配置',
  priceTrend: '价格趋势',
  newListing: '新上线',
  premiumFilter: '大额基差',
};

export default function MobileLayout() {
  const { isLoggedIn, token } = useAuth();
  const { token: tk } = antTheme.useToken();
  const [route, setRoute] = useState<MobileRoute>('fundingRank');
  const [history, setHistory] = useState<MobileRoute[]>([]);

  useWebSocket(token);

  const navigate = (next: MobileRoute) => {
    setHistory((h) => [...h, route]);
    setRoute(next);
  };

  const goBack = () => {
    setHistory((h) => {
      if (h.length === 0) return h;
      const prev = h[h.length - 1];
      setRoute(prev);
      return h.slice(0, -1);
    });
  };

  const goTab = (next: MobileRoute) => {
    setHistory([]);
    setRoute(next);
  };

  // 'me' requires login; if not logged in, route auto-redirects via Me page itself.
  const renderPage = () => {
    switch (route) {
      case 'fundingRank': return <FundingRank />;
      case 'fundingBreak': return <FundingBreak />;
      case 'basisMonitor': return <BasisMonitor />;
      case 'me': return <Me navigate={navigate} isLoggedIn={isLoggedIn} />;
      case 'alertConfig': return <AlertConfig />;
      case 'priceTrend': return <PriceTrend />;
      case 'newListing': return <NewListing />;
      case 'premiumFilter': return <PremiumFilter />;
    }
  };

  const isTabRoute = tabRoutes.includes(route);
  const showBack = !isTabRoute && history.length > 0;

  return (
    <AntLayout style={{ minHeight: '100vh', background: tk.colorBgLayout }}>
      <MobileTopBar title={titleMap[route]} showBack={showBack} onBack={goBack} />
      <Content
        style={{
          padding: '12px',
          paddingTop: 60,
          paddingBottom: 76,
          width: '100%',
        }}
      >
        {renderPage()}
      </Content>
      <MobileTabBar active={route} onChange={goTab} />
      <LoginModal />
      <RegisterModal />
    </AntLayout>
  );
}
