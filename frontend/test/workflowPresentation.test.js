import test from 'node:test';
import assert from 'node:assert/strict';
import {
  deriveStageStatus,
  filterPresentationEvents,
  getQaPresentationMode,
  shouldLoadQaArtifact,
} from '../src/utils/workflowPresentation.js';

test('a completed task cannot leave a stage visually running', () => {
  assert.equal(deriveStageStatus(['strategy'], { strategy: 'running' }, 'completed'), 'completed');
});

test('parallel stage status keeps failure and retry states visible', () => {
  assert.equal(deriveStageStatus(['product', 'pricing'], { product: 'completed', pricing: 'failed' }), 'failed');
  assert.equal(deriveStageStatus(['product', 'pricing'], { product: 'completed', pricing: 'retrying' }), 'retrying');
});

test('QA checkpoint state becomes the visible state of a completed business stage', () => {
  const completedAgent = { collection: 'completed' };

  assert.equal(deriveStageStatus(['collection'], completedAgent, undefined, 'running'), 'running');
  assert.equal(deriveStageStatus(['collection'], completedAgent, undefined, 'failed'), 'failed');
  assert.equal(deriveStageStatus(['collection'], completedAgent, undefined, 'degraded'), 'degraded');
  assert.equal(deriveStageStatus(['collection'], completedAgent, undefined, 'passed'), 'completed');
  assert.equal(deriveStageStatus(['collection'], completedAgent, undefined, 'disabled'), 'completed');
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
