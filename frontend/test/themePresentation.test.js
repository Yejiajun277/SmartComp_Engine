import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

test('global theme toggle exposes the next action and current pressed state', async (t) => {
  const vite = await createServer({
    appType: 'custom',
    configFile: false,
    logLevel: 'silent',
    server: { middlewareMode: true },
  });
  t.after(() => vite.close());
  const { default: ThemeToggle } = await vite.ssrLoadModule('/src/components/ThemeToggle.jsx');

  const light = renderToStaticMarkup(
    React.createElement(ThemeToggle, { appTheme: 'light', onToggle: () => {} }),
  );
  const dark = renderToStaticMarkup(
    React.createElement(ThemeToggle, { appTheme: 'dark', onToggle: () => {} }),
  );

  assert.match(light, /aria-pressed="false"/);
  assert.match(light, /切换到深色模式/);
  assert.match(light, />深色模式</);
  assert.match(dark, /aria-pressed="true"/);
  assert.match(dark, /切换到浅色模式/);
  assert.match(dark, />浅色模式</);
});

test('workflow canvas follows the app theme without a local theme control', async (t) => {
  const vite = await createServer({
    appType: 'custom',
    configFile: false,
    logLevel: 'silent',
    server: { middlewareMode: true },
  });
  t.after(() => vite.close());
  const { default: PipelineGraph } = await vite.ssrLoadModule('/src/components/PipelineGraph.jsx');
  const html = renderToStaticMarkup(React.createElement(PipelineGraph));

  assert.doesNotMatch(html, /切换画布主题/);
  assert.doesNotMatch(html, /深色画布|浅色画布/);
  assert.match(html, /title="重置画布"/);
  assert.match(html, /静态执行图/);
});
