import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { createServer } from 'vite';
import { updateLlmLogPagination } from '../src/utils/llmLogs.js';

async function loadLlmLogsModule(t) {
  const vite = await createServer({
    appType: 'custom',
    configFile: false,
    logLevel: 'silent',
    server: { middlewareMode: true },
  });
  t.after(() => vite.close());

  return vite.ssrLoadModule('/src/components/LlmLogs.jsx');
}

test('technical trace applies the selected 10, 20, 50, or 100 row page size', async (t) => {
  const module = await loadLlmLogsModule(t);

  assert.equal(typeof module.LlmLogsTable, 'function');

  const table = module.LlmLogsTable({
    logs: [],
    columns: [],
    pagination: { current: 1, pageSize: 20 },
    onPaginationChange: () => {},
  });
  assert.equal(React.isValidElement(table), true);
  assert.equal(table.props.pagination.current, 1);
  assert.equal(table.props.pagination.pageSize, 20);
  assert.deepEqual(Array.from(table.props.pagination.pageSizeOptions), [10, 20, 50, 100]);
  assert.equal(table.props.pagination.showSizeChanger, true);
});

test('technical trace retains the selected page size when refreshed logs remount the table', () => {
  const selected = updateLlmLogPagination(
    { current: 3, pageSize: 10 },
    { current: 2, pageSize: 50 },
  );
  const nextPage = updateLlmLogPagination(selected, { current: 2, pageSize: 50 });

  assert.deepEqual(selected, { current: 1, pageSize: 50 });
  assert.deepEqual(nextPage, { current: 2, pageSize: 50 });
});
