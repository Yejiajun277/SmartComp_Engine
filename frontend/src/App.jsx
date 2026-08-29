import { BrowserRouter, NavLink, Routes, Route } from 'react-router-dom';
import { ConfigProvider, Layout, theme } from 'antd';
import Dashboard from './pages/Dashboard';
import TaskDetail from './pages/TaskDetail';
import ReportView from './pages/ReportView';
import BrandMark from './components/BrandMark';
import './App.css';

const { Header, Content } = Layout;

export default function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#176bff',
          colorInfo: '#176bff',
          colorSuccess: '#0aa886',
          colorWarning: '#d88915',
          colorError: '#e5484d',
          colorBgBase: '#f5f7f8',
          colorTextBase: '#111827',
          borderRadius: 12,
          fontFamily: "Inter, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
        },
      }}
    >
      <BrowserRouter>
        <Layout className="app-shell">
          <Header className="app-header">
            <NavLink className="brand-link" to="/" aria-label="返回 SmartComp 分析中心">
              <BrandMark />
            </NavLink>
            <nav className="primary-nav" aria-label="主导航">
              <NavLink to="/" end>分析中心</NavLink>
            </nav>
          </Header>
          <Content className="app-content">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/tasks/:taskId" element={<TaskDetail />} />
              <Route path="/tasks/:taskId/report" element={<ReportView />} />
            </Routes>
          </Content>
        </Layout>
      </BrowserRouter>
    </ConfigProvider>
  );
}
