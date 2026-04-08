import { Card, Result, Button, Tabs } from 'antd';
import s from '../../styles/page.module.css';
import {
  LockOutlined,
  SettingOutlined,
  MonitorOutlined,
  LineChartOutlined,
  RocketOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useAuth } from '../../hooks/useAuth';
import NotificationSettings from './NotificationSettings';
import PostInvestment from './PostInvestment';
import BasisAlert from './BasisAlert';
import NewListingAlert from './NewListingAlert';
import FundingBreakAlert from './FundingBreakAlert';

const tabItems = [
  {
    key: 'notification',
    label: (
      <span>
        <SettingOutlined />
        通知设置
      </span>
    ),
    children: <NotificationSettings />,
  },
  {
    key: 'newListing',
    label: (
      <span>
        <RocketOutlined />
        新上线币种
      </span>
    ),
    children: <NewListingAlert />,
  },
  {
    key: 'fundingBreak',
    label: (
      <span>
        <ThunderboltOutlined />
        资费突破
      </span>
    ),
    children: <FundingBreakAlert />,
  },
  {
    key: 'postInvestment',
    label: (
      <span>
        <MonitorOutlined />
        投后监测
      </span>
    ),
    children: <PostInvestment />,
  },
  {
    key: 'basisAlert',
    label: (
      <span>
        <LineChartOutlined />
        基差预警
      </span>
    ),
    children: <BasisAlert />,
  },
];

export default function AlertConfig() {
  const { isLoggedIn, requireAuth } = useAuth();

  if (!isLoggedIn) {
    return (
      <Card>
        <Result
          icon={<LockOutlined />}
          title="请先登录"
          subTitle="预警配置需要登录后才能使用"
          extra={
            <Button type="primary" onClick={() => requireAuth()}>
              登录
            </Button>
          }
        />
      </Card>
    );
  }

  return (
    <div className={s.page}>
      <Tabs defaultActiveKey="notification" items={tabItems} />
    </div>
  );
}
