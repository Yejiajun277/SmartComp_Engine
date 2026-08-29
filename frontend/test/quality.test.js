import test from 'node:test';
import assert from 'node:assert/strict';
import { aggregateQuality, getGateState } from '../src/utils/quality.js';

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
