import { useEffect } from 'react';
import { ConfigProvider, theme as antTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useThemeStore } from '../stores/themeStore';
import MobileLayout from './MobileLayout';
import 'nprogress/nprogress.css';

const tokens = {
  dark: {
    colorPrimary: '#F0B90B',
    colorBgLayout: '#0B0E11',
    colorBgContainer: '#0B0E11',
    colorBgElevated: '#1A1F26',
    colorBorder: '#2A313C',
    colorBorderSecondary: '#1F252E',
    colorText: '#FFFFFF',
    colorTextSecondary: '#B7BDC6',
    colorTextTertiary: '#707A8A',
    colorSuccess: '#16C784',
    colorError: '#EA3943',
    colorWarning: '#F0B90B',
    colorInfo: '#5B7CFA',
  },
  light: {
    colorPrimary: '#C99400',
    colorBgLayout: '#F2F4F7',
    colorBgContainer: '#FFFFFF',
    colorBgElevated: '#EDEFF3',
    colorBorder: '#C8CDD4',
    colorBorderSecondary: '#DDE1E6',
    colorText: '#000000',
    colorTextSecondary: '#323842',
    colorTextTertiary: '#7A828E',
    colorSuccess: '#16C784',
    colorError: '#EA3943',
    colorWarning: '#F0B90B',
    colorInfo: '#3861FB',
  },
};

export default function MobileApp() {
  const { theme } = useThemeStore();
  const isDark = theme === 'dark';
  const t = isDark ? tokens.dark : tokens.light;

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    document.body.style.background = t.colorBgLayout;
    document.body.style.color = t.colorText;
  }, [theme, t]);

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: isDark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
        token: {
          ...t,
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "PingFang SC", sans-serif',
          fontSize: 14,
          borderRadius: 8,
        },
        components: {
          Button: { controlHeight: 40, borderRadius: 8, fontWeight: 500 },
          Input: { controlHeight: 40 },
          Select: { controlHeight: 40 },
          InputNumber: { controlHeight: 40 },
          DatePicker: { controlHeight: 40 },
        },
      }}
    >
      <MobileLayout />
    </ConfigProvider>
  );
}
