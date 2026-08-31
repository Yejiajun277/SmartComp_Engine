function getQaAttemptKey(result = {}) {
  if (!result.phase) return null;
  const attempt = getKnownAttempt(result.attempt);
  return [
    result.phase,
    result.target_agent || '',
    attempt ?? 'unknown',
  ].join('::');
}

export function shouldAcceptTaskEvent(event, taskId, connectionClosed = false) {
  if (connectionClosed || !taskId || !event || event.type === 'ping') return false;
  return event.task_id === taskId;
}

export function getQaResultState(result = {}) {
  if (result.degraded === true) return 'degraded';
  if (result.passed === true) return 'passed';
  if (result.passed === false) return 'failed';
  if (result.running === true) return 'running';
  return 'unknown';
}

function normalizeQaResultState(result = {}) {
  const state = getQaResultState(result);
  if (['failed', 'degraded', 'passed'].includes(state) && result.running === true) {
    return { ...result, running: false };
  }
  return result;
}

function getQaResultRank(result = {}) {
  const state = getQaResultState(result);
  if (state === 'passed' || state === 'degraded') return 2;
  if (state === 'failed') return 1;
  return 0;
}

const QA_SUMMARY_RANKS = {
  waiting: 0,
  running: 1,
  failed: 2,
  degraded: 3,
  passed: 3,
};

function getQaSummaryRank(summary = {}) {
  return QA_SUMMARY_RANKS[summary.status] ?? 0;
}

function getKnownAttempt(value) {
  if (value === null || value === undefined || value === '') return null;
  const attempt = Number(value);
  return Number.isFinite(attempt) ? attempt : null;
}

function compareQaSummaryAttempts(live = {}, persisted = {}) {
  const liveAttempt = getKnownAttempt(live.attempt);
  const persistedAttempt = getKnownAttempt(persisted.attempt);
  if (liveAttempt === null || persistedAttempt === null) return null;
  return Math.sign(liveAttempt - persistedAttempt);
}

function shouldReplaceQaSummary(existing, incoming) {
  if (!existing?.status) return true;
  const attemptOrder = compareQaSummaryAttempts(incoming, existing);
  if (attemptOrder !== null && attemptOrder !== 0) return attemptOrder > 0;
  return getQaSummaryRank(incoming) >= getQaSummaryRank(existing);
}

function getQaSummaryLabel(status, score, retryCount) {
  if (status === 'running') return '质检中';
  if (status === 'degraded') return `降级通过 · 打回 ${retryCount} 次`;
  if (status === 'passed') {
    return `通过${score != null ? ` · ${Math.round(score)} 分` : ''}`;
  }
  return `未通过 · 打回 ${retryCount} 次`;
}

export function mergeQaSummaries(persisted = {}, live = {}) {
  const merged = { ...persisted };

  Object.entries(live || {}).forEach(([target, liveSummary]) => {
    const persistedSummary = persisted?.[target];
    if (!shouldReplaceQaSummary(persistedSummary, liveSummary)) return;

    merged[target] = liveSummary;
  });

  return merged;
}

export function upsertQaResult(results = [], incoming) {
  if (!incoming) return results;
  const normalizedIncoming = normalizeQaResultState(incoming);
  const incomingKey = getQaAttemptKey(normalizedIncoming);
  if (!incomingKey) return [...results, normalizedIncoming];

  const existingIndex = results.findIndex(result => getQaAttemptKey(result) === incomingKey);
  if (existingIndex < 0) return [...results, normalizedIncoming];

  const existing = normalizeQaResultState(results[existingIndex]);
  if (getQaResultRank(normalizedIncoming) < getQaResultRank(existing)) {
    if (existing === results[existingIndex]) return results;
    const normalizedResults = [...results];
    normalizedResults[existingIndex] = existing;
    return normalizedResults;
  }

  const nextResults = [...results];
  nextResults[existingIndex] = normalizeQaResultState({ ...existing, ...normalizedIncoming });
  return nextResults;
}

export function mergeQaResults(persisted = [], live = []) {
  const persistedResults = Array.isArray(persisted) ? persisted : [];
  const liveResults = Array.isArray(live) ? live : [];
  return [...persistedResults, ...liveResults].reduce(upsertQaResult, []);
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

    const normalizedResult = normalizeQaResultState(result);
    const resultState = getQaResultState(normalizedResult);
    const current = summaries[nodeKey] || { retryCount: 0, checks: [] };
    const checks = [...current.checks, normalizedResult];
    let candidate;
    let retryCount = current.retryCount;
    if (resultState === 'running') {
      candidate = {
        phase: normalizedResult.phase,
        status: 'running',
        score: normalizedResult.score,
        attempt: normalizedResult.attempt,
      };
    } else {
      retryCount += resultState === 'failed' ? 1 : 0;
      candidate = {
        phase: normalizedResult.phase,
        status: resultState === 'degraded'
          ? 'degraded'
          : resultState === 'passed'
            ? 'passed'
            : 'failed',
        score: normalizedResult.score,
        attempt: normalizedResult.attempt,
      };
    }

    const selected = shouldReplaceQaSummary(current, candidate) ? candidate : current;
    summaries[nodeKey] = {
      ...selected,
      label: getQaSummaryLabel(selected.status, selected.score, retryCount),
      retryCount,
      checks,
    };
  });

  return summaries;
}
