import { aggregateQuality } from '../../utils/quality';

function MetricCard({ label, value, hint, tone = 'neutral' }) {
  return (
    <article className="quality-metric" data-tone={tone}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </article>
  );
}

function formatRate(value) {
  return value == null ? '待质检' : `${value.toFixed(1)}%`;
}

export default function QualityCockpit({ checks = [] }) {
  const summary = aggregateQuality(checks);

  return (
    <section className="surface-card quality-cockpit" aria-labelledby="quality-cockpit-title">
      <header className="quality-cockpit-header">
        <div>
          <span className="section-eyebrow">Quality cockpit</span>
          <h2 id="quality-cockpit-title">质量驾驶舱</h2>
        </div>
        <p>按每个阶段最新一轮质检加权统计</p>
      </header>

      <div className="quality-metric-grid">
        <MetricCard
          label="准确率"
          value={formatRate(summary.accuracyRate)}
          hint="越高越可信"
          tone="positive"
        />
        <MetricCard
          label="覆盖率"
          value={formatRate(summary.coverageRate)}
          hint="越高越完整"
          tone="positive"
        />
        <MetricCard
          label="修正率"
          value={formatRate(summary.correctionRate)}
          hint="反映 QA 纠偏幅度"
          tone="attention"
        />
        <MetricCard
          label="QA 检查"
          value={summary.totalChecks}
          hint="已完成轮次"
        />
        <MetricCard
          label="打回次数"
          value={summary.retryCount}
          hint="未通过后重做"
          tone={summary.retryCount > 0 ? 'attention' : 'neutral'}
        />
        <MetricCard
          label="降级通过"
          value={summary.degradedCount}
          hint="建议人工复核"
          tone={summary.degradedCount > 0 ? 'danger' : 'neutral'}
        />
      </div>
    </section>
  );
}
