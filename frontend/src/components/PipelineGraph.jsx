import AgentNode from './AgentNode';

// Each stage is an array of nodes; multi-node stages run in parallel
const PIPELINE = [
  [{ key: 'discovery', label: '竞品发现', agent: 'DiscoveryAgent' }],
  [{ key: 'collection', label: '数据采集', agent: 'CollectionAgent' }],
  [{ key: 'dimension', label: '维度配置', agent: 'DimensionAgent' }],
  [
    { key: 'product_analysis', label: '功能分析', agent: 'ProductAgent' },
    { key: 'pricing_analysis', label: '定价分析', agent: 'PricingAgent' },
    { key: 'market_analysis', label: '市场分析', agent: 'MarketAgent' },
  ],
  [{ key: 'strategy', label: '报告生成', agent: 'StrategyAgent' }],
];

const QA_ENABLED_PHASES = new Set([
  'collection',
  'product_analysis',
  'pricing_analysis',
  'market_analysis',
  'strategy',
]);

function getQaStatus(nodeKey, qaSummaries) {
  if (qaSummaries?.[nodeKey]) return qaSummaries[nodeKey];
  if (QA_ENABLED_PHASES.has(nodeKey)) return { label: '等待', status: 'none' };
  return null;
}

function Arrow({ active }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: active ? '#1890ff' : '#d9d9d9',
      fontSize: 24,
      padding: '0 8px',
      flexShrink: 0,
    }}>
      →
    </div>
  );
}

function ParallelGroup({ nodes, nodeStates, qaSummaries, timings, onNodeClick }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      padding: '8px 12px',
      border: '1.5px dashed #b7eb8f',
      borderRadius: 12,
      background: '#f6ffed40',
      position: 'relative',
    }}>
      <span style={{
        position: 'absolute',
        top: -10,
        left: 12,
        background: '#fff',
        padding: '0 6px',
        fontSize: 11,
        color: '#52c41a',
        fontWeight: 600,
      }}>
        并行
      </span>
      {nodes.map(node => {
        const status = nodeStates[node.key] || 'waiting';
        const timing = timings?.[node.key];
        return (
          <AgentNode
            key={node.key}
            label={node.label}
            agent={node.agent}
            status={status}
            qaStatus={getQaStatus(node.key, qaSummaries)}
            timing={timing ? `${timing.toFixed(1)}s` : undefined}
            onClick={() => onNodeClick?.(node.key)}
          />
        );
      })}
    </div>
  );
}

export default function PipelineGraph({ nodeStates, qaSummaries, timings, onNodeClick }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexWrap: 'wrap',
      gap: 4,
      padding: '16px 0',
    }}>
      {PIPELINE.map((stage, i) => {
        const isParallel = stage.length > 1;
        // Determine if the previous stage is fully completed for arrow highlighting
        const prevStage = i > 0 ? PIPELINE[i - 1] : null;
        const prevCompleted = prevStage
          ? prevStage.every(n => nodeStates[n.key] === 'completed')
          : true;

        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
            {i > 0 && <Arrow active={prevCompleted} />}
            {isParallel ? (
              <ParallelGroup
                nodes={stage}
                nodeStates={nodeStates}
                qaSummaries={qaSummaries}
                timings={timings}
                onNodeClick={onNodeClick}
              />
            ) : (
              <AgentNode
                label={stage[0].label}
                agent={stage[0].agent}
                status={nodeStates[stage[0].key] || 'waiting'}
                qaStatus={getQaStatus(stage[0].key, qaSummaries)}
                timing={timings?.[stage[0].key] ? `${timings[stage[0].key].toFixed(1)}s` : undefined}
                onClick={() => onNodeClick?.(stage[0].key)}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
