import { useCallback, useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Progress, Typography, Row, Col, Statistic, Button, Tag, Space } from 'antd';
import {
  ArrowLeftOutlined,
  FileTextOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import { getArtifact, getTask } from '../api/client';
import { useWebSocket } from '../hooks/useWebSocket';
import { useTask } from '../hooks/useTask';
import PipelineGraph from '../components/PipelineGraph';
import AgentDetail from '../components/AgentDetail';
import QATimeline from '../components/QATimeline';
import LlmLogs from '../components/LlmLogs';

const { Title, Text } = Typography;

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
    const retryCount = current.retryCount + (check.passed ? 0 : 1);
    const label = check.degraded
      ? `降级通过，打回 ${retryCount} 次`
      : check.passed
        ? `通过${check.score != null ? ` ${Math.round(check.score)}分` : ''}`
        : `未通过，打回 ${retryCount} 次`;

    summaries[nodeKey] = {
      phase: check.phase,
      label,
      status: check.degraded ? 'degraded' : check.passed ? 'passed' : 'failed',
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
    events, nodeStates, progress, currentMessage,
    qaResults, qaSummaries, taskStatus, handleEvent, AGENT_PHASE_MAP,
  } = useTask();

  const { connected } = useWebSocket(taskId, handleEvent);

  const loadTaskInfo = useCallback(() => (
    getTask(taskId).then(setTaskInfo).catch(() => {})
  ), [taskId]);

  const cacheArtifact = useCallback((phase, data) => {
    setArtifactCache(prev => ({ ...prev, [phase]: data }));
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

  const refreshQa = useCallback(() => (
    getArtifact(taskId, 'qa')
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
      })
  ), [cacheArtifact, taskId]);

  useEffect(() => {
    loadTaskInfo();
    refreshQa();
  }, [loadTaskInfo, refreshQa]);

  useEffect(() => {
    if (!taskId) return undefined;
    const interval = setInterval(loadTaskInfo, 2000);
    return () => clearInterval(interval);
  }, [loadTaskInfo, taskId]);

  useEffect(() => {
    const event = events[events.length - 1];
    if (!event) return;

    if (event.type === 'agent_completed') {
      refreshArtifact(event.phase);
    }
    if (event.type === 'qa_check_passed' || event.type === 'qa_check_failed') {
      refreshQa();
    }
  }, [events, refreshArtifact, refreshQa]);

  const handleNodeClick = (phase) => {
    setSelectedPhase(phase);
    setDetailOpen(true);
  };

  const statusColor = {
    pending: 'default', running: 'processing', completed: 'success', failed: 'error',
  }[taskStatus] || 'default';

  const statusText = {
    pending: '等待中', running: '运行中', completed: '已完成', failed: '失败',
  }[taskStatus] || taskStatus;
  const graphQaSummaries = Object.keys(qaSummaries).length > 0 ? qaSummaries : persistedQaSummaries;
  const timelineQaResults = qaResults.length > 0 ? qaResults : persistedQaResults;
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

  return (
    <div style={{ padding: 24 }}>
      <Button
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate('/')}
        style={{ marginBottom: 16 }}
      >
        返回
      </Button>

      {/* Header */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={24} align="middle">
          <Col flex="auto">
            <Space>
              <Title level={3} style={{ margin: 0 }}>
                {taskInfo?.product_description || taskId}
              </Title>
              <Tag color={statusColor}>{statusText}</Tag>
              <Tag color={connected ? 'green' : 'default'}>
                {connected ? 'WS 已连接' : 'WS 未连接'}
              </Tag>
            </Space>
            {currentMessage && (
              <Text type="secondary" style={{ display: 'block', marginTop: 4 }}>
                {currentMessage}
              </Text>
            )}
            {taskInfo && (
              <Space style={{ marginTop: 4 }}>
                {taskInfo.use_rule_engine && <Tag color="purple">规则引擎模式</Tag>}
                {taskInfo.skip_qa && <Tag color="orange">跳过质检</Tag>}
              </Space>
            )}
          </Col>
          <Col>
            {taskStatus === 'completed' && (
              <Button
                type="primary"
                icon={<FileTextOutlined />}
                onClick={() => navigate(`/tasks/${taskId}/report`)}
              >
                查看报告
              </Button>
            )}
          </Col>
        </Row>

        <Progress
          percent={Math.round(progress * 100)}
          status={taskStatus === 'failed' ? 'exception' : undefined}
          style={{ marginTop: 12 }}
        />
      </Card>

      {/* Pipeline Visualization */}
      <Card title="Agent 流程" style={{ marginBottom: 16 }}>
        <PipelineGraph
          nodeStates={graphNodeStates}
          qaSummaries={graphQaSummaries}
          onNodeClick={handleNodeClick}
        />
      </Card>

      {/* Bottom Row: QA + Stats */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24} md={12}>
          <Card title="质检结果" style={{ height: '100%' }}>
            <QATimeline results={timelineQaResults} />
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title="统计" style={{ height: '100%' }}>
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title="事件数"
                  value={events.length}
                  prefix={<RobotOutlined />}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="进度"
                  value={Math.round(progress * 100)}
                  suffix="%"
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="质检次数"
                  value={timelineQaResults.length}
                />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      {/* LLM Logs */}
      <Card title="LLM 调用日志" style={{ marginBottom: 16 }}>
        <LlmLogs taskId={taskId} />
      </Card>

      {/* Agent Detail Drawer */}
      <AgentDetail
        taskId={taskId}
        phase={selectedPhase}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        agentLabel={selectedPhase ? AGENT_PHASE_MAP[selectedPhase]?.label : ''}
        nodeStatus={selectedPhase ? graphNodeStates[selectedPhase] : undefined}
        artifactData={selectedPhase ? artifactCache[selectedPhase] : undefined}
        qaArtifactData={artifactCache.qa}
        onArtifactLoaded={cacheArtifact}
      />
    </div>
  );
}
