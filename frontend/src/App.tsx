import { ConfigProvider, theme as antTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useThemeStore } from './stores/themeStore';
import Layout from './components/Layout';
import 'nprogress/nprogress.css';
import './App.css';

function App() {
  const { theme } = useThemeStore();

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm:
          theme === 'dark' ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
      }}
    >
      <Layout />
    </ConfigProvider>
  );
}

export default App;
