import test from 'node:test';
import assert from 'node:assert/strict';
import { aggregateQuality, getGateState } from '../src/utils/quality.js';
import * as quality from '../src/utils/quality.js';
import { buildQaSummaries } from '../src/utils/taskEvents.js';

test('uses the latest completed check per phase for weighted metrics', () => {
  const summary = aggregateQuality([
    {
      phase: 'product',
      passed: false,
      total_fields: 5,
      accuracy_rate: 40,
      coverage_rate: 60,
      correction_count: 2,
      issues: [{}],
    },
    {
      phase: 'product',
      passed: true,
      total_fields: 5,
      accuracy_rate: 90,
      coverage_rate: 80,
      correction_count: 1,
      issues: [],
    },
    {
      phase: 'market',
      passed: true,
      total_fields: 10,
      accuracy_rate: 80,
      coverage_rate: 70,
      correction_count: 1,
      issues: [],
    },
  ]);

  assert.equal(summary.totalChecks, 3);
  assert.equal(summary.retryCount, 1);
  assert.equal(summary.accuracyRate, 83.3);
  assert.equal(summary.coverageRate, 73.3);
  assert.equal(summary.correctionRate, 13.3);
});

test('prioritizes running, failed, degraded, then passed gate states', () => {
  assert.equal(
    getGateState(['product_analysis'], { product_analysis: { status: 'running' } }).status,
    'running',
  );
  assert.equal(
    getGateState(['product_analysis'], { product_analysis: { status: 'failed' } }).status,
    'failed',
  );
  assert.equal(
    getGateState(['product_analysis'], { product_analysis: { status: 'degraded' } }).status,
    'degraded',
  );
  assert.equal(
    getGateState(['product_analysis'], { product_analysis: { status: 'passed' } }).status,
    'passed',
  );
});

test('disabled QA overrides stale running summaries', () => {
  const result = getGateState(
    ['strategy'],
    { strategy: { status: 'running', attempt: 1 } },
    { disabled: true },
  );

  assert.equal(result.status, 'disabled');
});

test('completed quality metrics include terminal outcomes with a stale running marker', () => {
  const result = aggregateQuality([{
    phase: 'collection',
    running: true,
    passed: false,
    total_fields: 4,
    correction_count: 1,
    issues: [{}],
  }]);

  assert.equal(result.totalChecks, 1);
  assert.equal(result.retryCount, 1);
});

test('reloaded QA applies only a matching terminal disposition to a copied latest attempt', () => {
  const checks = [
    { phase: 'product', attempt: 2, passed: false, degraded: false, issues: [{ severity: 'critical' }] },
    { phase: 'product', attempt: 3, passed: false, degraded: false, issues: [{ severity: 'critical' }] },
  ];
  assert.equal(typeof quality.getTimelineQaResults, 'function');
  const results = quality.getTimelineQaResults({
    checks,
    terminal_dispositions: { product: { status: 'degraded', attempt: 3, reason: 'retry_exhausted' } },
  });
  const summary = buildQaSummaries(results).product_analysis;

  assert.equal(results.length, 2);
  assert.equal(results[0].degraded, false);
  assert.equal(results[1].passed, false);
  assert.equal(results[1].degraded, true);
  assert.equal(results[1].issues[0].severity, 'critical');
  assert.equal(summary.status, 'degraded');
  assert.equal(aggregateQuality(results).degradedCount, 1);
  assert.equal(checks[1].degraded, false);
});

test('old timelines and newer failures retain their recorded QA semantics', () => {
  const checks = [{ phase: 'product', attempt: 4, passed: false, degraded: false }];
  assert.equal(typeof quality.getTimelineQaResults, 'function');
  assert.deepEqual(quality.getTimelineQaResults({ checks }), checks);
  assert.deepEqual(quality.getTimelineQaResults({
    checks,
    terminal_dispositions: { product: { status: 'degraded', attempt: 3, reason: 'retry_exhausted' } },
  }), checks);
});
