import axios from 'axios';
import { DEFAULT_MAX_COMPETITORS } from '../utils/taskCreation.js';

const api = axios.create({ baseURL: '/api' });

export async function getRuntimeConfig() {
  const { data } = await api.get('/runtime');
  return data;
}

export async function submitTask(
  productDescription,
  maxCompetitors = DEFAULT_MAX_COMPETITORS,
  skipQa = false,
  useRuleEngine = false,
) {
  const { data } = await api.post('/tasks', {
    product_description: productDescription,
    max_competitors: maxCompetitors,
    skip_qa: skipQa,
    use_rule_engine: useRuleEngine,
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
