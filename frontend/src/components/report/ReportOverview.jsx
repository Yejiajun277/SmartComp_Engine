import { Button } from 'antd';
import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  FileSearchOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { buildReportOverview } from '../../utils/report';

const QA_STATUS_META = {
  passed: { label: '最终质检通过', tone: 'passed', hint: '各阶段最新轮次无未解决失败' },
  degraded: { label: '降级通过', tone: 'degraded', hint: '保留风险，建议人工复核相关结论' },
  failed: { label: '存在未解决问题', tone: 'failed', hint: '最新质检仍有未修正项' },
  unknown: { label: '状态待确认', tone: 'unknown', hint: '报告未提供可判断的 QA 记录' },
};

function TrustCard({ icon, label, value, hint, tone = 'neutral' }) {
  return (
    <article className="report-trust-card" data-tone={tone}>
      <span className="report-trust-icon" aria-hidden="true">{icon}</span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
        <p>{hint}</p>
      </div>
    </article>
  );
}

export default function ReportOverview({ report, onReadFull }) {
  const overview = buildReportOverview(report);
  const qaStatus = QA_STATUS_META[overview.qaStatus];

  return (
    <div className="report-overview">
      <section className="report-positioning">
        <div>
          <span className="section-eyebrow">Strategic position</span>
          <h2>核心定位</h2>
          {overview.positioning ? (
            <blockquote>{overview.positioning}</blockquote>
          ) : (
            <p className="report-empty-copy">报告暂未提供整体定位，建议进入完整分析核对分维度结论。</p>
          )}
        </div>
        <span className="report-positioning-mark" aria-hidden="true">SC</span>
      </section>

      <section className="report-action-section" aria-labelledby="report-actions-title">
        <header>
          <div>
            <span className="section-eyebrow">Priority actions</span>
            <h2 id="report-actions-title">优先行动</h2>
          </div>
          <p>按 P0 → P3 排序，先展示最需要执行的三项</p>
        </header>

        {overview.actions.length > 0 ? (
          <div className="report-action-grid">
            {overview.actions.map((item, index) => (
              <article className="report-action-card" data-priority={item.priority || 'NA'} key={`${item.priority || 'action'}-${index}`}>
                <div className="report-action-index">
                  <span>{item.priority || '—'}</span>
                  <small>{String(index + 1).padStart(2, '0')}</small>
                </div>
                <h3>{item.action || '该行动项未提供描述'}</h3>
                <dl>
                  <div>
                    <dt>时间范围</dt>
                    <dd>{item.timeline || '未说明'}</dd>
                  </div>
                  <div>
                    <dt>预期影响</dt>
                    <dd>{item.expected_impact || '未说明'}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        ) : (
          <div className="report-actions-empty">
            当前报告没有结构化行动项，可在完整分析中查看其他策略内容。
          </div>
        )}
      </section>

      <section className="report-trust-section" aria-labelledby="report-trust-title">
        <header>
          <div>
            <span className="section-eyebrow">Evidence & quality</span>
            <h2 id="report-trust-title">可信度证据</h2>
          </div>
          <p>只展示报告中实际存在的竞品、引用与 QA 记录</p>
        </header>
        <div className="report-trust-grid">
          <TrustCard
            icon={<TeamOutlined />}
            label="竞品范围"
            value={overview.competitorCount > 0 ? overview.competitorCount : '未记录'}
            hint={overview.competitorCount > 0 ? '纳入最终比较' : '报告未提供数量'}
          />
          <TrustCard
            icon={<FileSearchOutlined />}
            label="可信引用"
            value={overview.citationCount}
            hint={overview.citationCount > 0 ? '可回溯来源' : '未提供引用索引'}
          />
          <TrustCard
            icon={<SafetyCertificateOutlined />}
            label="QA 检查"
            value={overview.qaCheckCount}
            hint={overview.qaCheckCount > 0 ? '包含历史打回记录' : '未提供质检记录'}
          />
          <TrustCard
            icon={overview.qaStatus === 'passed' ? <CheckCircleOutlined /> : <SafetyCertificateOutlined />}
            label="最终状态"
            value={qaStatus.label}
            hint={qaStatus.hint}
            tone={qaStatus.tone}
          />
        </div>
      </section>

      {onReadFull && (
        <div className="report-overview-cta">
          <div>
            <strong>需要完整论证与分维度细节？</strong>
            <p>继续阅读功能、定价、市场、SWOT、风险与引用附录。</p>
          </div>
          <Button
            className="primary-action"
            type="primary"
            icon={<ArrowRightOutlined />}
            onClick={onReadFull}
          >
            阅读完整分析
          </Button>
        </div>
      )}
    </div>
  );
}
