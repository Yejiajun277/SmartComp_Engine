function getQaAttemptKey(result = {}) {
  if (!result.phase) return null;
  return [
    result.phase,
    result.target_agent || '',
    result.attempt ?? 'unknown',
  ].join('::');
}

export function shouldAcceptTaskEvent(event, taskId, connectionClosed = false) {
  if (connectionClosed || !taskId || !event || event.type === 'ping') return false;
  return event.task_id === taskId;
}

function getQaResultRank(result = {}) {
  if (result.running) return 0;
  if (result.degraded || result.passed) return 2;
  return 1;
}

function isTerminalQaSummary(summary = {}) {
  return ['failed', 'degraded', 'passed'].includes(summary.status);
}

function hasHigherAttempt(live = {}, persisted = {}) {
  const liveAttempt = getKnownAttempt(live.attempt);
  const persistedAttempt = getKnownAttempt(persisted.attempt);

  return liveAttempt !== null
    && persistedAttempt !== null
    && liveAttempt > persistedAttempt;
}

function getKnownAttempt(value) {
  if (value === null || value === undefined || value === '') return null;
  const attempt = Number(value);
  return Number.isFinite(attempt) ? attempt : null;
}

export function mergeQaSummaries(persisted = {}, live = {}) {
  const merged = { ...persisted };

  Object.entries(live || {}).forEach(([target, liveSummary]) => {
    const persistedSummary = persisted?.[target];

    if (
      persistedSummary
      && isTerminalQaSummary(persistedSummary)
      && liveSummary?.status === 'running'
      && !hasHigherAttempt(liveSummary, persistedSummary)
    ) {
      return;
    }

    merged[target] = liveSummary;
  });

  return merged;
}

export function upsertQaResult(results = [], incoming) {
  if (!incoming) return results;
  const incomingKey = getQaAttemptKey(incoming);
  if (!incomingKey) return [...results, incoming];

  const existingIndex = results.findIndex(result => getQaAttemptKey(result) === incomingKey);
  if (existingIndex < 0) return [...results, incoming];

  const existing = results[existingIndex];
  if (getQaResultRank(incoming) < getQaResultRank(existing)) return results;

  const nextResults = [...results];
  nextResults[existingIndex] = { ...existing, ...incoming };
  return nextResults;
}

function getEventIdentity(event = {}) {
  if (!event.timestamp) return null;
  return [
    event.task_id || '',
    event.type || '',
    event.phase || '',
    event.agent || '',
    event.timestamp,
  ].join('::');
}

export function appendUniqueEvent(events = [], incoming) {
  if (!incoming) return events;
  const incomingIdentity = getEventIdentity(incoming);
  if (!incomingIdentity) return [...events, incoming];

  const isReplay = events.some(event => getEventIdentity(event) === incomingIdentity);
  return isReplay ? events : [...events, incoming];
}
const QA_PHASE_TO_NODE = {
  collection: 'collection',
  product: 'product_analysis',
  pricing: 'pricing_analysis',
  market: 'market_analysis',
  strategy: 'strategy',
};

export function buildQaSummaries(results = []) {
  const summaries = {};

  results.forEach((result) => {
    const nodeKey = QA_PHASE_TO_NODE[result?.phase];
    if (!nodeKey) return;

    const current = summaries[nodeKey] || { retryCount: 0, checks: [] };
    const checks = [...current.checks, result];
    if (result.running) {
      summaries[nodeKey] = {
        phase: result.phase,
        label: '质检中',
        status: 'running',
        score: result.score,
        attempt: result.attempt,
        retryCount: current.retryCount,
        checks,
      };
      return;
    }

    const retryCount = current.retryCount + (
      result.passed === false && !result.degraded ? 1 : 0
    );
    const status = result.degraded ? 'degraded' : result.passed ? 'passed' : 'failed';
    const label = result.degraded
      ? `降级通过 · 打回 ${retryCount} 次`
      : result.passed
        ? `通过${result.score != null ? ` · ${Math.round(result.score)} 分` : ''}`
        : `未通过 · 打回 ${retryCount} 次`;

    summaries[nodeKey] = {
      phase: result.phase,
      label,
      status,
      score: result.score,
      attempt: result.attempt,
      retryCount,
      checks,
    };
  });

  return summaries;
}
