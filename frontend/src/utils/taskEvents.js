function getQaAttemptKey(result = {}) {
  if (!result.phase) return null;
  return [
    result.phase,
    result.target_agent || '',
    result.attempt ?? 'unknown',
  ].join('::');
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
  const liveAttempt = Number(live.attempt);
  const persistedAttempt = Number(persisted.attempt);

  return Number.isFinite(liveAttempt)
    && Number.isFinite(persistedAttempt)
    && liveAttempt > persistedAttempt;
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
