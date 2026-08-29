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
  if (states.includes('retrying')) return 'retrying';
  if (states.includes('running')) return 'running';
  const agentStatus = states.length > 0 && states.every(state => state === 'completed')
    ? 'completed'
    : 'waiting';

  if (checkpointStatus === 'disabled' || checkpointStatus === 'waiting' || checkpointStatus === 'passed') {
    return agentStatus;
  }
  if (checkpointStatus === 'failed') return 'failed';
  if (checkpointStatus === 'degraded') return 'degraded';
  if (checkpointStatus === 'running') return 'running';
  return agentStatus;
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
