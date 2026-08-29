import {
  ApiOutlined,
  CheckCircleOutlined,
  GlobalOutlined,
  LoadingOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { getRuntimeStatusMeta } from '../utils/runtime';

function getStatusIcon(state, loading) {
  if (loading) return <LoadingOutlined spin />;
  if (state === 'model') return <CheckCircleOutlined />;
  if (state === 'rule') return <WarningOutlined />;
  return <ApiOutlined />;
}

export default function RuntimeStatus({ config, compact = false, loading = false }) {
  const meta = getRuntimeStatusMeta(config);
  const title = loading ? '正在读取运行配置' : meta.title;
  const compactLabel = loading ? '正在确认运行模式' : meta.compactLabel;
  const detail = loading ? '正在从本机服务读取模型与搜索配置' : meta.detail;

  if (compact) {
    return (
      <div
        className="runtime-status-compact"
        data-tone={loading ? 'neutral' : meta.tone}
        role="status"
        aria-live="polite"
        title={`${title}；${meta.searchLabel}`}
      >
        <span className="runtime-status-dot" aria-hidden="true" />
        <span className="runtime-status-copy">
          <small>运行模式</small>
          <strong>{compactLabel}</strong>
        </span>
      </div>
    );
  }

  return (
    <section
      className="runtime-status-panel"
      data-tone={loading ? 'neutral' : meta.tone}
      role="status"
      aria-live="polite"
    >
      <header>
        <span className="runtime-status-icon" aria-hidden="true">
          {getStatusIcon(meta.state, loading)}
        </span>
        <span>
          <small>Execution mode</small>
          <strong>{title}</strong>
        </span>
      </header>
      <p>{detail}</p>
      <div className="runtime-status-tags">
        <span><ApiOutlined /> 执行 · {loading ? '待确认' : meta.executionLabel}</span>
        <span data-warning={!loading && meta.searchConfigured === false ? 'true' : 'false'}>
          <GlobalOutlined /> {loading ? '联网搜索状态待确认' : meta.searchLabel}
        </span>
      </div>
    </section>
  );
}
