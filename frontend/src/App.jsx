import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout, Typography } from 'antd';
import Dashboard from './pages/Dashboard';
import TaskDetail from './pages/TaskDetail';
import ReportView from './pages/ReportView';

const { Header, Content } = Layout;
const { Text } = Typography;

export default function App() {
  return (
    <BrowserRouter>
      <Layout style={{ minHeight: '100vh' }}>
        <Header style={{
          background: '#001529',
          display: 'flex',
          alignItems: 'center',
          padding: '0 24px',
        }}>
          <Text style={{ color: '#fff', fontSize: 18, fontWeight: 700 }}>
            SmartComp Engine
          </Text>
        </Header>
        <Content style={{ background: '#f0f2f5' }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/tasks/:taskId" element={<TaskDetail />} />
            <Route path="/tasks/:taskId/report" element={<ReportView />} />
          </Routes>
        </Content>
      </Layout>
    </BrowserRouter>
  );
}
