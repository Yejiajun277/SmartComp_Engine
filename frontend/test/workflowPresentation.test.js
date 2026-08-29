import test from 'node:test';
import assert from 'node:assert/strict';
import {
  deriveStageStatus,
  filterPresentationEvents,
} from '../src/utils/workflowPresentation.js';

test('a completed task cannot leave a stage visually running', () => {
  assert.equal(deriveStageStatus(['strategy'], { strategy: 'running' }, 'completed'), 'completed');
});

test('parallel stage status keeps failure and retry states visible', () => {
  assert.equal(deriveStageStatus(['product', 'pricing'], { product: 'completed', pricing: 'failed' }), 'failed');
  assert.equal(deriveStageStatus(['product', 'pricing'], { product: 'completed', pricing: 'retrying' }), 'retrying');
});

test('QA events are omitted from presentation only when QA is disabled', () => {
  const events = [{ type: 'agent_started' }, { type: 'qa_check_started' }];
  assert.deepEqual(filterPresentationEvents(events, true), [{ type: 'agent_started' }]);
  assert.deepEqual(filterPresentationEvents(events, false), events);
});
