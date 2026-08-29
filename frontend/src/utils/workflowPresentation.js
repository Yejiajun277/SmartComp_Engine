export function deriveStageStatus(agentKeys = [], nodeStates = {}, taskStatus) {
  if (taskStatus === 'completed') return 'completed';
  const states = agentKeys.map(key => nodeStates[key] || 'waiting');
  if (states.includes('failed')) return 'failed';
  if (states.includes('retrying')) return 'retrying';
  if (states.includes('running')) return 'running';
  return states.length > 0 && states.every(state => state === 'completed') ? 'completed' : 'waiting';
}

export function filterPresentationEvents(events = [], qaDisabled = false) {
  return qaDisabled ? events.filter(event => !event?.type?.startsWith('qa_')) : events;
}
