export function deriveStageStatus(
  agentKeys = [],
  nodeStates = {},
  taskStatus,
  checkpointStatus = 'waiting',
) {
  const checkpointHasRisk = ['running', 'failed', 'degraded'].includes(checkpointStatus);
  if (taskStatus === 'completed' && !checkpointHasRisk) return 'completed';
  const states = agentKeys.map(key => nodeStates[key] || 'waiting');
  if (states.includes('failed')) return 'failed';
  if (checkpointStatus === 'failed') return 'failed';
  if (checkpointStatus === 'degraded') return 'degraded';
  if (checkpointStatus === 'running') return 'running';
  if (states.includes('retrying')) return 'retrying';
  if (states.includes('running')) return 'running';
  const agentStatus = states.length > 0 && states.every(state => state === 'completed')
    ? 'completed'
    : 'waiting';
  return agentStatus;
}

export function normalizeNodeStateForTask(nodeState = 'waiting', taskStatus) {
  if (taskStatus !== 'completed') return nodeState;
  return nodeState === 'failed' ? 'failed' : 'completed';
}

export function buildPresentationNodeStates(nodeStates = {}, taskStatus, currentPhase) {
  const displayNodeStates = Object.fromEntries(
    Object.entries(nodeStates).map(([phase, state]) => [
      phase,
      normalizeNodeStateForTask(state, taskStatus),
    ]),
  );

  if (
    taskStatus === 'running'
    && currentPhase
    && displayNodeStates[currentPhase] !== 'failed'
    && displayNodeStates[currentPhase] !== 'retrying'
  ) {
    displayNodeStates[currentPhase] = 'running';
  }

  return displayNodeStates;
}

export function createTaskArtifactCache(taskId) {
  return { taskId, artifacts: {} };
}

export function selectTaskArtifactCache(cache, taskId) {
  if (!cache || cache.taskId !== taskId) return {};
  return cache.artifacts || {};
}

export function updateTaskArtifactCache(cache, taskId, phase, data) {
  if (!cache || cache.taskId !== taskId) return cache;
  return {
    ...cache,
    artifacts: {
      ...cache.artifacts,
      [phase]: data,
    },
  };
}

export function selectTaskScopedArtifact(artifact, taskId, phase) {
  if (!artifact || artifact.taskId !== taskId || artifact.phase !== phase) return null;
  return artifact.data;
}

export function selectTaskScopedQaArtifact(artifact, taskId) {
  if (!artifact || artifact.taskId !== taskId) return null;
  return artifact.data;
}

export function getQaPresentationMode(taskId, taskInfo) {
  if (!taskId || !taskInfo || taskInfo.id !== taskId) return 'pending';
  return taskInfo.skip_qa === true ? 'disabled' : 'enabled';
}

export function shouldLoadQaArtifact(taskId, taskInfo, attemptedTaskId) {
  return getQaPresentationMode(taskId, taskInfo) === 'enabled'
    && attemptedTaskId !== taskId;
}

export function filterPresentationEvents(events = [], qaDisabled = false) {
  return qaDisabled ? events.filter(event => !event?.type?.startsWith('qa_')) : events;
}
