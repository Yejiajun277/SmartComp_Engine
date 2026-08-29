import { ArrowDownOutlined, ArrowRightOutlined, BranchesOutlined } from '@ant-design/icons';
import AgentNode from './AgentNode';
import QAGate from './QAGate';
import { getGateState } from '../utils/quality';

const PIPELINE = [
  { type: 'agent', key: 'discovery', label: '竞品发现', agent: 'DiscoveryAgent' },
  { type: 'agent', key: 'collection', label: '证据采集', agent: 'CollectionAgent' },
  { type: 'qa', key: 'qa_collection', label: '采集质量门', targets: ['collection'] },
  { type: 'agent', key: 'dimension', label: '维度配置', agent: 'DimensionAgent' },
  {
    type: 'parallel',
    key: 'parallel_analysis',
    nodes: [
      { key: 'product_analysis', label: '功能分析', agent: 'ProductAgent' },
      { key: 'pricing_analysis', label: '定价分析', agent: 'PricingAgent' },
      { key: 'market_analysis', label: '市场分析', agent: 'MarketAgent' },
    ],
  },
  {
    type: 'qa',
    key: 'qa_analysis',
    label: '三维分析质量门',
    targets: ['product_analysis', 'pricing_analysis', 'market_analysis'],
  },
  { type: 'agent', key: 'strategy', label: '策略综合', agent: 'StrategyAgent' },
  { type: 'qa', key: 'qa_strategy', label: '交付质量门', targets: ['strategy'] },
];

function formatTiming(value) {
  return Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}s` : undefined;
}

function stageIsComplete(stage, nodeStates, qaSummaries) {
  if (stage.type === 'agent') return nodeStates[stage.key] === 'completed';
  if (stage.type === 'parallel') {
    return stage.nodes.every(node => nodeStates[node.key] === 'completed');
  }
  const status = getGateState(stage.targets, qaSummaries).status;
  return status === 'passed' || status === 'degraded';
}

function PipelineConnector({ active }) {
  return (
    <span className="pipeline-connector" data-active={active} aria-hidden="true">
      <i />
      <ArrowRightOutlined />
    </span>
  );
}

function ParallelGroup({ stage, nodeStates, timings, onNodeClick }) {
  const statuses = stage.nodes.map(node => nodeStates[node.key] || 'waiting');
  const groupStatus = statuses.includes('failed')
    ? 'failed'
    : statuses.some(status => status === 'running' || status === 'retrying')
      ? 'running'
      : statuses.every(status => status === 'completed')
        ? 'completed'
        : 'waiting';

  return (
    <section className="parallel-agent-group" data-status={groupStatus}>
      <header>
        <span><BranchesOutlined /> PARALLEL TRACK</span>
        <strong>三路并行研判</strong>
      </header>
      <div className="parallel-agent-nodes">
        {stage.nodes.map(node => (
          <AgentNode
            key={node.key}
            label={node.label}
            agent={node.agent}
            status={nodeStates[node.key] || 'waiting'}
            timing={formatTiming(timings?.[node.key])}
            onClick={() => onNodeClick?.(node.key)}
          />
        ))}
      </div>
    </section>
  );
}

function PipelineStage({ stage, nodeStates, qaSummaries, timings, onNodeClick }) {
  if (stage.type === 'parallel') {
    return (
      <ParallelGroup
        stage={stage}
        nodeStates={nodeStates}
        timings={timings}
        onNodeClick={onNodeClick}
      />
    );
  }

  if (stage.type === 'qa') {
    return <QAGate label={stage.label} targets={stage.targets} qaSummaries={qaSummaries} />;
  }

  return (
    <AgentNode
      label={stage.label}
      agent={stage.agent}
      status={nodeStates[stage.key] || 'waiting'}
      timing={formatTiming(timings?.[stage.key])}
      onClick={() => onNodeClick?.(stage.key)}
    />
  );
}

function PipelineRow({ stages, nodeStates, qaSummaries, timings, onNodeClick }) {
  return (
    <div className="pipeline-row">
      {stages.map((stage, index) => (
        <div className="pipeline-row-item" key={stage.key}>
          {index > 0 && (
            <PipelineConnector
              active={stageIsComplete(stages[index - 1], nodeStates, qaSummaries)}
            />
          )}
          <PipelineStage
            stage={stage}
            nodeStates={nodeStates}
            qaSummaries={qaSummaries}
            timings={timings}
            onNodeClick={onNodeClick}
          />
        </div>
      ))}
    </div>
  );
}

export default function PipelineGraph({
  nodeStates = {},
  qaSummaries = {},
  timings = {},
  onNodeClick,
}) {
  const primaryStages = PIPELINE.slice(0, 4);
  const analysisStages = PIPELINE.slice(4, 6);
  const deliveryStages = PIPELINE.slice(6);

  return (
    <div className="pipeline-graph">
      <div className="pipeline-legend">
        <span><i className="legend-agent" /> 业务 Agent</span>
        <span><i className="legend-gate" /> QualityAgent 质量门</span>
        <span><i className="legend-return" /> 打回后重做</span>
      </div>

      <PipelineRow
        stages={primaryStages}
        nodeStates={nodeStates}
        qaSummaries={qaSummaries}
        timings={timings}
        onNodeClick={onNodeClick}
      />

      <div
        className="pipeline-row-bridge"
        data-active={stageIsComplete(primaryStages.at(-1), nodeStates, qaSummaries)}
      >
        <span>维度确认后进入并行研判</span>
        <ArrowDownOutlined />
      </div>

      <PipelineRow
        stages={analysisStages}
        nodeStates={nodeStates}
        qaSummaries={qaSummaries}
        timings={timings}
        onNodeClick={onNodeClick}
      />

      <div
        className="pipeline-row-bridge"
        data-active={stageIsComplete(analysisStages.at(-1), nodeStates, qaSummaries)}
      >
        <span>质量门通过后形成最终策略</span>
        <ArrowDownOutlined />
      </div>

      <PipelineRow
        stages={deliveryStages}
        nodeStates={nodeStates}
        qaSummaries={qaSummaries}
        timings={timings}
        onNodeClick={onNodeClick}
      />
    </div>
  );
}
