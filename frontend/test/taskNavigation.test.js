import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';

const taskNavigation = await import('../src/utils/taskNavigation.js').catch(() => ({}));

async function loadDashboardModule(t) {
  const vite = await createServer({
    appType: 'custom',
    configFile: false,
    logLevel: 'silent',
    server: { middlewareMode: true },
  });
  t.after(() => vite.close());
  return vite.ssrLoadModule('/src/pages/Dashboard.jsx');
}

test('a missing task redirects home while transient request failures remain retryable', () => {
  assert.equal(typeof taskNavigation.getTaskLoadFailureAction, 'function');
  assert.equal(
    taskNavigation.getTaskLoadFailureAction({ response: { status: 404 } }),
    'redirect_home',
  );
  assert.equal(
    taskNavigation.getTaskLoadFailureAction({ response: { status: 503 } }),
    'retry',
  );
  assert.equal(taskNavigation.getTaskLoadFailureAction(new Error('offline')), 'retry');
  const staleScope = taskNavigation.createTaskLoadScope('task-a');
  staleScope.cancel();
  assert.equal(staleScope.isActive(), false);
});

test('the recent-task row does not navigate when its delete control is used', async (t) => {
  const module = await loadDashboardModule(t);
  assert.equal(typeof module.TaskListItem, 'function');

  const item = module.TaskListItem({
    task: { id: 'task-delete', product_description: '待删除任务', status: 'running' },
    status: { label: '运行中', tone: 'running' },
    onOpen: () => {},
    onDelete: () => {},
  });

  assert.equal(item.props.onClick, undefined);
});
