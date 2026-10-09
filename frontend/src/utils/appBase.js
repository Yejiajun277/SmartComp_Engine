const configuredBaseUrl = import.meta.env?.BASE_URL || '/';

export function normalizeAppBasePath(baseUrl = '/') {
  const value = String(baseUrl || '/').trim();
  if (!value || value === '/') return '';
  return `/${value.replace(/^\/+|\/+$/g, '')}`;
}

export function buildAppPath(path, baseUrl = configuredBaseUrl) {
  const basePath = normalizeAppBasePath(baseUrl);
  const suffix = String(path || '').replace(/^\/+/, '');
  return suffix ? `${basePath}/${suffix}` : `${basePath}/`;
}

export function buildWebSocketUrl(location, path, baseUrl = configuredBaseUrl) {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${location.host}${buildAppPath(path, baseUrl)}`;
}

export function buildTaskReportPath(taskId, baseUrl = configuredBaseUrl) {
  return buildAppPath(`/api/tasks/${encodeURIComponent(taskId)}/report.html`, baseUrl);
}

export const APP_BASE_PATH = normalizeAppBasePath(configuredBaseUrl);
