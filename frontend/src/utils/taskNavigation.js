export function getTaskLoadFailureAction(error) {
  return error?.response?.status === 404 ? 'redirect_home' : 'retry';
}

export function createTaskLoadScope(taskId) {
  let active = true;
  return {
    taskId,
    cancel() {
      active = false;
    },
    isActive() {
      return active;
    },
  };
}
