import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { getQaResultState } from '../utils/taskEvents';

const PHASE_LABELS = {
  collection: '证据采集',
  product: '功能分析',
  pricing: '定价分析',
  market: '市场分析',
  strategy: '策略报告',
};

function getStatusMeta(result) {
  if (result.technical_error === true) {
    return { label: '执行错误', tone: 'failed', icon: <CloseCircleOutlined /> };
  }
  const state = getQaResultState(result);
  if (state === 'running') {
    return { label: '质检中', tone: 'running', icon: <LoadingOutlined spin /> };
  }
  if (state === 'degraded') {
    return { label: '降级通过', tone: 'degraded', icon: <WarningOutlined /> };
  }
  if (state === 'passed') {
    return { label: '通过', tone: 'passed', icon: <CheckCircleOutlined /> };
  }
  return { label: '已打回', tone: 'failed', icon: <CloseCircleOutlined /> };
}

function getIssueText(issue) {
  if (!issue) return '';
  const field = issue.field ? `${issue.field}：` : '';
  return `${field}${issue.description || issue.suggestion || issue.category || '待修正问题'}`;
}

function trimText(text, limit = 140) {
  if (!text) return '';
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function groupResults(results) {
  const groups = new Map();

  results.forEach((result, index) => {
    const key = result.target_agent || result.phase || 'QualityAgent';
    const current = groups.get(key) || [];
    current.push({ ...result, sourceIndex: index });
    groups.set(key, current);
  });

  return Array.from(groups, ([key, entries]) => ({ key, entries }));
}

function getCorrectionStory(result, attempt) {
  if (result.technical_error === true) return `第 ${attempt} 轮质量检查执行中断`;
  const state = getQaResultState(result);
  if (state === 'running') return `第 ${attempt} 轮质量检查正在进行`;
  if (state === 'degraded') return `第 ${attempt} 轮保留风险后降级通过`;
  if (state === 'passed') return `第 ${attempt} 轮检查通过，可以进入下一阶段`;
  return `发现问题 → 已反馈给 ${result.target_agent || '对应 Agent'} → 第 ${attempt} 轮修正`;
}

export default function QATimeline({ results = [] }) {
  if (results.length === 0) {
    return (
      <div className="qa-timeline-empty">
        <SafetyCertificateOutlined />
        <p>暂无质检记录，QualityAgent 将在关键阶段开始检查。</p>
      </div>
    );
  }

  return (
    <div className="qa-correction-groups">
      {groupResults(results).map(group => (
        <section className="qa-correction-group" key={group.key}>
          <header>
            <div>
              <strong>{group.key}</strong>
              <span>{PHASE_LABELS[group.entries[0]?.phase] || group.entries[0]?.phase || '质量检查'}</span>
            </div>
            <small>{group.entries.length} 轮</small>
          </header>

          <ol>
            {group.entries.map((result, groupIndex) => {
              const status = getStatusMeta(result);
              const issues = Array.isArray(result.issues) ? result.issues : [];
              const primaryIssues = issues.slice(0, 2);
              const attempt = result.attempt ?? groupIndex + 1;

              return (
                <li
                  className="qa-correction-item"
                  data-status={status.tone}
                  key={`${result.phase || 'qa'}-${result.attempt ?? result.sourceIndex}`}
                >
                  <span className="qa-correction-icon" aria-hidden="true">{status.icon}</span>
                  <div className="qa-correction-body">
                    <div className="qa-correction-title">
                      <strong>{getCorrectionStory(result, attempt)}</strong>
                      <span>{status.label}</span>
                    </div>

                    <div className="qa-correction-meta">
                      {result.score != null && <span>得分 {Math.round(result.score)}</span>}
                      <span>问题 {issues.length}</span>
                      {result.hallucination_status && (
                        <span>事实检查 {result.hallucination_status}</span>
                      )}
                    </div>

                    {primaryIssues.length > 0 && (
                      <ul className="qa-issue-list">
                        {primaryIssues.map((issue, issueIndex) => (
                          <li key={`${issue.field || 'issue'}-${issueIndex}`}>
                            {getIssueText(issue)}
                          </li>
                        ))}
                      </ul>
                    )}

                    {issues.length > primaryIssues.length && (
                      <p className="qa-more-issues">另有 {issues.length - primaryIssues.length} 条问题已保留在完整记录中</p>
                    )}

                    {result.feedback_to_agent && (
                      <blockquote>
                        <span>反馈</span>
                        {trimText(result.feedback_to_agent)}
                      </blockquote>
                    )}

                    {result.message && !result.feedback_to_agent && (
                      <p className="qa-result-message">{trimText(result.message)}</p>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
