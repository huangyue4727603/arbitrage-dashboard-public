import { Button } from 'antd';
import { SunOutlined, MoonOutlined } from '@ant-design/icons';
import { useThemeStore } from '../stores/themeStore';

export default function ThemeSwitch() {
  const { theme, toggleTheme } = useThemeStore();

  return (
    <Button
      type="text"
      icon={theme === 'light' ? <MoonOutlined /> : <SunOutlined />}
      onClick={toggleTheme}
      style={{ color: 'inherit' }}
    />
  );
}
