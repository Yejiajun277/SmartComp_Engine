import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Empty, Spin } from 'antd';
import {
  ArrowLeftOutlined,
  DownloadOutlined,
  ExportOutlined,
  FileDoneOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { getReport, getTask } from '../api/client';
import ReportOverview from '../components/report/ReportOverview';
import { buildReportOverview } from '../utils/report';
import { getTaskLoadFailureAction } from '../utils/taskNavigation';

const REPORT_VIEWS = [
  { key: 'overview', label: '决策简报' },
  { key: 'full', label: '完整报告' },
  { key: 'json', label: 'JSON 数据' },
];

export default function ReportView() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState('overview');
  const [iframeLoading, setIframeLoading] = useState(true);
  const [iframeKey, setIframeKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getReport(taskId)
      .then((data) => {
        if (!cancelled) setReport(data);
      })
      .catch(async (error) => {
        if (getTaskLoadFailureAction(error) !== 'redirect_home') {
          if (!cancelled) setReport(null);
          return;
        }

        try {
          await getTask(taskId);
          if (!cancelled) setReport(null);
        } catch (taskError) {
          if (!cancelled && getTaskLoadFailureAction(taskError) === 'redirect_home') {
            navigate('/', { replace: true });
          } else if (!cancelled) {
            setReport(null);
          }
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [navigate, taskId]);

  const handleViewChange = (nextView) => {
    if (nextView === 'full') setIframeLoading(true);
    setView(nextView);
  };

  const handleDownloadJson = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    const safeName = (report.product_name || 'report').replace(/[\\/:*?"<>|]/g, '-');
    anchor.href = url;
    anchor.download = `${safeName}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const handleReloadIframe = () => {
    setIframeLoading(true);
    setIframeKey(current => current + 1);
  };

  if (loading) {
    return (
      <main className="page-shell report-loading-state">
        <Spin size="large" />
        <p>正在装载策略报告…</p>
      </main>
    );
  }

  if (!report) {
    return (
      <main className="page-shell report-empty-state">
        <Empty description="报告暂不可用" />
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/tasks/${taskId}`)}>
          返回工作台
        </Button>
      </main>
    );
  }

  const overview = buildReportOverview(report);
  const iframeUrl = `/api/tasks/${taskId}/report.html`;

  return (
    <main className="page-shell report-page">
      <Button
        className="workbench-back"
        type="text"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate(`/tasks/${taskId}`)}
      >
        返回 Agent 工作台
      </Button>

      <header className="surface-card report-header">
        <div className="report-heading-copy">
          <span className="section-eyebrow">Strategy report</span>
          <h1>{overview.productName}</h1>
          <p>竞品策略分析报告 · 决策、证据与质量修正链</p>
        </div>
        <div className="report-heading-actions">
          <span className="report-ready-pill"><FileDoneOutlined /> 报告已生成</span>
          <Button icon={<DownloadOutlined />} onClick={handleDownloadJson}>
            下载 JSON
          </Button>
        </div>
      </header>

      <nav className="report-view-tabs" aria-label="报告视图">
        <div>
          {REPORT_VIEWS.map(item => (
            <button
              type="button"
              aria-pressed={view === item.key}
              className={view === item.key ? 'is-active' : ''}
              key={item.key}
              onClick={() => handleViewChange(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
        {view === 'full' && (
          <a href={iframeUrl} target="_blank" rel="noreferrer">
            <ExportOutlined /> 在新窗口打开
          </a>
        )}
      </nav>

      {view === 'overview' && (
        <ReportOverview report={report} onReadFull={() => handleViewChange('full')} />
      )}

      {view === 'full' && (
        <section className="surface-card full-report-panel" aria-labelledby="full-report-title">
          <header>
            <div>
              <span className="section-eyebrow">Full analysis</span>
              <h2 id="full-report-title">完整分析</h2>
            </div>
            <p>由 StrategyAgent 汇总生成的完整 HTML 报告</p>
          </header>
          <div className="report-iframe-wrap">
            {iframeLoading && (
              <div className="report-iframe-loading">
                <Spin />
                <span>正在载入完整报告…</span>
              </div>
            )}
            <iframe
              key={iframeKey}
              src={iframeUrl}
              title={`${overview.productName} 竞品分析报告`}
              onLoad={() => setIframeLoading(false)}
              onError={() => setIframeLoading(false)}
            />
          </div>
          <p className="report-iframe-fallback">
            如果嵌入内容未正常显示，请
            <a href={iframeUrl} target="_blank" rel="noreferrer">在新窗口打开完整报告</a>
            或
            <button type="button" onClick={handleReloadIframe}>重新载入</button>。
          </p>
        </section>
      )}

      {view === 'json' && (
        <section className="surface-card report-json-panel" aria-labelledby="report-json-title">
          <header>
            <div>
              <span className="section-eyebrow">Structured data</span>
              <h2 id="report-json-title"><FileTextOutlined /> JSON 数据</h2>
            </div>
            <p>供技术检查、二次处理与归档使用</p>
          </header>
          <pre>{JSON.stringify(report, null, 2)}</pre>
        </section>
      )}
    </main>
  );
}
