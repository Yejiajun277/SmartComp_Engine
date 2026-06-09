import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Progress, Typography, Row, Col, Statistic, Button, Tag, Space } from 'antd';
import {
  ArrowLeftOutlined,
  FileTextOutlined,
  ClockCircleOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import { getTask } from '../api/client';
import { useWebSocket } from '../hooks/useWebSocket';
import { useTask } from '../hooks/useTask';
import PipelineGraph from '../components/PipelineGraph';
import AgentDetail from '../components/AgentDetail';
import QATimeline from '../components/QATimeline';
import LlmLogs from '../components/LlmLogs';

const { Title, Text } = Typography;

export default function TaskDetail() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const [taskInfo, setTaskInfo] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedPhase, setSelectedPhase] = useState(null);

  const {
    events, nodeStates, progress, currentMessage,
    qaResults, taskStatus, handleEvent, AGENT_PHASE_MAP,
  } = useTask();

  const { connected } = useWebSocket(taskId, handleEvent);

  useEffect(() => {
    getTask(taskId).then(setTaskInfo).catch(() => {});
  }, [taskId]);

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
          nodeStates={nodeStates}
          onNodeClick={handleNodeClick}
        />
      </Card>

      {/* Bottom Row: QA + Stats */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24} md={12}>
          <Card title="质检结果" style={{ height: '100%' }}>
            <QATimeline results={qaResults} />
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
                  value={qaResults.length}
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
      />
    </div>
  );
}
