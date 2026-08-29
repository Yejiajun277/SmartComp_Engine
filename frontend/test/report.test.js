import test from 'node:test';
import assert from 'node:assert/strict';
import { buildReportOverview } from '../src/utils/report.js';

test('derives prioritized actions and trust evidence from serialized report data', () => {
  const result = buildReportOverview({
    product_name: '飞书',
    competitor_count: 5,
    overall_positioning: '以协作深度建立差异化',
    action_plan: [
      { priority: 'P2', action: '长期生态建设' },
      { priority: 'P0', action: '强化核心协作能力' },
      { priority: 'P1', action: '优化团队定价' },
    ],
    citation_index: { citations: { c1: {}, c2: {} } },
    qa_timeline: { checks: [{ passed: true }, { passed: true, degraded: true }] },
  });

  assert.equal(result.productName, '飞书');
  assert.deepEqual(result.actions.map(item => item.priority), ['P0', 'P1', 'P2']);
  assert.equal(result.citationCount, 2);
  assert.equal(result.qaStatus, 'degraded');
});

test('uses honest unknown states for incomplete reports', () => {
  const result = buildReportOverview({ product_name: '未完成任务' });

  assert.equal(result.citationCount, 0);
  assert.equal(result.qaStatus, 'unknown');
  assert.deepEqual(result.actions, []);
});

test('uses the latest completed QA check per phase', () => {
  const result = buildReportOverview({
    qa_timeline: {
      checks: [
        { phase: 'strategy', passed: false },
        { phase: 'strategy', passed: true },
        { phase: 'market', running: true },
      ],
    },
  });

  assert.equal(result.qaCheckCount, 3);
  assert.equal(result.qaStatus, 'passed');
});
