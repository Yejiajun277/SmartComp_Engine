import test from 'node:test';
import assert from 'node:assert/strict';
import {
  formatElapsed,
  getEventLabel,
  getTaskModeMeta,
  getTaskStatusMeta,
  mergeTasks,
  resolveTaskProgress,
  resolveTaskStatus,
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

test('keeps server task order and appends unmatched local tasks', () => {
  const result = mergeTasks(
    [{ id: 'new', status: 'running' }, { id: 'old', status: 'completed' }],
    [{ id: 'local', status: 'pending' }, { id: 'old', status: 'pending' }],
  );

  assert.deepEqual(result.map(item => item.id), ['new', 'old', 'local']);
});

test('does not claim execution or QA modes when the task API omits them', () => {
  const unknownMeta = {
    executionLabel: '执行模式待同步',
    qaLabel: 'QA 状态待同步',
    qaTone: 'neutral',
  };
  assert.deepEqual(getTaskModeMeta({}), unknownMeta);
  assert.deepEqual(getTaskModeMeta(null), unknownMeta);
  assert.deepEqual(getTaskModeMeta({ use_rule_engine: true, skip_qa: true }), {
    executionLabel: '规则引擎分析',
    qaLabel: '质量检查已关闭',
    qaTone: 'risk',
  });
});

test('uses persisted task progress until a newer live update arrives', () => {
  assert.equal(resolveTaskProgress('running', 0, 0.42), 42);
  assert.equal(resolveTaskProgress('running', 0.58, 0.42), 58);
  assert.equal(resolveTaskProgress('completed', 0, 0.42), 100);
});

test('lets persisted terminal state recover a missed websocket terminal event', () => {
  assert.equal(resolveTaskStatus('running', 'completed'), 'completed');
  assert.equal(resolveTaskStatus('running', 'failed'), 'failed');
  assert.equal(resolveTaskStatus('completed', 'running'), 'completed');
  assert.equal(resolveTaskStatus('pending', 'running'), 'running');
});
