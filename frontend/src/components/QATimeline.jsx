import { Timeline, Tag, Typography } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  LoadingOutlined,
} from '@ant-design/icons';

const { Text, Paragraph } = Typography;

function getStatusMeta(result) {
  if (result.running) return { text: '质检中', color: 'processing' };
  if (result.degraded) return { text: '降级通过', color: 'warning' };
  if (result.passed) return { text: '通过', color: 'success' };
  return { text: '未通过', color: 'error' };
}

function getIssueText(issue) {
  if (!issue) return '';
  const field = issue.field ? `${issue.field}：` : '';
  return `${field}${issue.description || issue.suggestion || issue.category || ''}`;
}

function trimText(text, limit = 120) {
  if (!text) return '';
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

export default function QATimeline({ results }) {
  if (!results || results.length === 0) {
    return <Text type="secondary">暂无质检记录</Text>;
  }

  return (
    <Timeline
      items={results.map((r, index) => {
        const status = getStatusMeta(r);
        const issues = r.issues || [];
        const primaryIssues = issues.slice(0, 2);
        const title = [
          r.target_agent,
          r.phase,
          r.attempt != null ? `第 ${r.attempt} 次` : '',
        ].filter(Boolean).join(' · ');

        return {
          dot: r.running
            ? <LoadingOutlined style={{ color: '#1890ff' }} />
            : r.degraded
            ? <ExclamationCircleOutlined style={{ color: '#fa8c16' }} />
            : r.passed
            ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
            : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
          children: (
            <div>
              <div style={{ marginBottom: 6 }}>
                <Text strong>{title || r.message || `质检记录 ${index + 1}`}</Text>
              </div>

              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                <Tag color={status.color}>{status.text}</Tag>
                {r.score != null && <Text type="secondary">分数：{Math.round(r.score)}</Text>}
                {issues.length > 0 && <Text type="secondary">问题数：{issues.length}</Text>}
                {r.hallucination_status && (
                  <Text type="secondary">幻觉检测：{r.hallucination_status}</Text>
                )}
              </div>

              {r.message && !r.target_agent && (
                <Paragraph style={{ margin: '6px 0 0' }}>{r.message}</Paragraph>
              )}

              {primaryIssues.length > 0 && (
                <ul style={{ margin: '8px 0 0 18px', padding: 0 }}>
                  {primaryIssues.map((issue, issueIndex) => (
                    <li key={`${issue.field || 'issue'}-${issueIndex}`} style={{ marginBottom: 4 }}>
                      <Text>{getIssueText(issue)}</Text>
                    </li>
                  ))}
                </ul>
              )}

              {issues.length > primaryIssues.length && (
                <Text type="secondary" style={{ display: 'block', marginTop: 4 }}>
                  还有 {issues.length - primaryIssues.length} 条问题
                </Text>
              )}

              {r.feedback_to_agent && (
                <Paragraph style={{ margin: '8px 0 0' }}>
                  <Text type="secondary">反馈：</Text>
                  {trimText(r.feedback_to_agent)}
                </Paragraph>
              )}
            </div>
          ),
        };
      })}
    />
  );
}
