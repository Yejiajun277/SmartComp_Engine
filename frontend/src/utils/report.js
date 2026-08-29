const PRIORITY_ORDER = new Map([
  ['P0', 0],
  ['P1', 1],
  ['P2', 2],
  ['P3', 3],
]);

function countCitations(citationIndex) {
  const citations = citationIndex?.citations;
  if (Array.isArray(citations)) return citations.length;
  if (citations && typeof citations === 'object') return Object.keys(citations).length;
  return 0;
}

function getLatestCompletedChecks(checks) {
  const latestByPhase = new Map();

  checks.forEach((check) => {
    if (!check || check.running) return;
    latestByPhase.set(check.phase || '__unknown', check);
  });

  return Array.from(latestByPhase.values());
}

function getQaStatus(checks) {
  const latestChecks = getLatestCompletedChecks(checks);
  if (latestChecks.some(check => check.passed === false && !check.degraded)) return 'failed';
  if (latestChecks.some(check => check.degraded)) return 'degraded';
  if (latestChecks.some(check => check.passed === true)) return 'passed';
  return 'unknown';
}

function prioritizeActions(actions) {
  return actions
    .map((action, index) => ({ ...action, _sourceIndex: index }))
    .sort((left, right) => {
      const leftRank = PRIORITY_ORDER.get(left.priority) ?? Number.MAX_SAFE_INTEGER;
      const rightRank = PRIORITY_ORDER.get(right.priority) ?? Number.MAX_SAFE_INTEGER;
      return leftRank - rightRank || left._sourceIndex - right._sourceIndex;
    })
    .slice(0, 3)
    .map((action) => {
      const output = { ...action };
      delete output._sourceIndex;
      return output;
    });
}

export function buildReportOverview(report = {}) {
  const checks = Array.isArray(report.qa_timeline?.checks) ? report.qa_timeline.checks : [];
  const actions = Array.isArray(report.action_plan) ? report.action_plan : [];

  return {
    productName: report.product_name || '未命名报告',
    competitorCount: Number.isFinite(Number(report.competitor_count))
      ? Number(report.competitor_count)
      : 0,
    positioning: typeof report.overall_positioning === 'string'
      ? report.overall_positioning
      : '',
    actions: prioritizeActions(actions),
    citationCount: countCitations(report.citation_index),
    qaCheckCount: checks.length,
    qaStatus: getQaStatus(checks),
  };
}
