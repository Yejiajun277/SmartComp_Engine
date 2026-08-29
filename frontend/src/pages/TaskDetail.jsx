import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Collapse, Progress } from 'antd';
import {
  ArrowLeftOutlined,
  CodeOutlined,
  FileTextOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import { getArtifact, getTask } from '../api/client';
import { useWebSocket } from '../hooks/useWebSocket';
import { useTask } from '../hooks/useTask';
import AgentDetail from '../components/AgentDetail';
import LlmLogs from '../components/LlmLogs';
import PipelineGraph from '../components/PipelineGraph';
import QATimeline from '../components/QATimeline';
import LiveActivityRail from '../components/workbench/LiveActivityRail';
import QualityCockpit from '../components/workbench/QualityCockpit';
import QualityDisabledNotice from '../components/workbench/QualityDisabledNotice';
import { filterPresentationEvents } from '../utils/workflowPresentation';
import { mergeQaSummaries } from '../utils/taskEvents';
import {
  getTaskModeMeta,
  getTaskStatusMeta,
  resolveTaskProgress,
  resolveTaskStatus,
} from '../utils/presentation';

const QA_PHASE_TO_NODE = {
  collection: 'collection',
  product: 'product_analysis',
  pricing: 'pricing_analysis',
  market: 'market_analysis',
  strategy: 'strategy',
};

const AGENT_TO_PHASE = {
  DiscoveryAgent: 'discovery',
  CollectionAgent: 'collection',
  DimensionAgent: 'dimension',
  ProductAgent: 'product_analysis',
  PricingAgent: 'pricing_analysis',
  MarketAgent: 'market_analysis',
  StrategyAgent: 'strategy',
};

function summarizeQaChecks(checks = []) {
  const summaries = {};

  checks.forEach((check) => {
    const nodeKey = QA_PHASE_TO_NODE[check.phase];
    if (!nodeKey) return;

    const current = summaries[nodeKey] || { retryCount: 0 };
    if (check.running) {
      summaries[nodeKey] = {
        ...current,
        phase: check.phase,
        label: '质检中',
        status: 'running',
        score: check.score,
      };
      return;
    }

    const retryCount = current.retryCount + (
      check.passed === false && !check.degraded ? 1 : 0
    );
    const status = check.degraded ? 'degraded' : check.passed ? 'passed' : 'failed';
    const label = check.degraded
      ? `降级通过 · 打回 ${retryCount} 次`
      : check.passed
        ? `通过${check.score != null ? ` · ${Math.round(check.score)} 分` : ''}`
        : `未通过 · 打回 ${retryCount} 次`;

    summaries[nodeKey] = {
      phase: check.phase,
      label,
      status,
      score: check.score,
      retryCount,
    };
  });

  return summaries;
}

export default function TaskDetail() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const [taskInfo, setTaskInfo] = useState(null);
  const [persistedQaResults, setPersistedQaResults] = useState([]);
  const [persistedQaSummaries, setPersistedQaSummaries] = useState({});
  const [artifactCache, setArtifactCache] = useState({});
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedPhase, setSelectedPhase] = useState(null);
  const {
    events,
    nodeStates,
    progress,
    currentMessage,
    qaResults,
    qaSummaries,
    taskStatus,
    llmLogsKey,
    handleEvent,
    AGENT_PHASE_MAP,
  } = useTask();

  const { connected } = useWebSocket(taskId, handleEvent);
  const qaDisabled = taskInfo?.skip_qa === true;

  const loadTaskInfo = useCallback(() => (
    getTask(taskId).then(setTaskInfo).catch(() => null)
  ), [taskId]);

  const cacheArtifact = useCallback((phase, data) => {
    setArtifactCache(previous => ({ ...previous, [phase]: data }));
  }, []);

  const mergeQaResult = useCallback((qaResult) => {
    setArtifactCache((previous) => {
      const previousChecks = previous.qa?.checks || [];
      const checks = [
        ...previousChecks.filter(check => !(
          check.phase === qaResult.phase
          && (check.attempt == null || qaResult.attempt == null || check.attempt === qaResult.attempt)
        )),
        qaResult,
      ];
      return {
        ...previous,
        qa: {
          ...(previous.qa || {}),
          checks,
        },
      };
    });
  }, []);

  const refreshArtifact = useCallback((phase) => {
    if (!phase) return Promise.resolve(null);
    return getArtifact(taskId, phase)
      .then((data) => {
        cacheArtifact(phase, data);
        return data;
      })
      .catch(() => null);
  }, [cacheArtifact, taskId]);

  const refreshQa = useCallback(() => {
    if (qaDisabled) return Promise.resolve(null);
    return getArtifact(taskId, 'qa')
      .then((data) => {
        const checks = data?.checks || [];
        cacheArtifact('qa', data);
        setPersistedQaResults(checks);
        setPersistedQaSummaries(summarizeQaChecks(checks));
        return data;
      })
      .catch(() => {
        setPersistedQaResults([]);
        setPersistedQaSummaries({});
        return null;
      });
  }, [cacheArtifact, qaDisabled, taskId]);

  useEffect(() => {
    loadTaskInfo();
  }, [loadTaskInfo]);

  useEffect(() => {
    if (!taskInfo || qaDisabled) return;
    refreshQa();
  }, [qaDisabled, refreshQa, taskInfo]);

  useEffect(() => {
    if (!taskId) return undefined;
    const interval = window.setInterval(loadTaskInfo, 2000);
    return () => window.clearInterval(interval);
  }, [loadTaskInfo, taskId]);

  useEffect(() => {
    const event = events[events.length - 1];
    if (!event) return;

    if (event.type === 'agent_completed') {
      refreshArtifact(event.phase);
    }
    if (!qaDisabled && (event.type === 'qa_check_passed' || event.type === 'qa_check_failed')) {
      const qaResult = event.data?.qa_result;
      if (qaResult) {
        queueMicrotask(() => mergeQaResult(qaResult));
      } else {
        refreshQa();
      }
    }
    if (!qaDisabled && event.type === 'task_completed') {
      refreshQa();
    }
  }, [events, mergeQaResult, qaDisabled, refreshArtifact, refreshQa]);

  const handleNodeClick = (phase) => {
    setSelectedPhase(phase);
    setDetailOpen(true);
  };

  const graphQaSummaries = qaDisabled
    ? {}
    : mergeQaSummaries(persistedQaSummaries, qaSummaries);
  const timelineQaResults = qaDisabled ? [] : (qaResults.length > 0 ? qaResults : persistedQaResults);
  const cockpitChecks = artifactCache.qa?.checks?.length > 0
    ? artifactCache.qa.checks
    : timelineQaResults;
  const presentationEvents = filterPresentationEvents(events, qaDisabled);
  const graphNodeStates = { ...nodeStates };
  const currentPhase = AGENT_TO_PHASE[taskInfo?.current_agent];

  if (
    taskInfo?.status === 'running'
    && currentPhase
    && graphNodeStates[currentPhase] !== 'failed'
    && graphNodeStates[currentPhase] !== 'retrying'
  ) {
    graphNodeStates[currentPhase] = 'running';
  }

  const resolvedTaskStatus = resolveTaskStatus(taskStatus, taskInfo?.status);
  const taskStatusMeta = getTaskStatusMeta(resolvedTaskStatus);
  const taskModeMeta = getTaskModeMeta(taskInfo);
  const progressPercent = resolveTaskProgress(
    resolvedTaskStatus,
    progress,
    taskInfo?.progress,
  );
  const currentAgent = taskInfo?.current_agent
    || (currentPhase ? AGENT_PHASE_MAP[currentPhase]?.agent : null)
    || '等待调度';
  const presentationCurrentMessage = qaDisabled
    ? presentationEvents.at(-1)?.message || '业务 Agent 正在推进工作流'
    : currentMessage;

  return (
    <main className="page-shell workbench-page">
      <Button
        className="workbench-back"
        type="text"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate('/')}
      >
        返回分析中心
      </Button>

      <section className="surface-card mission-header">
        <div className="mission-title-row">
          <div className="mission-title-copy">
            <span className="section-eyebrow">Live agent mission</span>
            <h1>{taskInfo?.product_description || taskId}</h1>
            <p>{presentationCurrentMessage || '等待 Agent 团队更新进度'}</p>
          </div>
          <div className="mission-actions">
            <span className={`status-pill status-${taskStatusMeta.tone}`}>
              {taskStatusMeta.label}
            </span>
            <span className={`status-pill ${connected ? 'status-connected' : 'status-disconnected'}`}>
              <i aria-hidden="true" />
              {connected ? '实时连接正常' : '正在重新连接'}
            </span>
            {resolvedTaskStatus === 'completed' && (
              <Button
                className="primary-action report-entry-action"
                type="primary"
                icon={<FileTextOutlined />}
                onClick={() => navigate(`/tasks/${taskId}/report`)}
              >
                查看策略报告
              </Button>
            )}
          </div>
        </div>

        <div className="mission-meta-row">
          <span><RobotOutlined /> 当前 Agent：<strong>{currentAgent}</strong></span>
          <span>
            <CodeOutlined />
            {taskModeMeta.executionLabel}
          </span>
          <span className={taskModeMeta.qaTone === 'risk' ? 'mission-risk-meta' : ''}>
            <SafetyCertificateOutlined />
            {taskModeMeta.qaLabel}
          </span>
        </div>

        {taskInfo?.error && <p className="mission-error">{taskInfo.error}</p>}

        <div className="mission-progress-row">
          <span>任务总进度</span>
          <strong>{progressPercent}%</strong>
        </div>
        <Progress
          className="mission-progress"
          percent={progressPercent}
          showInfo={false}
          status={resolvedTaskStatus === 'failed' ? 'exception' : undefined}
          strokeColor={{ from: '#176bff', to: '#58e6c2' }}
        />
      </section>

      <section className="workbench-grid">
        <section className="surface-card workflow-deck" aria-labelledby="workflow-deck-title">
          <header className="workflow-deck-header">
            <div>
              <span className="section-eyebrow">Agent workflow</span>
              <h2 id="workflow-deck-title">协作流程与质量门</h2>
            </div>
            <p>点击业务 Agent 查看阶段产物</p>
          </header>
          <PipelineGraph
            nodeStates={graphNodeStates}
            qaSummaries={graphQaSummaries}
            taskStatus={resolvedTaskStatus}
            qaDisabled={qaDisabled}
            onNodeClick={handleNodeClick}
          />
        </section>

        <LiveActivityRail
          events={presentationEvents}
          currentMessage={presentationCurrentMessage}
          connected={connected}
          qaDisabled={qaDisabled}
        />
      </section>

      {qaDisabled ? (
        <QualityDisabledNotice />
      ) : (
        <section className="quality-grid">
          <QualityCockpit checks={cockpitChecks} />
          <section className="surface-card qa-timeline-panel" aria-labelledby="qa-timeline-title">
            <header>
              <div>
                <span className="section-eyebrow">Correction trail</span>
                <h2 id="qa-timeline-title">QA 修正记录</h2>
              </div>
              <span>{timelineQaResults.length} 条记录</span>
            </header>
            <QATimeline results={timelineQaResults} />
          </section>
        </section>
      )}

      <section className="technical-trace" aria-label="技术追溯">
        <Collapse
          className="technical-trace-collapse"
          items={[{
            key: 'trace',
            label: (
              <div className="technical-trace-label">
                <CodeOutlined />
                <span>
                  <strong>运行详情与技术追溯</strong>
                  <small>按需查看模型、Token、耗时以及原始输入输出</small>
                </span>
              </div>
            ),
            children: <LlmLogs taskId={taskId} refreshKey={llmLogsKey} />,
          }]}
        />
      </section>

      <AgentDetail
        taskId={taskId}
        phase={selectedPhase}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        agentLabel={selectedPhase ? AGENT_PHASE_MAP[selectedPhase]?.label : ''}
        nodeStatus={selectedPhase ? graphNodeStates[selectedPhase] : undefined}
        artifactData={selectedPhase ? artifactCache[selectedPhase] : undefined}
        qaArtifactData={qaDisabled ? undefined : artifactCache.qa}
        qaDisabled={qaDisabled}
        onArtifactLoaded={cacheArtifact}
      />
    </main>
  );
}
