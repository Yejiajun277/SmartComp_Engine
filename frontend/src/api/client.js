import axios from 'axios';

const api = axios.create({ baseURL: '/api' });

export async function submitTask(productDescription, maxCompetitors = 5, skipQa = false, useRuleEngine = false, enableHumanReview = false) {
  const { data } = await api.post('/tasks', {
    product_description: productDescription,
    max_competitors: maxCompetitors,
    skip_qa: skipQa,
    use_rule_engine: useRuleEngine,
    enable_human_review: enableHumanReview,
  });
  return data;
}

export async function evaluateDescription(productDescription) {
  const { data } = await api.post('/tasks/evaluate-description', {
    product_description: productDescription,
  });
  return data;
}

export async function getLlmLogs(taskId) {
  const { data } = await api.get(`/tasks/${taskId}/llm-logs`);
  return data;
}

export async function getTasks() {
  const { data } = await api.get('/tasks');
  return data;
}

export async function getTask(taskId) {
  const { data } = await api.get(`/tasks/${taskId}`);
  return data;
}

export async function deleteTask(taskId) {
  const { data } = await api.delete(`/tasks/${taskId}`);
  return data;
}

export async function getReport(taskId) {
  const { data } = await api.get(`/tasks/${taskId}/report`);
  return data;
}

export async function getArtifact(taskId, phase) {
  const { data } = await api.get(`/tasks/${taskId}/artifacts/${phase}`);
  return data;
}

// ── 人工介入 API ──

export async function getIntervention(taskId) {
  const { data } = await api.get(`/tasks/${taskId}/intervention`);
  return data;
}

export async function submitIntervention(taskId, response) {
  const { data } = await api.post(`/tasks/${taskId}/intervention`, response);
  return data;
}
