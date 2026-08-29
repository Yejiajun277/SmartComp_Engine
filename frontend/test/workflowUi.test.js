import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const sourceRoot = new URL('../src/', import.meta.url);

async function readSource(relativePath) {
  return readFile(new URL(relativePath, sourceRoot), 'utf8');
}

test('workflow workbench keeps QA disabled state on every presentation surface', async () => {
  const [taskDetail, pipelineGraph, agentDetail, activityRail] = await Promise.all([
    readSource('pages/TaskDetail.jsx'),
    readSource('components/PipelineGraph.jsx'),
    readSource('components/AgentDetail.jsx'),
    readSource('components/workbench/LiveActivityRail.jsx'),
  ]);

  assert.match(taskDetail, /const qaDisabled = taskInfo\?\.skip_qa === true/);
  assert.match(taskDetail, /<PipelineGraph[\s\S]*qaDisabled=\{qaDisabled\}/);
  assert.match(taskDetail, /<LiveActivityRail[\s\S]*qaDisabled=\{qaDisabled\}/);
  assert.match(taskDetail, /<AgentDetail[\s\S]*qaDisabled=\{qaDisabled\}/);
  assert.match(pipelineGraph, /taskStatus,\s*qaDisabled/);
  assert.match(agentDetail, /qaDisabled/);
  assert.match(activityRail, /filterPresentationEvents\(events, qaDisabled\)/);
});

test('pipeline is organized around four numbered business stages with checkpoint QA', async () => {
  const pipelineGraph = await readSource('components/PipelineGraph.jsx');

  assert.match(pipelineGraph, /const STAGES = \[/);
  assert.match(pipelineGraph, /number: 1/);
  assert.match(pipelineGraph, /number: 4/);
  assert.match(pipelineGraph, /checkpoint:/);
  assert.match(pipelineGraph, /deriveStageStatus/);
});
