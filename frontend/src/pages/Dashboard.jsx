import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { App as AntdApp, Button, List, Popconfirm } from 'antd';
import { ArrowRightOutlined, DeleteOutlined } from '@ant-design/icons';
import { deleteTask, getTasks, submitTask } from '../api/client';
import HomeHero from '../components/dashboard/HomeHero';
import TaskForm from '../components/TaskForm';
import { formatElapsed, getTaskStatusMeta, mergeTasks } from '../utils/presentation';
import { DEFAULT_MAX_COMPETITORS } from '../utils/taskCreation';

const RECENT_TASKS_KEY = 'smartcomp_recent_tasks';

const PROCESS_STEPS = [
  { title: '发现竞品', description: '界定真实竞争边界' },
  { title: '采集证据', description: '保留来源与查询链' },
  { title: '并行分析', description: '功能、定价、市场同步推进' },
  { title: 'QA 打回', description: '检查幻觉、完整性与覆盖率' },
  { title: '策略交付', description: '输出带引用的行动建议' },
];

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

function formatStartedAt(startedAt) {
  if (!startedAt) return '尚未开始';
  const value = new Date(startedAt);
  if (Number.isNaN(value.getTime())) return '开始时间待确认';
  return `开始于 ${value.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

export function TaskListItem({ task, status, onOpen, onDelete }) {
  return (
    <List.Item className="task-list-item">
      <div className="task-list-main">
        <div className="task-list-title-row">
          <span className={`status-pill status-${status.tone}`}>{status.label}</span>
          <strong>{task.product_description || '未命名分析'}</strong>
        </div>
        <div className="task-list-meta">
          <span>{task.max_competitors || DEFAULT_MAX_COMPETITORS} 个竞品</span>
          <span>{formatStartedAt(task.started_at)}</span>
          <span>{task.finished_at ? `总耗时 ${formatElapsed(task.started_at, task.finished_at)}` : '实时推进中'}</span>
        </div>
        {task.error && <p className="task-list-error">{task.error}</p>}
      </div>

      <div className="task-list-actions">
        <Button
          className="secondary-action"
          icon={<ArrowRightOutlined />}
          onClick={onOpen}
        >
          {task.status === 'completed' ? '查看结果' : '进入工作台'}
        </Button>
        <Popconfirm
          title="删除任务"
          description="删除后将无法从任务列表恢复。"
          okText="删除"
          cancelText="取消"
          onConfirm={() => onDelete(task.id)}
        >
          <Button
            className="task-delete-action"
            danger
            type="text"
            icon={<DeleteOutlined />}
            aria-label={`删除 ${task.product_description || '任务'}`}
            onClick={event => event.stopPropagation()}
          />
        </Popconfirm>
      </div>
    </List.Item>
  );
}

export default function Dashboard({ runtimeConfig, runtimeLoading }) {
  const navigate = useNavigate();
  const { message: messageApi } = AntdApp.useApp();
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [selectedExample, setSelectedExample] = useState('');

  const loadTasks = useCallback(async () => {
    try {
      const data = await getTasks();
      setTasks(mergeTasks(data, loadRecentTasks()));
    } catch (err) {
      setTasks(loadRecentTasks());
      messageApi.error(`任务列表加载失败：${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  }, [messageApi]);

  useEffect(() => {
    const initialLoad = window.setTimeout(loadTasks, 0);
    const interval = window.setInterval(loadTasks, 5000);
    window.addEventListener('focus', loadTasks);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(interval);
      window.removeEventListener('focus', loadTasks);
    };
  }, [loadTasks]);

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
      messageApi.success('Agent 团队已开始工作');
      navigate(`/tasks/${result.task_id}`);
    } catch (err) {
      messageApi.error(`提交失败：${err.response?.data?.detail || err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (taskId) => {
    try {
      await deleteTask(taskId);
      removeRecentTask(taskId);
      setTasks(previous => previous.filter(task => task.id !== taskId));
      messageApi.success('任务已删除');
    } catch (err) {
      messageApi.error(`删除失败：${err.response?.data?.detail || err.message}`);
    }
  };

  return (
    <main className="page-shell dashboard-page">
      <section className="dashboard-hero-grid">
        <HomeHero onExampleSelect={setSelectedExample} />
        <TaskForm
          initialProduct={selectedExample}
          onSubmit={handleSubmit}
          loading={submitting}
          runtimeConfig={runtimeConfig}
          runtimeLoading={runtimeLoading}
        />
      </section>

      <section className="process-proof" aria-label="分析工作流">
        {PROCESS_STEPS.map((step, index) => (
          <article className="process-step" key={step.title}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <strong>{step.title}</strong>
            <p>{step.description}</p>
          </article>
        ))}
      </section>

      <section className="surface-card recent-tasks" aria-labelledby="recent-task-heading">
        <header className="section-heading">
          <div>
            <span className="section-eyebrow">Recent missions</span>
            <h2 id="recent-task-heading">最近分析</h2>
          </div>
          <span>{tasks.length} 个任务</span>
        </header>
        <List
          className="task-list"
          loading={loading}
          dataSource={tasks}
          split={false}
          locale={{ emptyText: '还没有分析任务，从上方启动第一支 Agent 团队' }}
          renderItem={(task) => (
            <TaskListItem
              task={task}
              status={getTaskStatusMeta(task.status)}
              onOpen={() => navigate(`/tasks/${task.id}`)}
              onDelete={handleDelete}
            />
          )}
        />
      </section>
    </main>
  );
}
