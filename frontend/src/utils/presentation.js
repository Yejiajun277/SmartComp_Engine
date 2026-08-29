import { formatProviderName } from './runtime.js';

const TASK_STATUS_META = {
  pending: { label: '等待中', tone: 'neutral' },
  queued: { label: '等待中', tone: 'neutral' },
  running: { label: '分析中', tone: 'running' },
  retrying: { label: '重新校验', tone: 'warning' },
  completed: { label: '已交付', tone: 'success' },
  degraded: { label: '降级交付', tone: 'warning' },
  failed: { label: '未完成', tone: 'danger' },
  cancelled: { label: '已取消', tone: 'neutral' },
};

export function getTaskStatusMeta(status) {
  return TASK_STATUS_META[status] || TASK_STATUS_META.pending;
}

export function getTaskModeMeta(task = {}) {
  const provider = formatProviderName(task?.llm_provider);
  const configuredModel = task?.llm_model
    ? [provider, task.llm_model].filter(Boolean).join(' · ')
    : provider;
  const executionLabel = task?.use_rule_engine === true
    ? '规则引擎分析'
    : task?.use_rule_engine === false
      ? configuredModel || '模型信息不可用（旧任务）'
      : '执行模式待同步';
  const qaLabel = task?.skip_qa === true
    ? '质量检查已关闭'
    : task?.skip_qa === false
      ? 'QualityAgent 已开启'
      : 'QA 状态待同步';

  return {
    executionLabel,
    qaLabel,
    qaTone: task?.skip_qa === true ? 'risk' : 'neutral',
  };
}

export function resolveTaskProgress(status, liveProgress = 0, persistedProgress = 0) {
  if (status === 'completed') return 100;

  const normalizedLive = Number.isFinite(Number(liveProgress)) ? Number(liveProgress) : 0;
  const normalizedPersisted = Number.isFinite(Number(persistedProgress))
    ? Number(persistedProgress)
    : 0;

  return Math.round(Math.min(1, Math.max(0, normalizedLive, normalizedPersisted)) * 100);
}

const TERMINAL_TASK_STATUSES = new Set([
  'completed',
  'failed',
  'cancelled',
  'degraded',
]);

export function resolveTaskStatus(liveStatus = 'pending', persistedStatus = 'pending') {
  if (TERMINAL_TASK_STATUSES.has(persistedStatus)) return persistedStatus;
  if (TERMINAL_TASK_STATUSES.has(liveStatus)) return liveStatus;
  if (liveStatus && liveStatus !== 'pending') return liveStatus;
  return persistedStatus || 'pending';
}

export function mergeTasks(serverTasks = [], recentTasks = []) {
  const recentById = new Map(
    recentTasks.filter(task => task?.id).map(task => [task.id, task]),
  );
  const serverIds = new Set();

  const authoritativeTasks = serverTasks
    .filter(task => task?.id)
    .map((task) => {
      serverIds.add(task.id);
      return { ...(recentById.get(task.id) || {}), ...task };
    });

  const localOnlyTasks = recentTasks
    .filter(task => task?.id && !serverIds.has(task.id))
    .map(task => ({ ...task }));

  return [...authoritativeTasks, ...localOnlyTasks];
}

export function formatElapsed(startedAt, finishedAt) {
  if (!startedAt) return '尚未开始';

  const started = new Date(startedAt).getTime();
  const finished = finishedAt ? new Date(finishedAt).getTime() : Date.now();
  if (!Number.isFinite(started) || !Number.isFinite(finished) || finished < started) {
    return '耗时待确认';
  }

  const totalSeconds = Math.max(0, Math.round((finished - started) / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) return `${hours}时${minutes}分`;
  if (minutes > 0) return `${minutes}分${seconds}秒`;
  return `${seconds}秒`;
}

function getEventSubject(event = {}) {
  return event.data?.target_agent
    || event.agent
    || event.phase
    || event.data?.phase
    || '当前环节';
}

export function getEventLabel(event = {}) {
  const subject = getEventSubject(event);
  const labels = {
    agent_started: `${subject} 开始工作`,
    agent_completed: `${subject} 已完成分析`,
    qa_check_started: `QualityAgent 正在检查 ${subject}`,
    qa_check_failed: `${subject} 未通过质检，等待修正`,
    qa_check_passed: `${subject} 已通过质检`,
    qa_retrying: `${subject} 正在根据质检意见重做`,
    task_completed: '策略报告已经生成',
    task_failed: '任务未完成，请查看异常信息',
  };

  return labels[event.type] || event.message || `${subject} 状态已更新`;
}
