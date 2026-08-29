const GATE_PRIORITY = ['running', 'failed', 'degraded', 'passed', 'waiting'];

function roundRate(value) {
  return Math.round(value * 10) / 10;
}

function weightedRate(checks, field) {
  const validChecks = checks.filter(check => (
    Number(check.total_fields) > 0 && Number.isFinite(Number(check[field]))
  ));
  const totalFields = validChecks.reduce((total, check) => total + Number(check.total_fields), 0);

  if (totalFields === 0) return null;
  const weightedTotal = validChecks.reduce(
    (total, check) => total + (Number(check[field]) * Number(check.total_fields)),
    0,
  );
  return roundRate(weightedTotal / totalFields);
}

export function aggregateQuality(checks = []) {
  const completedChecks = checks.filter(check => check && !check.running);
  const latestByPhase = new Map();

  completedChecks.forEach((check) => {
    if (check.phase) latestByPhase.set(check.phase, check);
  });

  const latestChecks = Array.from(latestByPhase.values());
  const correctionFields = latestChecks.filter(check => Number(check.total_fields) > 0);
  const totalCorrectionFields = correctionFields.reduce(
    (total, check) => total + Number(check.total_fields),
    0,
  );
  const totalCorrections = correctionFields.reduce(
    (total, check) => total + (Number(check.correction_count) || 0),
    0,
  );

  return {
    totalChecks: completedChecks.length,
    retryCount: completedChecks.filter(check => check.passed === false && !check.degraded).length,
    degradedCount: completedChecks.filter(check => check.degraded).length,
    issueCount: completedChecks.reduce(
      (total, check) => total + (Array.isArray(check.issues) ? check.issues.length : 0),
      0,
    ),
    accuracyRate: weightedRate(latestChecks, 'accuracy_rate'),
    coverageRate: weightedRate(latestChecks, 'coverage_rate'),
    correctionRate: totalCorrectionFields > 0
      ? roundRate((totalCorrections / totalCorrectionFields) * 100)
      : null,
    latestChecks,
  };
}

export function getGateState(targetKeys = [], qaSummaries = {}) {
  const summaries = targetKeys
    .map(target => ({ target, summary: qaSummaries?.[target] }))
    .filter(item => item.summary);

  const status = GATE_PRIORITY.find(candidate => (
    summaries.some(item => item.summary.status === candidate)
  )) || 'waiting';
  const retryCount = summaries.reduce(
    (total, item) => total + (Number(item.summary.retryCount) || 0),
    0,
  );
  const scores = summaries
    .map(item => Number(item.summary.score))
    .filter(Number.isFinite);
  const score = scores.length > 0 ? Math.min(...scores) : null;

  const labels = {
    running: '质检中',
    failed: retryCount > 0 ? `未通过 · 已打回 ${retryCount} 次` : '未通过 · 等待修正',
    degraded: retryCount > 0 ? `降级通过 · 打回 ${retryCount} 次` : '降级通过',
    passed: score != null ? `已通过 · ${Math.round(score)} 分` : '已通过',
    waiting: '等待质检',
  };

  return {
    status,
    label: labels[status],
    score,
    retryCount,
    targets: targetKeys,
  };
}
