import { ArrowDownOutlined, BranchesOutlined } from '@ant-design/icons';
import AgentNode from './AgentNode';
import QAGate from './QAGate';
import { deriveStageStatus } from '../utils/workflowPresentation';

const STAGES = [
  {
    number: 1,
    key: 'discovery_collection',
    title: '发现竞品并建立证据',
    purpose: '先识别直接竞争者，再补全可追溯的市场与产品证据。',
    deliverable: '竞品清单与证据集',
    agents: [
      { key: 'discovery', label: '竞品发现', agent: 'DiscoveryAgent' },
      { key: 'collection', label: '证据采集', agent: 'CollectionAgent' },
    ],
    checkpoint: { label: '证据完整性检查', targets: ['collection'] },
  },
  {
    number: 2,
    key: 'dimension',
    title: '定义分析框架',
    purpose: '将已收集的证据整理为后续研判可复用的分析维度。',
    deliverable: '分析维度配置',
    agents: [{ key: 'dimension', label: '维度配置', agent: 'DimensionAgent' }],
  },
  {
    number: 3,
    key: 'analysis',
    title: '并行分析竞争态势',
    purpose: '围绕产品、定价和市场位置同步形成三条独立判断。',
    deliverable: '三维竞争分析',
    parallel: true,
    agents: [
      { key: 'product_analysis', label: '产品与功能', agent: 'ProductAgent' },
      { key: 'pricing_analysis', label: '定价与套餐', agent: 'PricingAgent' },
      { key: 'market_analysis', label: '市场与定位', agent: 'MarketAgent' },
    ],
    checkpoint: {
      label: '三维结论检查',
      targets: ['product_analysis', 'pricing_analysis', 'market_analysis'],
    },
  },
  {
    number: 4,
    key: 'strategy',
    title: '形成策略报告',
    purpose: '综合证据和三维分析，输出可执行的竞争策略与行动优先级。',
    deliverable: '竞争策略报告',
    agents: [{ key: 'strategy', label: '策略综合', agent: 'StrategyAgent' }],
    checkpoint: { label: '交付一致性检查', targets: ['strategy'] },
  },
];

function formatTiming(value) {
  return Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}s` : undefined;
}

function StageConnector({ status }) {
  return (
    <div className="stage-connector" data-status={status} aria-hidden="true">
      <i />
      <ArrowDownOutlined />
    </div>
  );
}

function StageAgents({ stage, nodeStates, timings, onNodeClick }) {
  const className = stage.parallel
    ? 'stage-agent-grid stage-agent-grid-parallel'
    : `stage-agent-grid stage-agent-grid-${stage.agents.length}`;

  return (
    <div className={className}>
      {stage.parallel && <span className="stage-parallel-label"><BranchesOutlined /> 三路并行</span>}
      {stage.agents.map((agent) => (
        <AgentNode
          key={agent.key}
          label={agent.label}
          agent={agent.agent}
          status={nodeStates[agent.key] || 'waiting'}
          timing={formatTiming(timings?.[agent.key])}
          onClick={() => onNodeClick?.(agent.key)}
        />
      ))}
    </div>
  );
}

function WorkflowStage({ stage, nodeStates, qaSummaries, timings, taskStatus, qaDisabled, onNodeClick }) {
  const status = deriveStageStatus(
    stage.agents.map(agent => agent.key),
    nodeStates,
    taskStatus,
  );
  const statusLabel = {
    completed: '已完成',
    running: '进行中',
    retrying: '重试中',
    failed: '需处理',
    waiting: '等待中',
  }[status] || '等待中';

  return (
    <section className="workflow-stage" data-status={status} aria-labelledby={`stage-${stage.key}-title`}>
      <div className="workflow-stage-rail" aria-hidden="true">
        <span className="workflow-stage-index">{stage.number}</span>
      </div>
      <div className="workflow-stage-panel">
        <header className="workflow-stage-header">
          <div>
            <span className="workflow-stage-kicker">阶段 {stage.number}</span>
            <h3 id={`stage-${stage.key}-title`}>{stage.title}</h3>
            <p>{stage.purpose}</p>
          </div>
          <span className="workflow-stage-status">{statusLabel}</span>
        </header>
        <div className="workflow-stage-deliverable">
          <span>阶段产物</span>
          <strong>{stage.deliverable}</strong>
        </div>
        <StageAgents stage={stage} nodeStates={nodeStates} timings={timings} onNodeClick={onNodeClick} />
        {stage.checkpoint && (
          <div className="stage-checkpoint">
            <span>QA checkpoint</span>
            <QAGate
              label={stage.checkpoint.label}
              targets={stage.checkpoint.targets}
              qaSummaries={qaSummaries}
              disabled={qaDisabled}
            />
          </div>
        )}
      </div>
    </section>
  );
}

export default function PipelineGraph({
  nodeStates = {},
  qaSummaries = {},
  timings = {},
  taskStatus,
  qaDisabled = false,
  onNodeClick,
}) {
  return (
    <div className="pipeline-graph pipeline-stage-flow">
      <div className="pipeline-legend" aria-label="状态说明">
        <span><i className="legend-waiting" /> 等待</span>
        <span><i className="legend-running" /> 运行</span>
        <span><i className="legend-completed" /> 完成</span>
        <span><i className="legend-retrying" /> 重试 / 降级</span>
        <span><i className="legend-failed" /> 失败</span>
        {qaDisabled && <span><i className="legend-disabled" /> QA 已关闭</span>}
      </div>
      {STAGES.map((stage, index) => {
        const status = deriveStageStatus(
          stage.agents.map(agent => agent.key),
          nodeStates,
          taskStatus,
        );
        return (
          <div className="workflow-stage-flow-item" key={stage.key}>
            <WorkflowStage
              stage={stage}
              nodeStates={nodeStates}
              qaSummaries={qaSummaries}
              timings={timings}
              taskStatus={taskStatus}
              qaDisabled={qaDisabled}
              onNodeClick={onNodeClick}
            />
            {index < STAGES.length - 1 && <StageConnector status={status} />}
          </div>
        );
      })}
    </div>
  );
}
