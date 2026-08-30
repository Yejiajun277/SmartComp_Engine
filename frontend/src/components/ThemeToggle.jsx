import { MoonOutlined, SunOutlined } from '@ant-design/icons';

export default function ThemeToggle({ appTheme, onToggle }) {
  const dark = appTheme === 'dark';
  const nextAction = dark ? '切换到浅色模式' : '切换到深色模式';
  return (
    <button
      type="button"
      className="app-theme-toggle"
      aria-pressed={dark}
      aria-label={nextAction}
      title={nextAction}
      onClick={onToggle}
    >
      {dark ? <SunOutlined aria-hidden="true" /> : <MoonOutlined aria-hidden="true" />}
      <span>{dark ? '浅色模式' : '深色模式'}</span>
    </button>
  );
}
