import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Typography, Button, Spin, Empty, Space } from 'antd';
import { ArrowLeftOutlined, DownloadOutlined, FileTextOutlined } from '@ant-design/icons';
import { getReport } from '../api/client';

const { Title } = Typography;

export default function ReportView() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showJson, setShowJson] = useState(false);

  useEffect(() => {
    getReport(taskId)
      .then(setReport)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [taskId]);

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;
  if (!report) return <Empty description="报告不可用" />;

  const handleDownloadJson = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${report.product_name || 'report'}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/tasks/${taskId}`)}>
          返回详情
        </Button>
        <Space>
          <Button
            icon={<FileTextOutlined />}
            onClick={() => setShowJson(!showJson)}
          >
            {showJson ? '查看 HTML 报告' : '查看 JSON 数据'}
          </Button>
          <Button icon={<DownloadOutlined />} onClick={handleDownloadJson}>
            下载 JSON
          </Button>
        </Space>
      </div>

      <Title level={2}>{report.product_name} - 竞品分析报告</Title>

      {showJson ? (
        <Card>
          <pre style={{ whiteSpace: 'pre-wrap', maxHeight: '80vh', overflow: 'auto', fontSize: 13 }}>
            {JSON.stringify(report, null, 2)}
          </pre>
        </Card>
      ) : (
        <Card bodyStyle={{ padding: 0 }}>
          <iframe
            src={`/api/tasks/${taskId}/report.html`}
            title="竞品分析报告"
            style={{ width: '100%', height: '80vh', border: 'none' }}
          />
        </Card>
      )}
    </div>
  );
}
