import test from 'node:test';
import assert from 'node:assert/strict';
import * as appTheme from '../src/utils/appTheme.js';

test('stored app theme wins over the system preference', () => {
  assert.equal(appTheme.resolveAppTheme('dark', false), 'dark');
  assert.equal(appTheme.resolveAppTheme('light', true), 'light');
});

test('missing or invalid storage falls back to the system preference', () => {
  assert.equal(appTheme.resolveAppTheme(null, true), 'dark');
  assert.equal(appTheme.resolveAppTheme('broken', false), 'light');
});

test('storage failures never block the current session', () => {
  const throwingStorage = {
    getItem() { throw new Error('blocked'); },
    setItem() { throw new Error('blocked'); },
  };
  assert.equal(appTheme.readStoredAppTheme(throwingStorage), null);
  assert.equal(appTheme.writeStoredAppTheme(throwingStorage, 'dark'), false);

  const browser = {};
  Object.defineProperty(browser, 'localStorage', {
    get() { throw new Error('blocked'); },
  });
  assert.equal(appTheme.getAppThemeStorage(browser), null);
});

test('manual app theme choices persist and toggle predictably', () => {
  const values = new Map();
  const storage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
  assert.equal(appTheme.writeStoredAppTheme(storage, 'dark'), true);
  assert.equal(appTheme.readStoredAppTheme(storage), 'dark');
  assert.equal(appTheme.getNextAppTheme('dark'), 'light');
  assert.equal(appTheme.getNextAppTheme('light'), 'dark');
});

test('applying a theme updates the root dataset and browser color scheme', () => {
  const root = { dataset: {}, style: {} };
  assert.equal(appTheme.applyAppTheme(root, 'dark'), 'dark');
  assert.equal(root.dataset.theme, 'dark');
  assert.equal(root.style.colorScheme, 'dark');
});
