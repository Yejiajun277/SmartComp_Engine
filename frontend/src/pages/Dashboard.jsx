import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Row, Col, Card, Tag, List, Typography, Spin, message } from 'antd';
import { submitTask, getTasks } from '../api/client';
import TaskForm from '../components/TaskForm';

const { Title, Text } = Typography;

const STATUS_MAP = {
  pending: { color: 'default', text: '等待中' },
  running: { color: 'processing', text: '运行中' },
  completed: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
};

export default function Dashboard() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    loadTasks();
    const interval = setInterval(loadTasks, 5000);
    return () => clearInterval(interval);
  }, []);

  const loadTasks = async () => {
    try {
      const data = await getTasks();
      setTasks(data);
    } catch {}
  };

  const handleSubmit = async (values) => {
    setSubmitting(true);
    try {
      const result = await submitTask(
        values.productDescription,
        values.maxCompetitors,
        values.skipQa,
        values.useRuleEngine,
      );
      message.success('任务已提交');
      navigate(`/tasks/${result.task_id}`);
    } catch (err) {
      message.error('提交失败: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Title level={2}>SmartComp Engine</Title>
      <Text type="secondary">AI 驱动的竞品分析 Agent 协作系统</Text>

      <Row gutter={24} style={{ marginTop: 24 }}>
        <Col xs={24} md={8}>
          <TaskForm onSubmit={handleSubmit} loading={submitting} />
        </Col>

        <Col xs={24} md={16}>
          <Card title="分析任务列表" style={{ height: '100%' }}>
            <List
              dataSource={tasks}
              locale={{ emptyText: '暂无任务，提交一个试试' }}
              renderItem={(task) => {
                const status = STATUS_MAP[task.status] || STATUS_MAP.pending;
                return (
                  <List.Item
                    style={{ cursor: 'pointer', padding: '12px 0' }}
                    onClick={() => navigate(`/tasks/${task.id}`)}
                  >
                    <List.Item.Meta
                      title={
                        <span>
                          {task.product_description}
                          <Tag color={status.color} style={{ marginLeft: 8 }}>
                            {status.text}
                          </Tag>
                        </span>
                      }
                      description={
                        <span>
                          竞品数: {task.max_competitors}
                          {task.started_at && (
                            <> | 开始: {new Date(task.started_at).toLocaleTimeString()}</>
                          )}
                          {task.finished_at && task.started_at && (
                            <> | 耗时: {Math.round((new Date(task.finished_at) - new Date(task.started_at)) / 1000)}s</>
                          )}
                          {task.error && <> | 错误: {task.error}</>}
                        </span>
                      }
                    />
                  </List.Item>
                );
              }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
