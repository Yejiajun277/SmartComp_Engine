import {
  CheckCircleOutlined,
  HourglassOutlined,
  LoadingOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { getGateState } from '../utils/quality';

const GATE_META = {
  waiting: { icon: <HourglassOutlined />, title: '等待质检' },
  disabled: { icon: <StopOutlined />, title: '质量检查已关闭' },
  running: { icon: <LoadingOutlined spin />, title: 'QualityAgent 正在检查' },
  failed: { icon: <WarningOutlined />, title: '需要修正' },
  degraded: { icon: <SafetyCertificateOutlined />, title: '降级交付' },
  passed: { icon: <CheckCircleOutlined />, title: '质量门通过' },
};

const TARGET_AGENT_NAMES = {
  collection: 'CollectionAgent',
  product_analysis: 'ProductAgent',
  pricing_analysis: 'PricingAgent',
  market_analysis: 'MarketAgent',
  strategy: 'StrategyAgent',
};

export default function QAGate({ label, targets, qaSummaries, disabled = false }) {
  const state = getGateState(targets, qaSummaries, { disabled });
  const meta = GATE_META[state.status] || GATE_META.waiting;
  const targetNames = targets.map(target => TARGET_AGENT_NAMES[target] || target);

  return (
    <article
      className="qa-gate"
      data-status={state.status}
      aria-label={`${label}，QualityAgent，${state.label}`}
    >
      <div className="qa-gate-icon" aria-hidden="true">{meta.icon}</div>
      <div className="qa-gate-copy">
        <span className="qa-gate-kicker">QUALITY GATE</span>
        <strong>{label}</strong>
        <small>QualityAgent · {meta.title}</small>
      </div>
      <div className="qa-gate-result">
        <span>{state.label}</span>
        {state.score != null && <small>最低得分 {Math.round(state.score)}</small>}
      </div>
      {state.status === 'failed' && (
        <p className="qa-correction-note">
          已打回 {targetNames.join(' / ')}，等待按反馈修正后重新检查。
        </p>
      )}
      {state.status === 'degraded' && (
        <p className="qa-correction-note">
          已保留风险标记，报告中的相关结论需要人工复核。
        </p>
      )}
    </article>
  );
}
