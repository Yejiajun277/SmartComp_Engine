import { useEffect, useState } from 'react';
import { Collapse, Drawer, Spin, Tabs, Typography } from 'antd';
import { getArtifact } from '../api/client';
import QATimeline from './QATimeline';

const { Text } = Typography;

const QA_PHASE_MAP = {
  collection: 'collection',
  product_analysis: 'product',
  pricing_analysis: 'pricing',
  market_analysis: 'market',
  strategy: 'strategy',
};

const NODE_STATUS_LABELS = {
  waiting: '等待执行',
  running: '正在分析',
  retrying: 'QA 打回后重做',
  completed: '阶段完成',
  failed: '执行失败',
};

const SUMMARY_KEYS = [
  'summary',
  'overall_summary',
  'conclusion',
  'overall_positioning',
  'positioning',
  'analysis_summary',
  'description',
];

function getQaChecks(qaData, phase) {
  const qaPhase = QA_PHASE_MAP[phase];
  if (!qaPhase || !qaData?.checks) return [];
  return qaData.checks.filter(check => check.phase === qaPhase);
}

function getSummary(data) {
  if (typeof data === 'string') return data;
  if (!data || typeof data !== 'object') return '';
  const key = SUMMARY_KEYS.find(candidate => typeof data[candidate] === 'string' && data[candidate]);
  return key ? data[key] : '';
}

function getArtifactFacts(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return [];

  return Object.entries(data)
    .filter(([key]) => !SUMMARY_KEYS.includes(key) && !['citations', 'references', 'sources'].includes(key))
    .slice(0, 6)
    .map(([key, value]) => {
      if (Array.isArray(value)) return { key, value: `${value.length} 项` };
      if (value && typeof value === 'object') return { key, value: `${Object.keys(value).length} 个字段` };
      return { key, value: String(value ?? '—') };
    });
}

function collectCitations(value, citations = [], visited = new Set()) {
  if (!value || typeof value !== 'object' || visited.has(value)) return citations;
  visited.add(value);

  if (Array.isArray(value)) {
    value.forEach(item => collectCitations(item, citations, visited));
    return citations;
  }

  if (typeof value.url === 'string') {
    const title = value.title || value.source || value.name || value.url;
    if (!citations.some(citation => citation.url === value.url)) {
      citations.push({ title, url: value.url });
    }
  }

  Object.values(value).forEach(item => collectCitations(item, citations, visited));
  return citations;
}

function PhaseConclusion({ data, nodeStatus, emptyText }) {
  const summary = getSummary(data);
  const facts = getArtifactFacts(data);

  return (
    <div className="agent-detail-conclusion">
      <div className="agent-detail-stage-state">
        <span>阶段状态</span>
        <strong>{NODE_STATUS_LABELS[nodeStatus] || nodeStatus || '状态待同步'}</strong>
      </div>
      {summary && <p className="agent-detail-summary">{summary}</p>}
      {!summary && facts.length === 0 && <Text type="secondary">{emptyText}</Text>}
      {facts.length > 0 && (
        <dl className="agent-detail-facts">
          {facts.map(fact => (
            <div key={fact.key}>
              <dt>{fact.key.replaceAll('_', ' ')}</dt>
              <dd>{fact.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function EvidenceAndRawData({ data }) {
  const citations = collectCitations(data);

  if (!data) return <Text type="secondary">该阶段暂无引用或原始数据</Text>;
  return (
    <div className="agent-detail-evidence">
      <header>
        <strong>可识别引用</strong>
        <span>{citations.length} 条</span>
      </header>
      {citations.length > 0 ? (
        <ol>
          {citations.slice(0, 20).map(citation => (
            <li key={citation.url}>
              {/^https?:\/\//i.test(citation.url) ? (
                <a href={citation.url} target="_blank" rel="noreferrer">{citation.title}</a>
              ) : citation.title}
            </li>
          ))}
        </ol>
      ) : (
        <Text type="secondary">该阶段产物中未识别到独立引用对象</Text>
      )}
      <Collapse
        className="agent-raw-data-collapse"
        items={[{
          key: 'raw',
          label: '查看结构化原始数据',
          children: <pre>{JSON.stringify(data, null, 2)}</pre>,
        }]}
      />
    </div>
  );
}

function TechnicalTrace({ data }) {
  const trace = data?.technical_trace || data?.execution || data?.metadata;
  if (!trace) {
    return (
      <Text type="secondary">
        此阶段未提供额外执行元数据。模型、Token、耗时及原始输入输出可在工作台底部的“运行详情与技术追溯”中查看。
      </Text>
    );
  }
  return <pre className="agent-technical-json">{JSON.stringify(trace, null, 2)}</pre>;
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
  const [loadedArtifact, setLoadedArtifact] = useState({ phase: null, data: null });
  const [loadedQaData, setLoadedQaData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !taskId || !phase) return undefined;
    const needsArtifact = artifactData === undefined;
    const needsQa = qaArtifactData === undefined;
    if (!needsArtifact && !needsQa) return undefined;

    let cancelled = false;
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
        setLoadedArtifact({ phase, data: nextData });
        setLoadedQaData(nextQaData);
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

  const displayData = artifactData !== undefined
    ? artifactData
    : loadedArtifact.phase === phase ? loadedArtifact.data : null;
  const displayQaData = qaArtifactData !== undefined ? qaArtifactData : loadedQaData;
  const qaChecks = getQaChecks(displayQaData, phase);
  const emptyText = nodeStatus === 'running'
    ? 'Agent 执行中，完成后会自动显示阶段结论'
    : nodeStatus === 'waiting'
      ? '该 Agent 尚未开始，完成后会自动显示阶段结论'
      : '暂无阶段输出';

  const tabs = [
    {
      key: 'conclusion',
      label: '阶段结论',
      children: <PhaseConclusion data={displayData} nodeStatus={nodeStatus} emptyText={emptyText} />,
    },
    {
      key: 'quality',
      label: `质量反馈${qaChecks.length > 0 ? ` ${qaChecks.length}` : ''}`,
      children: qaChecks.length > 0
        ? <QATimeline results={qaChecks} />
        : <Text type="secondary">该阶段暂无质检记录</Text>,
    },
    {
      key: 'evidence',
      label: '引用与原始数据',
      children: <EvidenceAndRawData data={displayData} />,
    },
    {
      key: 'technical',
      label: '技术追溯',
      children: <TechnicalTrace data={displayData} />,
    },
  ];

  return (
    <Drawer
      className="agent-detail-drawer"
      title={(
        <div className="agent-detail-title">
          <span>{agentLabel || phase}</span>
          <small>{NODE_STATUS_LABELS[nodeStatus] || nodeStatus || '等待状态同步'}</small>
        </div>
      )}
      open={open}
      onClose={onClose}
      size="large"
    >
      {loading ? (
        <Spin style={{ display: 'block', textAlign: 'center', padding: 40 }} />
      ) : (
        <Tabs className="agent-detail-tabs" defaultActiveKey="conclusion" items={tabs} />
      )}
    </Drawer>
  );
}
