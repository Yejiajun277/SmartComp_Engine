import test from 'node:test';
import assert from 'node:assert/strict';
import {
  deriveStageStatus,
  filterPresentationEvents,
  getQaPresentationMode,
  normalizeNodeStateForTask,
  selectTaskScopedArtifact,
  selectTaskScopedQaArtifact,
  shouldLoadQaArtifact,
} from '../src/utils/workflowPresentation.js';

test('a completed task cannot leave a stage visually running', () => {
  assert.equal(deriveStageStatus(['strategy'], { strategy: 'running' }, 'completed'), 'completed');
});

test('parallel stage status keeps failure and retry states visible', () => {
  assert.equal(deriveStageStatus(['product', 'pricing'], { product: 'completed', pricing: 'failed' }), 'failed');
  assert.equal(deriveStageStatus(['product', 'pricing'], { product: 'completed', pricing: 'retrying' }), 'retrying');
});

test('checkpoint risks take priority over retrying agents while agent failures remain highest', () => {
  assert.equal(deriveStageStatus(['product'], { product: 'retrying' }, undefined, 'failed'), 'failed');
  assert.equal(deriveStageStatus(['product'], { product: 'retrying' }, undefined, 'degraded'), 'degraded');
  assert.equal(deriveStageStatus(['product'], { product: 'retrying' }, undefined, 'running'), 'running');
  assert.equal(deriveStageStatus(['product'], { product: 'retrying' }, undefined, 'passed'), 'retrying');
  assert.equal(deriveStageStatus(['product'], { product: 'running' }, undefined, 'passed'), 'running');
  assert.equal(deriveStageStatus(['product'], { product: 'failed' }, undefined, 'running'), 'failed');
});

test('completed tasks normalize non-failed node states without hiding a real failure', () => {
  assert.equal(normalizeNodeStateForTask('waiting', 'completed'), 'completed');
  assert.equal(normalizeNodeStateForTask('running', 'completed'), 'completed');
  assert.equal(normalizeNodeStateForTask('retrying', 'completed'), 'completed');
  assert.equal(normalizeNodeStateForTask('failed', 'completed'), 'failed');
  assert.equal(normalizeNodeStateForTask('running', 'running'), 'running');
});

test('task-scoped artifact selectors reject data from a previous task or phase', () => {
  const artifact = { taskId: 'task-one', phase: 'strategy', data: { summary: 'old' } };
  const qaArtifact = { taskId: 'task-one', data: { checks: [] } };

  assert.deepEqual(selectTaskScopedArtifact(artifact, 'task-one', 'strategy'), { summary: 'old' });
  assert.equal(selectTaskScopedArtifact(artifact, 'task-two', 'strategy'), null);
  assert.equal(selectTaskScopedArtifact(artifact, 'task-one', 'collection'), null);
  assert.deepEqual(selectTaskScopedQaArtifact(qaArtifact, 'task-one'), { checks: [] });
  assert.equal(selectTaskScopedQaArtifact(qaArtifact, 'task-two'), null);
});

test('QA checkpoint state becomes the visible state of a completed business stage', () => {
  const completedAgent = { collection: 'completed' };

  assert.equal(deriveStageStatus(['collection'], completedAgent, undefined, 'running'), 'running');
  assert.equal(deriveStageStatus(['collection'], completedAgent, undefined, 'failed'), 'failed');
  assert.equal(deriveStageStatus(['collection'], completedAgent, undefined, 'degraded'), 'degraded');
  assert.equal(deriveStageStatus(['collection'], completedAgent, undefined, 'passed'), 'completed');
  assert.equal(deriveStageStatus(['collection'], completedAgent, undefined, 'disabled'), 'completed');
});

test('completed tasks still surface a checkpoint risk while safe checkpoints stay completed', () => {
  const completedAgent = { strategy: 'completed' };

  assert.equal(deriveStageStatus(['strategy'], completedAgent, 'completed', 'running'), 'running');
  assert.equal(deriveStageStatus(['strategy'], completedAgent, 'completed', 'failed'), 'failed');
  assert.equal(deriveStageStatus(['strategy'], completedAgent, 'completed', 'degraded'), 'degraded');
  assert.equal(deriveStageStatus(['strategy'], completedAgent, 'completed', 'passed'), 'completed');
  assert.equal(deriveStageStatus(['strategy'], completedAgent, 'completed', 'disabled'), 'completed');
  assert.equal(deriveStageStatus(['strategy'], completedAgent, 'completed', 'waiting'), 'completed');
  assert.equal(deriveStageStatus(['strategy'], completedAgent, 'completed'), 'completed');
});

test('only current task metadata explicitly enabling QA permits an artifact load', () => {
  const currentEnabled = { id: 'task-current', skip_qa: false };
  const currentDisabled = { id: 'task-current', skip_qa: true };
  const previousTask = { id: 'task-previous', skip_qa: false };

  assert.equal(getQaPresentationMode('task-current', previousTask), 'pending');
  assert.equal(shouldLoadQaArtifact('task-current', previousTask, null), false);
  assert.equal(shouldLoadQaArtifact('task-current', currentDisabled, null), false);
  assert.equal(shouldLoadQaArtifact('task-current', currentEnabled, null), true);
  assert.equal(shouldLoadQaArtifact('task-current', currentEnabled, 'task-current'), false);
});

test('QA events are omitted from presentation only when QA is disabled', () => {
  const events = [{ type: 'agent_started' }, { type: 'qa_check_started' }];
  assert.deepEqual(filterPresentationEvents(events, true), [{ type: 'agent_started' }]);
  assert.deepEqual(filterPresentationEvents(events, false), events);
});
