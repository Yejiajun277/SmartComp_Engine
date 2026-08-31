import test from 'node:test';
import assert from 'node:assert/strict';
import * as taskEvents from '../src/utils/taskEvents.js';

const {
  appendUniqueEvent,
  buildQaSummaries,
  mergeQaResults,
  mergeQaSummaries,
  reduceWorkflowNodeStates,
  shouldAcceptTaskEvent,
  terminalizeQaResultsForTaskFailure,
  upsertQaResult,
} = taskEvents;

test('accepts websocket events only for the active task and an open connection', () => {
  const currentEvent = { task_id: 'task-current', type: 'qa_check_passed' };

  assert.equal(shouldAcceptTaskEvent(currentEvent, 'task-current', false), true);
  assert.equal(shouldAcceptTaskEvent(currentEvent, 'task-previous', false), false);
  assert.equal(shouldAcceptTaskEvent(currentEvent, 'task-current', true), false);
  assert.equal(shouldAcceptTaskEvent({ type: 'qa_check_passed' }, 'task-current', false), false);
  assert.equal(shouldAcceptTaskEvent({ type: 'ping' }, 'task-current', false), false);
});

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
  assert.equal(results[0].passed, false);
  assert.equal(results[0].running, false);
});

test('terminal QA outcomes outrank a contradictory running marker', () => {
  const cases = [
    [{ phase: 'collection', attempt: 1, running: true, passed: false }, 'failed'],
    [{ phase: 'product', attempt: 1, running: true, passed: true }, 'passed'],
    [{ phase: 'strategy', attempt: 1, running: true, passed: false, degraded: true }, 'degraded'],
  ];

  cases.forEach(([result, expectedStatus]) => {
    const summary = buildQaSummaries([result]);
    const nodeKey = result.phase === 'product' ? 'product_analysis' : result.phase;
    assert.equal(summary[nodeKey].status, expectedStatus);
  });
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

test('timeline merge preserves persisted terminal attempts over replayed starts', () => {
  const merged = mergeQaResults(
    [{ phase: 'collection', target_agent: 'CollectionAgent', attempt: 1, passed: false, score: 53 }],
    [{ phase: 'collection', target_agent: 'CollectionAgent', attempt: 1, running: true }],
  );

  assert.equal(merged.length, 1);
  assert.equal(merged[0].passed, false);
  assert.notEqual(merged[0].running, true);
  assert.equal(merged[0].score, 53);
});

test('an older replayed terminal summary cannot replace a newer persisted attempt', () => {
  const persisted = buildQaSummaries([
    { phase: 'collection', attempt: 2, passed: true, score: 91 },
  ]);
  const replayed = buildQaSummaries([
    { phase: 'collection', attempt: 1, passed: false, score: 53 },
  ]);

  const merged = mergeQaSummaries(persisted, replayed);

  assert.equal(merged.collection.status, 'passed');
  assert.equal(merged.collection.attempt, 2);
  assert.equal(merged.collection.score, 91);
});

test('numeric and string attempt values identify the same QA round', () => {
  const merged = mergeQaResults(
    [{ phase: 'collection', target_agent: 'CollectionAgent', attempt: 1, passed: false }],
    [{ phase: 'collection', target_agent: 'CollectionAgent', attempt: '1', running: true }],
  );

  assert.equal(merged.length, 1);
  assert.equal(merged[0].passed, false);
  assert.notEqual(merged[0].running, true);
});

test('summary selection uses the newest QA attempt regardless of replay order', () => {
  const results = mergeQaResults(
    [{ phase: 'collection', attempt: 2, passed: true, score: 91 }],
    [{ phase: 'collection', attempt: 1, passed: false, score: 53 }],
  );

  const summary = buildQaSummaries(results).collection;

  assert.equal(summary.status, 'passed');
  assert.equal(summary.attempt, 2);
  assert.equal(summary.score, 91);
  assert.equal(summary.retryCount, 1);
});

test('a structured task failure stops spinners and marks only the real workflow node failed', () => {
  assert.equal(typeof reduceWorkflowNodeStates, 'function');
  const result = reduceWorkflowNodeStates(
    {
      discovery: 'completed',
      collection: 'completed',
      qa_collection: 'running',
      dimension: 'waiting',
      product_analysis: 'running',
    },
    {
      type: 'task_failed',
      phase: 'qa_collection',
      data: { failed_node: 'qa_collection' },
    },
  );

  assert.deepEqual(result, {
    discovery: 'completed',
    collection: 'completed',
    qa_collection: 'failed',
    dimension: 'waiting',
    product_analysis: 'blocked',
  });
});

test('an agent failure event uses failed_node instead of leaving the business stage running', () => {
  assert.equal(typeof reduceWorkflowNodeStates, 'function');
  const result = reduceWorkflowNodeStates(
    { collection: 'completed', qa_collection: 'running' },
    {
      type: 'agent_failed',
      phase: 'collection',
      data: { failed_node: 'qa_collection' },
    },
  );

  assert.equal(result.collection, 'completed');
  assert.equal(result.qa_collection, 'failed');
});

test('a technical QA failure replaces its spinner with a diagnostic terminal result', () => {
  assert.equal(typeof terminalizeQaResultsForTaskFailure, 'function');
  const results = terminalizeQaResultsForTaskFailure(
    [
      { phase: 'collection', target_agent: 'CollectionAgent', attempt: 3, running: true },
      { phase: 'product', target_agent: 'ProductAgent', attempt: 1, running: true },
    ],
    {
      type: 'task_failed',
      message: '证据质检执行失败',
      data: { failed_node: 'qa_collection' },
    },
  );

  assert.deepEqual(results, [{
    phase: 'collection',
    target_agent: 'CollectionAgent',
    attempt: 3,
    running: false,
    passed: false,
    technical_error: true,
    message: '证据质检执行失败',
  }]);
});
