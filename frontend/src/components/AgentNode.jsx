import { Tag } from 'antd';
import {
  ClockCircleOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  LoadingOutlined,
} from '@ant-design/icons';

const STATUS_STYLES = {
  waiting: {
    label: '未开始',
    bg: '#f7f7f7',
    border: '#d9d9d9',
    icon: <ClockCircleOutlined />,
    color: '#8c8c8c',
    tagColor: 'default',
  },
  running: {
    label: '执行中',
    bg: '#e6f7ff',
    border: '#1890ff',
    icon: <LoadingOutlined spin />,
    color: '#1890ff',
    tagColor: 'processing',
  },
  completed: {
    label: '已完成',
    bg: '#f6ffed',
    border: '#52c41a',
    icon: <CheckCircleOutlined />,
    color: '#52c41a',
    tagColor: 'success',
  },
  retrying: {
    label: '执行中',
    bg: '#e6f7ff',
    border: '#1890ff',
    icon: <LoadingOutlined spin />,
    color: '#1890ff',
    tagColor: 'processing',
  },
  failed: {
    label: '失败',
    bg: '#fff2f0',
    border: '#ff4d4f',
    icon: <ExclamationCircleOutlined />,
    color: '#ff4d4f',
    tagColor: 'error',
  },
};

const QA_TAG_COLOR = {
  passed: 'success',
  failed: 'error',
  degraded: 'warning',
  running: 'processing',
  none: 'default',
};

export default function AgentNode({ label, agent, status = 'waiting', timing, qaStatus, onClick }) {
  const s = STATUS_STYLES[status] || STATUS_STYLES.waiting;
  const qaLabel = qaStatus?.label;
  const qaColor = QA_TAG_COLOR[qaStatus?.status || 'none'] || 'default';

  return (
    <div
      onClick={onClick}
      style={{
        background: s.bg,
        border: `2px solid ${s.border}`,
        borderRadius: 12,
        padding: '12px 16px',
        cursor: onClick ? 'pointer' : 'default',
        textAlign: 'center',
        minWidth: 120,
        transition: 'all 0.3s',
        boxShadow: status === 'running' ? `0 0 12px ${s.border}40` : 'none',
      }}
    >
      <div style={{ fontSize: 20, marginBottom: 4, color: s.color }}>{s.icon}</div>
      <div style={{ fontWeight: 600, fontSize: 14 }}>{label}</div>
      <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{agent}</div>
      <div style={{ marginTop: 8 }}>
        <Tag color={s.tagColor} style={{ marginInlineEnd: 0 }}>
          状态：{s.label}
        </Tag>
      </div>
      {qaLabel && (
        <div style={{ marginTop: 8 }}>
          <Tag color={qaColor} style={{ marginInlineEnd: 0 }}>
            QA：{qaLabel}
          </Tag>
        </div>
      )}
      {timing && <div style={{ fontSize: 11, color: '#aaa', marginTop: 4 }}>{timing}</div>}
    </div>
  );
}
