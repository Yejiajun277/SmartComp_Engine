import { useCallback, useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Row, Col, Card, Tag, List, Typography, Button, Popconfirm, message } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { deleteTask, submitTask, getTasks } from '../api/client';
import TaskForm from '../components/TaskForm';

const { Title, Text } = Typography;

const STATUS_MAP = {
  pending: { color: 'default', text: '等待中' },
  running: { color: 'processing', text: '运行中' },
  completed: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
};

const RECENT_TASKS_KEY = 'smartcomp_recent_tasks';

function loadRecentTasks() {
  try {
    return JSON.parse(localStorage.getItem(RECENT_TASKS_KEY) || '[]');
  } catch {
    return [];
  }
}

function saveRecentTask(task) {
  const tasks = loadRecentTasks().filter(item => item.id !== task.id);
  localStorage.setItem(RECENT_TASKS_KEY, JSON.stringify([task, ...tasks].slice(0, 20)));
}

function removeRecentTask(taskId) {
  const tasks = loadRecentTasks().filter(item => item.id !== taskId);
  localStorage.setItem(RECENT_TASKS_KEY, JSON.stringify(tasks));
}

function mergeTasks(serverTasks, recentTasks) {
  const byId = new Map();
  recentTasks.forEach(task => byId.set(task.id, task));
  serverTasks.forEach(task => byId.set(task.id, { ...byId.get(task.id), ...task }));
  return Array.from(byId.values());
}

export default function Dashboard() {
  const navigate = useNavigate();
  const location = useLocation();
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const loadTasks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getTasks();
      setTasks(mergeTasks(data, loadRecentTasks()));
    } catch (err) {
      setTasks(loadRecentTasks());
      message.error('任务列表加载失败: ' + (err.response?.data?.detail || err.message));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTasks();
    const interval = setInterval(loadTasks, 5000);
    window.addEventListener('focus', loadTasks);
    return () => {
      clearInterval(interval);
      window.removeEventListener('focus', loadTasks);
    };
  }, [loadTasks, location.key]);

  const handleSubmit = async (values) => {
    setSubmitting(true);
    try {
      const result = await submitTask(
        values.productDescription,
        values.maxCompetitors,
        values.skipQa,
        values.useRuleEngine,
      );
      saveRecentTask({
        id: result.task_id,
        product_description: values.productDescription,
        max_competitors: values.maxCompetitors,
        status: 'pending',
        started_at: null,
        finished_at: null,
        error: null,
      });
      message.success('任务已提交');
      navigate(`/tasks/${result.task_id}`);
    } catch (err) {
      message.error('提交失败: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (taskId) => {
    try {
      await deleteTask(taskId);
      removeRecentTask(taskId);
      setTasks(prev => prev.filter(task => task.id !== taskId));
      message.success('任务已删除');
    } catch (err) {
      message.error('删除失败: ' + (err.response?.data?.detail || err.message));
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
              loading={loading}
              dataSource={tasks}
              locale={{ emptyText: '暂无任务，提交一个试试' }}
              renderItem={(task) => {
                const status = STATUS_MAP[task.status] || STATUS_MAP.pending;
                return (
                  <List.Item
                    style={{ cursor: 'pointer', padding: '12px 0' }}
                    onClick={() => navigate(`/tasks/${task.id}`)}
                    actions={[
                      <Popconfirm
                        key="delete"
                        title="删除任务"
                        description="确定删除这个分析任务吗？"
                        okText="删除"
                        cancelText="取消"
                        onConfirm={(event) => {
                          event?.stopPropagation?.();
                          handleDelete(task.id);
                        }}
                        onCancel={(event) => event?.stopPropagation?.()}
                      >
                        <Button
                          danger
                          type="text"
                          icon={<DeleteOutlined />}
                          onClick={(event) => event.stopPropagation()}
                        >
                          删除
                        </Button>
                      </Popconfirm>,
                    ]}
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
