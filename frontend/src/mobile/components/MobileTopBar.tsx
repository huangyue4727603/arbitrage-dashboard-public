import { theme as antTheme } from 'antd';
import { LeftOutlined } from '@ant-design/icons';

interface Props {
  title: string;
  showBack?: boolean;
  onBack?: () => void;
}

export default function MobileTopBar({ title, showBack, onBack }: Props) {
  const { token } = antTheme.useToken();
  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        height: 48,
        background: token.colorBgContainer,
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
        paddingLeft: 'env(safe-area-inset-left)',
        paddingRight: 'env(safe-area-inset-right)',
      }}
    >
      {showBack && (
        <div
          onClick={onBack}
          style={{
            position: 'absolute',
            left: 8,
            top: 0,
            height: 48,
            width: 48,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: token.colorText,
            fontSize: 18,
            cursor: 'pointer',
          }}
        >
          <LeftOutlined />
        </div>
      )}
      <span style={{ fontSize: 16, fontWeight: 600, color: token.colorText }}>{title}</span>
    </div>
  );
}
