import test from 'node:test';
import assert from 'node:assert/strict';
import {
  appendUniqueEvent,
  buildQaSummaries,
  mergeQaSummaries,
  upsertQaResult,
} from '../src/utils/taskEvents.js';

test('replaces a failed QA attempt with its degraded final state', () => {
  const failed = { phase: 'strategy', attempt: 3, passed: false, degraded: false };
  const degraded = { phase: 'strategy', attempt: 3, passed: false, degraded: true };

  const finalResults = upsertQaResult(upsertQaResult([], failed), degraded);

  assert.equal(finalResults.length, 1);
  assert.equal(finalResults[0].degraded, true);
});

test('does not regress a final QA attempt when websocket history replays', () => {
  const degraded = { phase: 'collection', attempt: 2, passed: false, degraded: true };
  const replayedStart = { phase: 'collection', attempt: 2, running: true };
  const replayedFailure = { phase: 'collection', attempt: 2, passed: false, degraded: false };

  const afterStart = upsertQaResult([degraded], replayedStart);
  const afterFailure = upsertQaResult(afterStart, replayedFailure);

  assert.deepEqual(afterFailure, [degraded]);
});

test('keeps separate QA attempts while replacing the running placeholder', () => {
  const running = { phase: 'product', attempt: 1, running: true };
  const failed = { phase: 'product', attempt: 1, passed: false };
  const passed = { phase: 'product', attempt: 2, passed: true };

  const results = [running, failed, passed].reduce(upsertQaResult, []);

  assert.equal(results.length, 2);
  assert.deepEqual(results.map(result => result.attempt), [1, 2]);
});

test('deduplicates replayed workflow history by stable event identity', () => {
  const event = {
    task_id: 'task-1',
    type: 'qa_check_failed',
    phase: 'pricing',
    agent: 'QualityAgent',
    timestamp: '2026-08-29T10:00:00',
  };

  assert.equal(appendUniqueEvent(appendUniqueEvent([], event), { ...event }).length, 1);
});

test('persisted terminal QA does not regress to a replayed start from the same attempt', () => {
  const result = mergeQaSummaries(
    { strategy: { status: 'passed', attempt: 1 } },
    { strategy: { status: 'running', attempt: 1 } },
  );

  assert.equal(result.strategy.status, 'passed');
});

test('a higher live QA attempt replaces a persisted terminal summary', () => {
  const persisted = buildQaSummaries([
    { phase: 'collection', attempt: 1, passed: true, score: 90 },
  ]);
  const live = buildQaSummaries([
    { phase: 'collection', attempt: 2, running: true },
  ]);

  const merged = mergeQaSummaries(persisted, live);

  assert.equal(merged.collection.status, 'running');
  assert.equal(merged.collection.attempt, 2);
});

test('same or unknown QA attempts cannot downgrade a persisted terminal summary', () => {
  const persisted = buildQaSummaries([
    { phase: 'strategy', attempt: 1, passed: true },
  ]);

  [1, undefined, null, ''].forEach((attempt) => {
    const live = buildQaSummaries([{ phase: 'strategy', attempt, running: true }]);
    const merged = mergeQaSummaries(persisted, live);
    assert.equal(merged.strategy.status, 'passed');
    assert.equal(merged.strategy.attempt, 1);
  });
});
