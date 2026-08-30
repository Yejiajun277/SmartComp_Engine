import { useEffect, useState } from 'react';
import { BrowserRouter, NavLink, Routes, Route } from 'react-router-dom';
import { App as AntdApp, ConfigProvider, Layout, theme } from 'antd';
import { getRuntimeConfig } from './api/client';
import Dashboard from './pages/Dashboard';
import TaskDetail from './pages/TaskDetail';
import ReportView from './pages/ReportView';
import BrandMark from './components/BrandMark';
import RuntimeStatus from './components/RuntimeStatus';
import ThemeToggle from './components/ThemeToggle';
import {
  getAppThemeStorage,
  getNextAppTheme,
  readStoredAppTheme,
  resolveAppTheme,
  writeStoredAppTheme,
  applyAppTheme,
} from './utils/appTheme';
import './App.css';

const { Header, Content } = Layout;

export default function App() {
  const [runtimeConfig, setRuntimeConfig] = useState(null);
  const [runtimeLoading, setRuntimeLoading] = useState(true);
  const [appTheme, setAppTheme] = useState(() => {
    const storage = getAppThemeStorage(typeof window === 'undefined' ? null : window);
    const storedTheme = readStoredAppTheme(storage);
    const systemPrefersDark = typeof window !== 'undefined'
      && typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-color-scheme: dark)').matches;
    return resolveAppTheme(storedTheme, systemPrefersDark);
  });

  useEffect(() => {
    let active = true;

    getRuntimeConfig()
      .then((config) => {
        if (active) setRuntimeConfig(config);
      })
      .catch(() => {
        if (active) setRuntimeConfig(null);
      })
      .finally(() => {
        if (active) setRuntimeLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (typeof document !== 'undefined') applyAppTheme(document.documentElement, appTheme);
  }, [appTheme]);

  const handleThemeToggle = () => {
    setAppTheme((current) => {
      const next = getNextAppTheme(current);
      const storage = getAppThemeStorage(typeof window === 'undefined' ? null : window);
      writeStoredAppTheme(storage, next);
      return next;
    });
  };

  return (
    <ConfigProvider
      theme={{
        algorithm: appTheme === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          colorPrimary: '#176bff',
          colorInfo: '#176bff',
          colorSuccess: appTheme === 'dark' ? '#37d5ad' : '#0aa886',
          colorWarning: appTheme === 'dark' ? '#f4b14a' : '#d88915',
          colorError: appTheme === 'dark' ? '#ff7380' : '#e5484d',
          colorBgBase: appTheme === 'dark' ? '#07111d' : '#f5f7f8',
          colorTextBase: appTheme === 'dark' ? '#eef4fb' : '#111827',
          borderRadius: 12,
          fontFamily: "Inter, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
        },
      }}
    >
      <AntdApp component={false}>
        <BrowserRouter>
        <Layout className="app-shell" data-theme={appTheme}>
          <Header className="app-header">
            <NavLink className="brand-link" to="/" aria-label="返回 SmartComp 分析中心">
              <BrandMark />
            </NavLink>
            <nav className="primary-nav" aria-label="主导航">
              <NavLink to="/" end>分析中心</NavLink>
            </nav>
            <div className="app-header-actions">
              <RuntimeStatus config={runtimeConfig} compact loading={runtimeLoading} />
              <ThemeToggle appTheme={appTheme} onToggle={handleThemeToggle} />
            </div>
          </Header>
          <Content className="app-content">
            <Routes>
              <Route
                path="/"
                element={(
                  <Dashboard
                    runtimeConfig={runtimeConfig}
                    runtimeLoading={runtimeLoading}
                  />
                )}
              />
              <Route path="/tasks/:taskId" element={<TaskDetail />} />
              <Route path="/tasks/:taskId/report" element={<ReportView />} />
            </Routes>
          </Content>
        </Layout>
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
}
