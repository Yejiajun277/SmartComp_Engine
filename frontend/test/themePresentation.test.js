import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

function getDeclarationBlock(css, selectors) {
  const block = [...css.matchAll(/(?<selector>[^{}]+)\{(?<declarations>[^{}]*)\}/g)]
    .find(({ groups }) => selectors.every(selector => groups.selector.includes(selector)));

  assert.ok(block, `missing CSS block for ${selectors.join(' and ')}`);
  return block.groups.declarations;
}

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

test('global styles define one semantic dark theme contract', async () => {
  const appCss = await readFile(new URL('../src/App.css', import.meta.url), 'utf8');
  const indexCss = await readFile(new URL('../src/index.css', import.meta.url), 'utf8');
  const darkThemeDeclarations = getDeclarationBlock(appCss, [
    ":root[data-theme='dark']",
    ".app-shell[data-theme='dark']",
  ]);
  const documentDarkDeclarations = getDeclarationBlock(indexCss, ["html[data-theme='dark']"]);

  const requiredDarkTokens = [
    '--sc-bg',
    '--sc-bg-soft',
    '--sc-surface',
    '--sc-surface-soft',
    '--sc-surface-elevated',
    '--sc-control-bg',
    '--sc-control-solid',
    '--sc-header-bg',
    '--sc-code-bg',
    '--sc-overlay',
    '--sc-ink',
    '--sc-text',
    '--sc-muted',
    '--sc-border',
    '--sc-border-strong',
    '--sc-blue',
    '--sc-blue-soft',
    '--sc-mint',
    '--sc-mint-bright',
    '--sc-violet',
    '--sc-amber',
    '--sc-danger',
    '--sc-on-accent',
    '--sc-shadow-soft',
  ];

  for (const token of requiredDarkTokens) {
    assert.match(darkThemeDeclarations, new RegExp(`${token}\\s*:\\s*[^;]+;`));
  }

  assert.match(documentDarkDeclarations, /color-scheme\s*:\s*dark\s*;/);
  assert.match(documentDarkDeclarations, /background\s*:\s*#07111d\s*;/);
  assert.doesNotMatch(appCss, /\.workflow-canvas\[data-theme='dark'\]/);
});

test('dashboard messages use the app-scoped Ant Design theme context', async () => {
  const appSource = await readFile(new URL('../src/App.jsx', import.meta.url), 'utf8');
  const dashboardSource = await readFile(new URL('../src/pages/Dashboard.jsx', import.meta.url), 'utf8');

  assert.match(appSource, /import\s*\{[^}]*\bApp\s+as\s+AntdApp\b[^}]*\}\s*from\s*['"]antd['"]/);
  assert.match(appSource, /<AntdApp\s+component=\{false\}>/);
  assert.match(dashboardSource, /import\s*\{[^}]*\bApp\s+as\s+AntdApp\b[^}]*\}\s*from\s*['"]antd['"]/);
  assert.match(dashboardSource, /AntdApp\.useApp\(\)/);
  assert.doesNotMatch(dashboardSource, /import\s*\{[^}]*\bmessage\b[^}]*\}\s*from\s*['"]antd['"]/);
  assert.doesNotMatch(dashboardSource, /\bmessage\.(?:success|error)\s*\(/);
});
