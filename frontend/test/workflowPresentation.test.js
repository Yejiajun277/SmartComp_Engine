import test from 'node:test';
import assert from 'node:assert/strict';
import * as workflowPresentation from '../src/utils/workflowPresentation.js';
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

test('a completed resolved task ignores a stale current-agent override', () => {
  assert.equal(typeof workflowPresentation.buildPresentationNodeStates, 'function');

  assert.deepEqual(
    workflowPresentation.buildPresentationNodeStates(
      { strategy: 'completed' },
      'completed',
      'strategy',
    ),
    { strategy: 'completed' },
  );
});

test('a running resolved task marks its current agent as running without hiding a retry', () => {
  assert.equal(typeof workflowPresentation.buildPresentationNodeStates, 'function');

  assert.deepEqual(
    workflowPresentation.buildPresentationNodeStates(
      { strategy: 'waiting', collection: 'retrying' },
      'running',
      'strategy',
    ),
    { strategy: 'running', collection: 'retrying' },
  );
});

test('a task-scoped cache is empty for a different route and rejects stale writes', () => {
  assert.equal(typeof workflowPresentation.createTaskArtifactCache, 'function');
  assert.equal(typeof workflowPresentation.selectTaskArtifactCache, 'function');
  assert.equal(typeof workflowPresentation.updateTaskArtifactCache, 'function');

  const taskOneCache = workflowPresentation.updateTaskArtifactCache(
    workflowPresentation.createTaskArtifactCache('task-one'),
    'task-one',
    'strategy',
    { summary: 'old' },
  );
  const taskTwoCache = workflowPresentation.createTaskArtifactCache('task-two');
  const taskTwoWithArtifact = workflowPresentation.updateTaskArtifactCache(
    taskTwoCache,
    'task-two',
    'strategy',
    { summary: 'new' },
  );
  const afterStaleWrite = workflowPresentation.updateTaskArtifactCache(
    taskTwoWithArtifact,
    'task-one',
    'collection',
    { summary: 'stale' },
  );

  assert.deepEqual(workflowPresentation.selectTaskArtifactCache(taskOneCache, 'task-two'), {});
  assert.deepEqual(workflowPresentation.selectTaskArtifactCache(taskTwoWithArtifact, 'task-two'), {
    strategy: { summary: 'new' },
  });
  assert.equal(afterStaleWrite, taskTwoWithArtifact);
});

test('a task-scoped persisted QA presentation is empty for a new route and rejects stale writes', () => {
  assert.equal(typeof workflowPresentation.createTaskQaPresentationState, 'function');
  assert.equal(typeof workflowPresentation.selectTaskQaPresentationState, 'function');
  assert.equal(typeof workflowPresentation.updateTaskQaPresentationState, 'function');

  const taskOneState = workflowPresentation.updateTaskQaPresentationState(
    workflowPresentation.createTaskQaPresentationState('task-one'),
    'task-one',
    {
      results: [{ phase: 'strategy', passed: true }],
      summaries: { strategy: { status: 'passed' } },
    },
  );
  const taskTwoState = workflowPresentation.createTaskQaPresentationState('task-two');
  const afterStaleWrite = workflowPresentation.updateTaskQaPresentationState(
    taskTwoState,
    'task-one',
    {
      results: [{ phase: 'collection', passed: false }],
      summaries: { collection: { status: 'failed' } },
    },
  );

  assert.deepEqual(
    workflowPresentation.selectTaskQaPresentationState(taskOneState, 'task-two'),
    { results: [], summaries: {} },
  );
  assert.equal(afterStaleWrite, taskTwoState);
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
  assert.equal(shouldLoadQaArtifact('task-current', currentEnabled, 'task-current', true), true);
});

test('QA events are omitted from presentation only when QA is disabled', () => {
  const events = [{ type: 'agent_started' }, { type: 'qa_check_started' }];
  assert.deepEqual(filterPresentationEvents(events, true), [{ type: 'agent_started' }]);
  assert.deepEqual(filterPresentationEvents(events, false), events);
});
