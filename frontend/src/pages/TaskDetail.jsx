import { useCallback, useEffect, useRef, useState } from 'react';
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
import {
  buildPresentationNodeStates,
  createTaskArtifactCache,
  filterPresentationEvents,
  getQaPresentationMode,
  selectTaskArtifactCache,
  shouldLoadQaArtifact,
  updateTaskArtifactCache,
} from '../utils/workflowPresentation';
import { buildQaSummaries, mergeQaSummaries } from '../utils/taskEvents';
import {
  getTaskModeMeta,
  getTaskStatusMeta,
  resolveTaskProgress,
  resolveTaskStatus,
} from '../utils/presentation';

const AGENT_TO_PHASE = {
  DiscoveryAgent: 'discovery',
  CollectionAgent: 'collection',
  DimensionAgent: 'dimension',
  ProductAgent: 'product_analysis',
  PricingAgent: 'pricing_analysis',
  MarketAgent: 'market_analysis',
  StrategyAgent: 'strategy',
};

export default function TaskDetail() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const [taskInfo, setTaskInfo] = useState(null);
  const [persistedQaResults, setPersistedQaResults] = useState([]);
  const [persistedQaSummaries, setPersistedQaSummaries] = useState({});
  const [artifactCache, setArtifactCache] = useState(() => createTaskArtifactCache(taskId));
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
    reset,
    AGENT_PHASE_MAP,
  } = useTask();

  const { connected } = useWebSocket(taskId, handleEvent);
  const activeTaskIdRef = useRef(taskId);
  const qaLoadAttemptedForRef = useRef(null);
  const qaPresentationModeRef = useRef('pending');
  const currentTaskInfo = taskInfo?.id === taskId ? taskInfo : null;
  const qaPresentationMode = getQaPresentationMode(taskId, currentTaskInfo);
  const qaDisabled = qaPresentationMode === 'disabled';
  const qaPresentationBlocked = qaPresentationMode !== 'enabled';

  useEffect(() => {
    qaPresentationModeRef.current = qaPresentationMode;
  }, [qaPresentationMode]);

  useEffect(() => {
    activeTaskIdRef.current = taskId;
    qaLoadAttemptedForRef.current = null;
    queueMicrotask(() => {
      setTaskInfo(null);
      setPersistedQaResults([]);
      setPersistedQaSummaries({});
      setArtifactCache(createTaskArtifactCache(taskId));
      setSelectedPhase(null);
      setDetailOpen(false);
      reset();
    });
  }, [reset, taskId]);

  const loadTaskInfo = useCallback(() => (
    getTask(taskId)
      .then((data) => {
        if (data?.id !== taskId || activeTaskIdRef.current !== taskId) return null;
        setTaskInfo(data);
        return data;
      })
      .catch(() => null)
  ), [taskId]);

  const cacheArtifact = useCallback((phase, data) => {
    setArtifactCache(previous => updateTaskArtifactCache(previous, taskId, phase, data));
  }, [taskId]);

  const mergeQaResult = useCallback((qaResult) => {
    if (qaPresentationModeRef.current !== 'enabled') return;
    setArtifactCache((previous) => {
      const artifacts = selectTaskArtifactCache(previous, taskId);
      if (previous.taskId !== taskId) return previous;
      const previousChecks = artifacts.qa?.checks || [];
      const checks = [
        ...previousChecks.filter(check => !(
          check.phase === qaResult.phase
          && (check.attempt == null || qaResult.attempt == null || check.attempt === qaResult.attempt)
        )),
        qaResult,
      ];
      return updateTaskArtifactCache(previous, taskId, 'qa', {
          ...(artifacts.qa || {}),
          checks,
      });
    });
  }, [taskId]);

  const refreshArtifact = useCallback((phase) => {
    if (!phase) return Promise.resolve(null);
    return getArtifact(taskId, phase)
      .then((data) => {
        if (activeTaskIdRef.current !== taskId) return null;
        cacheArtifact(phase, data);
        return data;
      })
      .catch(() => null);
  }, [cacheArtifact, taskId]);

  const refreshQa = useCallback(() => {
    if (!shouldLoadQaArtifact(taskId, currentTaskInfo, qaLoadAttemptedForRef.current)) {
      return Promise.resolve(null);
    }
    qaLoadAttemptedForRef.current = taskId;
    return getArtifact(taskId, 'qa')
      .then((data) => {
        if (activeTaskIdRef.current !== taskId || qaPresentationModeRef.current !== 'enabled') return null;
        const checks = data?.checks || [];
        cacheArtifact('qa', data);
        setPersistedQaResults(checks);
        setPersistedQaSummaries(buildQaSummaries(checks));
        return data;
      })
      .catch(() => {
        if (activeTaskIdRef.current !== taskId || qaPresentationModeRef.current !== 'enabled') return null;
        setPersistedQaResults([]);
        setPersistedQaSummaries({});
        return null;
      });
  }, [cacheArtifact, currentTaskInfo, taskId]);

  useEffect(() => {
    loadTaskInfo();
  }, [loadTaskInfo]);

  useEffect(() => {
    if (qaPresentationMode !== 'enabled') return;
    refreshQa();
  }, [qaPresentationMode, refreshQa]);

  useEffect(() => {
    if (!taskId) return undefined;
    const interval = window.setInterval(loadTaskInfo, 2000);
    return () => window.clearInterval(interval);
  }, [loadTaskInfo, taskId]);

  useEffect(() => {
    const event = events[events.length - 1];
    if (!event) return;
    if (qaPresentationMode === 'pending') return;

    if (event.type === 'agent_completed') {
      refreshArtifact(event.phase);
    }
    if (qaPresentationMode === 'enabled' && (event.type === 'qa_check_passed' || event.type === 'qa_check_failed')) {
      const qaResult = event.data?.qa_result;
      if (qaResult) {
        queueMicrotask(() => mergeQaResult(qaResult));
      } else {
        refreshQa();
      }
    }
    if (qaPresentationMode === 'enabled' && event.type === 'task_completed') {
      refreshQa();
    }
  }, [events, mergeQaResult, qaPresentationMode, refreshArtifact, refreshQa]);

  const handleNodeClick = (phase) => {
    setSelectedPhase(phase);
    setDetailOpen(true);
  };

  const graphQaSummaries = qaPresentationBlocked
    ? {}
    : mergeQaSummaries(persistedQaSummaries, qaSummaries);
  const timelineQaResults = qaPresentationBlocked ? [] : (qaResults.length > 0 ? qaResults : persistedQaResults);
  const taskArtifacts = selectTaskArtifactCache(artifactCache, taskId);
  const cockpitChecks = taskArtifacts.qa?.checks?.length > 0
    ? taskArtifacts.qa.checks
    : timelineQaResults;
  const presentationEvents = filterPresentationEvents(events, qaPresentationBlocked);
  const resolvedTaskStatus = resolveTaskStatus(taskStatus, currentTaskInfo?.status);
  const currentPhase = AGENT_TO_PHASE[currentTaskInfo?.current_agent];
  const graphNodeStates = buildPresentationNodeStates(
    nodeStates,
    resolvedTaskStatus,
    currentPhase,
  );

  const taskStatusMeta = getTaskStatusMeta(resolvedTaskStatus);
  const taskModeMeta = getTaskModeMeta(currentTaskInfo);
  const progressPercent = resolveTaskProgress(
    resolvedTaskStatus,
    progress,
    currentTaskInfo?.progress,
  );
  const currentAgent = currentTaskInfo?.current_agent
    || (currentPhase ? AGENT_PHASE_MAP[currentPhase]?.agent : null)
    || '等待调度';
  const presentationCurrentMessage = qaPresentationBlocked
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
            <h1>{currentTaskInfo?.product_description || taskId}</h1>
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

        {currentTaskInfo?.error && <p className="mission-error">{currentTaskInfo.error}</p>}

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
        artifactData={selectedPhase ? taskArtifacts[selectedPhase] : undefined}
        qaArtifactData={qaPresentationBlocked ? undefined : taskArtifacts.qa}
        qaDisabled={qaPresentationBlocked}
        onArtifactLoaded={cacheArtifact}
      />
    </main>
  );
}
