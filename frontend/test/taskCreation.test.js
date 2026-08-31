import test from 'node:test';
import assert from 'node:assert/strict';
import axios from 'axios';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

test('task request defaults to three competitors while preserving explicit values', async (t) => {
  const originalAdapter = axios.defaults.adapter;
  const requests = [];
  axios.defaults.adapter = async (config) => {
    requests.push(JSON.parse(config.data));
    return {
      data: { task_id: 'task-default-three', status: 'pending' },
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    };
  };
  t.after(() => {
    axios.defaults.adapter = originalAdapter;
  });

  const { submitTask } = await import('../src/api/client.js?task-default-three');
  await submitTask('飞书');
  await submitTask('飞书', 6, true, true);

  assert.deepEqual(requests, [
    {
      product_description: '飞书',
      max_competitors: 3,
      skip_qa: false,
      use_rule_engine: false,
    },
    {
      product_description: '飞书',
      max_competitors: 6,
      skip_qa: true,
      use_rule_engine: true,
    },
  ]);
});

test('task form initially displays three competitors', async (t) => {
  const vite = await createServer({
    appType: 'custom',
    configFile: false,
    logLevel: 'silent',
    server: { middlewareMode: true },
  });
  t.after(() => vite.close());
  const { default: TaskForm } = await vite.ssrLoadModule('/src/components/TaskForm.jsx');
  const html = renderToStaticMarkup(React.createElement(TaskForm, {
    onSubmit: () => {},
    loading: false,
    runtimeConfig: {
      llm: { configured: true, provider: 'mimo', model: 'mimo-v2' },
      search: { configured: false, provider: 'none', model: null },
      default_mode: 'model',
    },
    runtimeLoading: false,
  }));
  const input = html.match(/<input[^>]*id="maxCompetitors"[^>]*>/)?.[0] || '';

  assert.match(input, /aria-valuenow="3"/);
  assert.match(input, /value="3"/);
});
