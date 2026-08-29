import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { getEventLabel } from '../../utils/presentation';

const IGNORED_EVENT_TYPES = new Set(['ping', 'pong', 'heartbeat']);

function getEventMeta(type = '') {
  if (type === 'task_failed' || type === 'agent_failed') {
    return { tone: 'danger', icon: <CloseCircleOutlined /> };
  }
  if (type === 'qa_check_failed' || type === 'qa_retrying') {
    return { tone: 'warning', icon: <WarningOutlined /> };
  }
  if (type.startsWith('qa_')) {
    return { tone: 'quality', icon: <SafetyCertificateOutlined /> };
  }
  if (type === 'task_completed' || type === 'agent_completed') {
    return { tone: 'success', icon: <CheckCircleOutlined /> };
  }
  if (type === 'agent_started' || type === 'task_started') {
    return { tone: 'running', icon: <LoadingOutlined spin /> };
  }
  return { tone: 'neutral', icon: <RobotOutlined /> };
}

function formatProgress(value) {
  if (!Number.isFinite(Number(value))) return null;
  const numeric = Number(value);
  return Math.round(numeric <= 1 ? numeric * 100 : numeric);
}

export default function LiveActivityRail({ events = [], currentMessage, connected }) {
  const recentEvents = events
    .filter(event => event && !IGNORED_EVENT_TYPES.has(event.type))
    .slice(-6)
    .reverse();

  return (
    <aside className="surface-card live-activity-rail" aria-labelledby="live-activity-title">
      <header className="activity-rail-header">
        <div>
          <span className="section-eyebrow">Live activity</span>
          <h2 id="live-activity-title">实时动态</h2>
        </div>
        <span className={`connection-state ${connected ? 'is-connected' : 'is-disconnected'}`}>
          <i aria-hidden="true" />
          {connected ? '实时连接' : '重连中'}
        </span>
      </header>

      <div className="activity-current-message">
        <span>当前动作</span>
        <p>{currentMessage || '等待 Agent 团队更新进度'}</p>
      </div>

      {!connected && (
        <p className="activity-connection-warning">
          实时连接中断，正在自动重连；已保存的任务状态仍可查看。
        </p>
      )}

      {recentEvents.length === 0 ? (
        <div className="activity-empty">
          <RobotOutlined />
          <p>等待 Agent 团队接管任务</p>
        </div>
      ) : (
        <ol className="activity-event-list">
          {recentEvents.map((event, index) => {
            const meta = getEventMeta(event.type);
            const progress = formatProgress(event.progress);
            return (
              <li className={`activity-event event-${meta.tone}`} key={`${event.type}-${event.timestamp || index}`}>
                <span className="activity-event-icon" aria-hidden="true">{meta.icon}</span>
                <div>
                  <p>{getEventLabel(event)}</p>
                  <small>{event.type?.replaceAll('_', ' ') || 'status update'}</small>
                </div>
                {progress != null && <strong>{progress}%</strong>}
              </li>
            );
          })}
        </ol>
      )}
    </aside>
  );
}
