import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

test('renders the requested quick experience options in order', async (t) => {
  const vite = await createServer({
    appType: 'custom',
    configFile: false,
    logLevel: 'silent',
    server: { middlewareMode: true },
  });
  t.after(() => vite.close());

  const { default: HomeHero } = await vite.ssrLoadModule(
    '/src/components/dashboard/HomeHero.jsx',
  );
  const html = renderToStaticMarkup(
    React.createElement(HomeHero, { onExampleSelect: () => {} }),
  );
  const options = [...html.matchAll(/<button[^>]*>([^<]+)<\/button>/g)]
    .map(match => match[1]);

  assert.deepEqual(options, ['飞书', '小米汽车', 'IPhone17', '蜜雪冰城', 'NIKE']);
});
