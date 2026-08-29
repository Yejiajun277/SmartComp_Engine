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
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#55d9ff',
          colorInfo: '#55d9ff',
          colorSuccess: '#62e6b1',
          colorWarning: '#ffbd59',
          colorError: '#ff6b72',
          colorBgBase: '#050b14',
          colorTextBase: '#f4f8ff',
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
            <span className="mode-pill">
              <span className="mode-dot" aria-hidden="true" />
              教学 / 比赛模式
            </span>
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
