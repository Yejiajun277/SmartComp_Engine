import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import axios from 'axios';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build, createServer } from 'vite';
import * as appBase from '../src/utils/appBase.js';

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('production build publishes browser assets below /smartcomp/', async () => {
  const result = await build({
    root: frontendRoot,
    configFile: path.join(frontendRoot, 'vite.config.js'),
    mode: 'production',
    logLevel: 'silent',
    build: { write: false },
  });
  const output = Array.isArray(result)
    ? result.flatMap(item => item.output)
    : result.output;
  const index = output.find(item => item.fileName === 'index.html');

  assert.ok(index, 'Vite should emit index.html');
  const html = String(index.source);
  assert.match(html, /(?:src|href)="\/smartcomp\/assets\//);
  assert.match(html, /href="\/smartcomp\/favicon\.svg"/);
});

test('production API requests stay below the SmartComp public prefix', async (t) => {
  const originalAdapter = axios.defaults.adapter;
  const requests = [];
  axios.defaults.adapter = async (config) => {
    requests.push(config);
    return {
      data: [],
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    };
  };

  const vite = await createServer({
    root: frontendRoot,
    configFile: path.join(frontendRoot, 'vite.config.js'),
    mode: 'production',
    appType: 'custom',
    logLevel: 'silent',
    server: { middlewareMode: true },
  });
  t.after(async () => {
    axios.defaults.adapter = originalAdapter;
    await vite.close();
  });

  const { getTasks } = await vite.ssrLoadModule('/src/api/client.js?app-base-test');
  await getTasks();

  assert.equal(requests.length, 1);
  assert.equal(requests[0].baseURL, '/smartcomp/api');
  assert.equal(requests[0].url, '/tasks');
});

test('websocket URLs preserve the public app prefix and transport security', () => {
  assert.equal(typeof appBase.buildWebSocketUrl, 'function');
  assert.equal(
    appBase.buildWebSocketUrl(
      { protocol: 'https:', host: 'example.test' },
      '/ws/tasks/task-42',
      '/smartcomp/',
    ),
    'wss://example.test/smartcomp/ws/tasks/task-42',
  );
  assert.equal(
    appBase.buildWebSocketUrl(
      { protocol: 'http:', host: '127.0.0.1:5173' },
      '/ws/tasks/task-42',
      '/',
    ),
    'ws://127.0.0.1:5173/ws/tasks/task-42',
  );
});

test('production router renders the application below /smartcomp/', async (t) => {
  const originalWindow = globalThis.window;
  const originalDocument = globalThis.document;
  const location = {
    pathname: '/smartcomp/',
    search: '',
    hash: '',
    href: 'http://example.test/smartcomp/',
    origin: 'http://example.test',
  };
  const history = {
    state: null,
    pushState() {},
    replaceState() {},
    go() {},
  };
  const windowStub = {
    location,
    history,
    addEventListener() {},
    removeEventListener() {},
    matchMedia: () => ({ matches: false }),
  };
  globalThis.window = windowStub;
  globalThis.document = { defaultView: windowStub };

  const vite = await createServer({
    root: frontendRoot,
    configFile: path.join(frontendRoot, 'vite.config.js'),
    mode: 'production',
    appType: 'custom',
    logLevel: 'silent',
    server: { middlewareMode: true },
  });
  t.after(async () => {
    await vite.close();
    globalThis.window = originalWindow;
    globalThis.document = originalDocument;
  });

  const { default: App } = await vite.ssrLoadModule('/src/App.jsx?app-base-router-test');
  const html = renderToStaticMarkup(React.createElement(App));

  assert.match(html, /class="[^"]*dashboard-page/);
});

test('embedded HTML reports stay below the public app prefix', () => {
  assert.equal(typeof appBase.buildTaskReportPath, 'function');
  assert.equal(
    appBase.buildTaskReportPath('task-42', '/smartcomp/'),
    '/smartcomp/api/tasks/task-42/report.html',
  );
});
