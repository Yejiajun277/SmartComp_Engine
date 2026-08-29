import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  RedoOutlined,
} from '@ant-design/icons';

const STATUS_META = {
  waiting: { label: '等待接力', icon: <ClockCircleOutlined /> },
  running: { label: '正在分析', icon: <LoadingOutlined spin /> },
  completed: { label: '分析完成', icon: <CheckCircleOutlined /> },
  retrying: { label: '重试 / 降级处理', icon: <RedoOutlined spin /> },
  failed: { label: '执行失败', icon: <CloseCircleOutlined /> },
};

export default function AgentNode({ label, agent, status = 'waiting', timing, onClick }) {
  const meta = STATUS_META[status] || STATUS_META.waiting;

  const handleKeyDown = (event) => {
    if (!onClick || (event.key !== 'Enter' && event.key !== ' ')) return;
    event.preventDefault();
    onClick();
  };

  return (
    <article
      className="agent-node"
      data-status={status}
      aria-label={`${label}，${agent}，${meta.label}`}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className="agent-node-icon" aria-hidden="true">{meta.icon}</div>
      <div className="agent-node-copy">
        <strong>{label}</strong>
        <small>{agent}</small>
      </div>
      <div className="agent-node-state" data-status={status}>
        <span>{meta.label}</span>
        {timing && <small>{timing}</small>}
      </div>
    </article>
  );
}
