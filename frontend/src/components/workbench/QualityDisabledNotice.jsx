import { StopOutlined } from '@ant-design/icons';

export default function QualityDisabledNotice() {
  return (
    <section className="surface-card quality-disabled-notice" aria-labelledby="quality-disabled-title">
      <span className="quality-disabled-icon" aria-hidden="true"><StopOutlined /></span>
      <div>
        <span className="section-eyebrow">Quality checkpoint closed</span>
        <h2 id="quality-disabled-title">质量检查已关闭</h2>
        <p>业务 Agent 会直接继续完成分析和策略报告；本任务不会生成 QA 评分或修正记录。</p>
        <small>模型调用、输入输出和阶段产物仍可在下方技术追溯与各 Agent 详情中查看。</small>
      </div>
    </section>
  );
}
