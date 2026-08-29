import test from 'node:test';
import assert from 'node:assert/strict';
import {
  formatElapsed,
  getEventLabel,
  getTaskStatusMeta,
  mergeTasks,
} from '../src/utils/presentation.js';

test('maps task states to user-facing labels and tones', () => {
  assert.deepEqual(getTaskStatusMeta('running'), { label: '分析中', tone: 'running' });
  assert.deepEqual(getTaskStatusMeta('completed'), { label: '已交付', tone: 'success' });
  assert.deepEqual(getTaskStatusMeta('unknown'), { label: '等待中', tone: 'neutral' });
});

test('merges recent tasks with authoritative server fields', () => {
  const result = mergeTasks(
    [{ id: 'a', status: 'completed', product_description: '飞书' }],
    [{ id: 'a', status: 'pending' }, { id: 'b', status: 'pending' }],
  );

  assert.equal(result.length, 2);
  assert.equal(result.find(item => item.id === 'a').status, 'completed');
});

test('formats elapsed seconds and event labels', () => {
  assert.equal(formatElapsed('2026-08-29T10:00:00Z', '2026-08-29T10:01:05Z'), '1分5秒');
  assert.match(
    getEventLabel({ type: 'qa_check_failed', data: { target_agent: 'MarketAgent' } }),
    /MarketAgent/,
  );
});
