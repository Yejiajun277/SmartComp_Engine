import { Drawer, Descriptions, Tag, Collapse, Typography, Spin } from 'antd';
import { useState, useEffect } from 'react';
import { getArtifact } from '../api/client';

const { Text, Paragraph } = Typography;

const QA_PHASE_MAP = {
  collection: 'collection',
  product_analysis: 'product',
  pricing_analysis: 'pricing',
  market_analysis: 'market',
  strategy: 'strategy',
};

function getQaChecks(qaData, phase) {
  const qaPhase = QA_PHASE_MAP[phase];
  if (!qaPhase || !qaData?.checks) return [];
  return qaData.checks.filter(check => check.phase === qaPhase);
}

function qaStatusText(check) {
  if (check.degraded) return '降级通过';
  return check.passed ? '通过' : '未通过';
}

function withRetryCounts(checks) {
  return checks.reduce(
    (acc, check, index) => {
      const retryCount = acc.retryCount + (check.passed ? 0 : 1);
      return {
        retryCount,
        items: [...acc.items, { check, index, retryCount }],
      };
    },
    { retryCount: 0, items: [] },
  ).items;
}

function QaCheckCard({ check, index, retryCount }) {
  const color = check.degraded ? 'warning' : check.passed ? 'success' : 'error';
  const issues = check.issues || [];
  const feedback = check.feedback_to_agent || '';

  return (
    <div style={{
      border: '1px solid #f0f0f0',
      borderRadius: 8,
      padding: 12,
      marginBottom: 12,
      background: '#fff',
    }}>
      <Descriptions
        size="small"
        column={2}
        items={[
          { key: 'status', label: '状态', children: <Tag color={color}>{qaStatusText(check)}</Tag> },
          { key: 'score', label: '分数', children: check.score != null ? Math.round(check.score) : '-' },
          { key: 'attempt', label: '第几次', children: check.attempt ?? index + 1 },
          { key: 'retry', label: '累计打回', children: retryCount },
          { key: 'agent', label: '质检对象', children: check.target_agent || '-' },
          { key: 'hallucination', label: '幻觉检测', children: check.hallucination_status || '-' },
        ]}
      />

      {issues.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <Text strong>问题</Text>
          <ul style={{ margin: '6px 0 0 18px', padding: 0 }}>
            {issues.map((issue, i) => (
              <li key={`${issue.field || 'issue'}-${i}`} style={{ marginBottom: 4 }}>
                <Text>
                  {issue.field ? `${issue.field}：` : ''}
                  {issue.description || issue.suggestion || issue.category}
                </Text>
              </li>
            ))}
          </ul>
        </div>
      )}

      {feedback && (
        <div style={{ marginTop: 12 }}>
          <Text strong>反馈</Text>
          <Paragraph style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>{feedback}</Paragraph>
        </div>
      )}
    </div>
  );
}

export default function AgentDetail({
  taskId,
  phase,
  open,
  onClose,
  agentLabel,
  nodeStatus,
  artifactData,
  qaArtifactData,
  onArtifactLoaded,
}) {
  const [data, setData] = useState(null);
  const [qaData, setQaData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !taskId || !phase) return;
    let cancelled = false;
    const needsArtifact = artifactData === undefined;
    const needsQa = qaArtifactData === undefined;

    if (!needsArtifact) setData(artifactData);
    if (!needsQa) setQaData(qaArtifactData);
    if (!needsArtifact && !needsQa) return undefined;

    Promise.resolve()
      .then(() => {
        if (!cancelled) setLoading(true);
        return Promise.allSettled([
          needsArtifact ? getArtifact(taskId, phase) : Promise.resolve(artifactData),
          needsQa ? getArtifact(taskId, 'qa') : Promise.resolve(qaArtifactData),
        ]);
      })
      .then(([artifactResult, qaResult]) => {
        if (cancelled) return;
        const nextData = artifactResult.status === 'fulfilled' ? artifactResult.value : null;
        const nextQaData = qaResult.status === 'fulfilled' ? qaResult.value : null;
        setData(nextData);
        setQaData(nextQaData);
        if (nextData) onArtifactLoaded?.(phase, nextData);
        if (nextQaData) onArtifactLoaded?.('qa', nextQaData);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [artifactData, onArtifactLoaded, open, phase, qaArtifactData, taskId]);

  const displayData = artifactData !== undefined ? artifactData : data;
  const displayQaData = qaArtifactData !== undefined ? qaArtifactData : qaData;
  const qaChecks = getQaChecks(displayQaData, phase);
  const qaChecksWithRetry = withRetryCounts(qaChecks);
  const emptyText = nodeStatus === 'running'
    ? 'Agent 执行中，完成后会自动显示详情'
    : nodeStatus === 'waiting'
      ? '该 Agent 未开始，完成后会自动显示详情'
      : '暂无输出数据';

  return (
    <Drawer
      title={`${agentLabel || phase} - 详细信息`}
      open={open}
      onClose={onClose}
      size="large"
    >
      {loading ? (
        <Spin style={{ display: 'block', textAlign: 'center', padding: 40 }} />
      ) : (
        <Collapse
          defaultActiveKey={['output', 'qa']}
          items={[
            {
              key: 'output',
              label: 'Agent 输出',
              children: displayData ? (
                <Paragraph>
                  <pre style={{
                    background: '#f5f5f5',
                    padding: 12,
                    borderRadius: 8,
                    maxHeight: 400,
                    overflow: 'auto',
                    fontSize: 12,
                  }}>
                    {JSON.stringify(displayData, null, 2)}
                  </pre>
                </Paragraph>
              ) : (
                <Text type="secondary">{emptyText}</Text>
              ),
            },
            {
              key: 'qa',
              label: '对应质检 QualityAgent',
              children: qaChecks.length > 0 ? (
                <div>
                  {qaChecksWithRetry.map(({ check, index, retryCount }) => (
                    <QaCheckCard
                      key={`${check.phase}-${check.attempt || index}-${index}`}
                      check={check}
                      index={index}
                      retryCount={retryCount}
                    />
                  ))}
                </div>
              ) : (
                <Text type="secondary">该阶段暂无质检</Text>
              ),
            },
          ]}
        />
      )}
    </Drawer>
  );
}
