import { useEffect } from 'react';
import { ConfigProvider, theme as antTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useThemeStore } from './stores/themeStore';
import Layout from './components/Layout';
import 'nprogress/nprogress.css';
import './App.css';

// Coinglass-inspired financial design tokens
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
    colorBgLayout: '#FFFFFF',
    colorBgContainer: '#FFFFFF',
    colorBgElevated: '#F5F5F5',
    colorBorder: '#D5D9DD',
    colorBorderSecondary: '#EAECEF',
    colorText: '#000000',
    colorTextSecondary: '#474D57',
    colorTextTertiary: '#929AA5',
    colorSuccess: '#16C784',
    colorError: '#EA3943',
    colorWarning: '#F0B90B',
    colorInfo: '#3861FB',
  },
};

function App() {
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
            '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
          fontSize: 13,
          borderRadius: 6,
          wireframe: false,
        },
        components: {
          Layout: {
            headerBg: isDark ? '#0E1217' : '#FFFFFF',
            headerHeight: 56,
            headerPadding: '0 24px',
            bodyBg: t.colorBgLayout,
          },
          Card: {
            borderRadiusLG: 8,
            paddingLG: 16,
            headerBg: 'transparent',
          },
          Table: {
            headerBg: isDark ? '#0F1318' : '#FAFBFC',
            headerColor: isDark ? '#8B919A' : '#58667E',
            headerSplitColor: 'transparent',
            rowHoverBg: isDark ? '#1A1F26' : '#F5F7FA',
            borderColor: isDark ? '#1A1F26' : '#F0F1F3',
            cellPaddingBlock: 10,
            cellPaddingInline: 12,
            cellFontSize: 13,
            headerBorderRadius: 0,
          },
          Tabs: {
            itemColor: isDark ? '#8B919A' : '#58667E',
            itemSelectedColor: isDark ? '#E6E8EA' : '#0B0E11',
            itemHoverColor: isDark ? '#E6E8EA' : '#0B0E11',
            inkBarColor: isDark ? '#5B7CFA' : '#3861FB',
            titleFontSize: 14,
            horizontalItemPadding: '12px 18px',
          },
          Button: {
            controlHeight: 32,
            borderRadius: 6,
            fontWeight: 500,
          },
          Input: { controlHeight: 32 },
          Select: { controlHeight: 32 },
          InputNumber: { controlHeight: 32 },
          DatePicker: { controlHeight: 32 },
          Modal: { borderRadiusLG: 10 },
          Tag: { borderRadiusSM: 4 },
        },
      }}
    >
      <Layout />
    </ConfigProvider>
  );
}

export default App;
