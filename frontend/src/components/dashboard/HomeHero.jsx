const PROOF_POINTS = [
  '7 个业务 Agent + QualityAgent',
  '功能 / 定价 / 市场并行研判',
  '结论保留引用与修正链',
];

const EXAMPLES = ['飞书', 'Notion', '小米汽车'];

const AGENT_NODES = [
  { key: 'discovery', label: '发现', className: 'agent-map-node-discovery' },
  { key: 'collection', label: '证据', className: 'agent-map-node-collection' },
  { key: 'product', label: '功能', className: 'agent-map-node-product' },
  { key: 'pricing', label: '定价', className: 'agent-map-node-pricing' },
  { key: 'market', label: '市场', className: 'agent-map-node-market' },
  { key: 'quality', label: 'QA', className: 'agent-map-node-quality' },
];

export default function HomeHero({ onExampleSelect }) {
  return (
    <section className="surface-card home-hero" aria-labelledby="home-hero-title">
      <div className="home-hero-copy">
        <span className="section-eyebrow">可核验竞品策略生成引擎</span>
        <h1 id="home-hero-title">
          把竞品分析交给一支
          <span>会互相质检的 Agent 团队</span>
        </h1>
        <p className="home-hero-lead">
          从竞争边界到行动策略，每一步都实时可见；被 QA 打回的结论会重做，最终报告保留可信引用链。
        </p>

        <ul className="hero-proof-list" aria-label="系统能力">
          {PROOF_POINTS.map(point => <li key={point}>{point}</li>)}
        </ul>

        <div className="hero-examples">
          <span>快速体验</span>
          {EXAMPLES.map(example => (
            <button type="button" key={example} onClick={() => onExampleSelect(example)}>
              {example}
            </button>
          ))}
        </div>
      </div>

      <div className="hero-system-map" aria-label="多智能体协作拓扑示意">
        <div className="agent-map-meta">
          <span><i /> LIVE WORKFLOW</span>
          <strong>协作推演中</strong>
        </div>
        <div className="agent-map-orbit" aria-hidden="true">
          <span className="agent-map-ring agent-map-ring-outer" />
          <span className="agent-map-ring agent-map-ring-inner" />
          <span className="agent-map-core">
            <small>FINAL</small>
            <strong>策略</strong>
          </span>
          {AGENT_NODES.map(node => (
            <span className={`agent-map-node ${node.className}`} key={node.key}>
              {node.label}
            </span>
          ))}
        </div>
        <p><span>Quality gate</span> 校验事实、完整性与引用覆盖</p>
      </div>
    </section>
  );
}
