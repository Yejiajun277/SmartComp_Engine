import { Space } from 'antd';
import AgentNode from './AgentNode';

const PIPELINE = [
  { key: 'discovery', label: '竞品发现', agent: 'DiscoveryAgent' },
  { key: 'collection', label: '数据采集', agent: 'CollectionAgent' },
  { key: 'dimension', label: '维度配置', agent: 'DimensionAgent' },
  { key: 'product_analysis', label: '功能分析', agent: 'ProductAgent' },
  { key: 'pricing_analysis', label: '定价分析', agent: 'PricingAgent' },
  { key: 'market_analysis', label: '市场分析', agent: 'MarketAgent' },
  { key: 'strategy', label: '报告生成', agent: 'StrategyAgent' },
];

function Arrow({ active }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      color: active ? '#1890ff' : '#d9d9d9',
      fontSize: 24,
      padding: '0 4px',
    }}>
      →
    </div>
  );
}

export default function PipelineGraph({ nodeStates, timings, onNodeClick }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexWrap: 'wrap',
      gap: 4,
      padding: '16px 0',
    }}>
      {PIPELINE.map((node, i) => {
        const status = nodeStates[node.key] || 'waiting';
        const prevStatus = i > 0 ? nodeStates[PIPELINE[i - 1].key] : 'completed';
        const timing = timings?.[node.key];

        return (
          <div key={node.key} style={{ display: 'flex', alignItems: 'center' }}>
            {i > 0 && <Arrow active={prevStatus === 'completed'} />}
            <AgentNode
              label={node.label}
              agent={node.agent}
              status={status}
              timing={timing ? `${(timing).toFixed(1)}s` : undefined}
              onClick={() => onNodeClick?.(node.key)}
            />
          </div>
        );
      })}
    </div>
  );
}
