# Global Light and Dark Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the workflow-only canvas theme with one persistent application-wide light/dark theme that keeps Ant Design, custom pages, and the DAG visually consistent.

**Architecture:** `App.jsx` owns the only theme state and applies it to both Ant Design and the application root. A focused `appTheme.js` module handles validation, browser preference resolution, persistence, toggling, and root attributes; `ThemeToggle.jsx` is the global header control. CSS keeps semantic `--sc-*` tokens, adds dark values at the root/application boundary, and makes the workflow canvas inherit those values instead of maintaining local state.

**Tech Stack:** React 19, Ant Design 6, React Router, CSS custom properties, Node built-in test runner, Vite SSR test loading.

**Spec:** `docs/superpowers/specs/2026-08-30-global-theme-design.md`

## Global Constraints

- Theme values are exactly `light` and `dark`; do not add a third UI state.
- First visit follows `prefers-color-scheme`; only a manual toggle writes the browser preference.
- The top header owns the theme switch; the workflow canvas must not expose an independent theme control.
- Ant Design and custom CSS must switch together.
- The generated full-report iframe keeps its authored styles; only the report page shell and iframe container follow the app theme.
- Preserve the existing blue/mint brand and workflow status meanings in both themes.
- Add no dependency and make no backend, database, permission, or API change.
- Use only targeted frontend tests and browser checks; do not run a real LLM, live web analysis, or the backend full pipeline.
- Work in `G:\SmartComp_Engine` on `codex/dag-canvas-workflow`; local commits only unless the user separately requests integration.

---

## File Structure

- Create `frontend/src/utils/appTheme.js`: the only browser-independent theme model and persistence boundary.
- Create `frontend/src/components/ThemeToggle.jsx`: the application-level accessible theme control.
- Create `frontend/test/appTheme.test.js`: pure theme resolution, persistence, toggle, and root-application tests.
- Create `frontend/test/themePresentation.test.js`: Vite SSR checks for toggle copy and the absence of a canvas-only theme control, plus stylesheet contract checks.
- Modify `frontend/src/App.jsx`: own theme state, configure Ant Design, apply root state, and render header actions.
- Modify `frontend/src/index.css`: set the document/body background and `color-scheme` for both themes.
- Modify `frontend/src/App.css`: define semantic dark tokens, style the header control, migrate light-only surfaces, and make the DAG inherit the global theme.
- Modify `frontend/src/components/PipelineGraph.jsx`: remove local theme state, imports, attributes, and button.

---

### Task 1: Theme State Model

**Files:**
- Create: `frontend/src/utils/appTheme.js`
- Create: `frontend/test/appTheme.test.js`

**Interfaces:**
- Produces: `APP_THEME_STORAGE_KEY: string`
- Produces: `isAppTheme(value): boolean`
- Produces: `getAppThemeStorage(browser): Storage | null`
- Produces: `resolveAppTheme(storedTheme, systemPrefersDark): 'light' | 'dark'`
- Produces: `readStoredAppTheme(storage): 'light' | 'dark' | null`
- Produces: `writeStoredAppTheme(storage, value): boolean`
- Produces: `getNextAppTheme(current): 'light' | 'dark'`
- Produces: `applyAppTheme(root, value): 'light' | 'dark'`

- [ ] **Step 1: Write the failing theme model tests**

```js
// frontend/test/appTheme.test.js
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
```

- [ ] **Step 2: Run the new test and verify the red state**

Run: `node --test test/appTheme.test.js`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `src/utils/appTheme.js`.

- [ ] **Step 3: Implement the minimal theme model**

```js
// frontend/src/utils/appTheme.js
export const APP_THEME_STORAGE_KEY = 'smartcomp-theme';

export function isAppTheme(value) {
  return value === 'light' || value === 'dark';
}

export function getAppThemeStorage(browser) {
  try {
    return browser?.localStorage ?? null;
  } catch {
    return null;
  }
}

export function resolveAppTheme(storedTheme, systemPrefersDark = false) {
  if (isAppTheme(storedTheme)) return storedTheme;
  return systemPrefersDark ? 'dark' : 'light';
}

export function readStoredAppTheme(storage) {
  if (!storage) return null;
  try {
    const value = storage.getItem(APP_THEME_STORAGE_KEY);
    return isAppTheme(value) ? value : null;
  } catch {
    return null;
  }
}

export function writeStoredAppTheme(storage, value) {
  if (!storage || !isAppTheme(value)) return false;
  try {
    storage.setItem(APP_THEME_STORAGE_KEY, value);
    return true;
  } catch {
    return false;
  }
}

export function getNextAppTheme(current) {
  return current === 'dark' ? 'light' : 'dark';
}

export function applyAppTheme(root, value) {
  const resolved = isAppTheme(value) ? value : 'light';
  if (root?.dataset) root.dataset.theme = resolved;
  if (root?.style) root.style.colorScheme = resolved;
  return resolved;
}
```

- [ ] **Step 4: Run the focused test and verify the green state**

Run: `node --test test/appTheme.test.js`

Expected: 5 tests pass, 0 fail.

- [ ] **Step 5: Commit the state model**

```powershell
git add frontend/src/utils/appTheme.js frontend/test/appTheme.test.js
git commit -m "feat(frontend): add global theme state model"
```

---

### Task 2: Global Header Toggle and Ant Design Integration

**Files:**
- Create: `frontend/src/components/ThemeToggle.jsx`
- Create: `frontend/test/themePresentation.test.js`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/App.css`

**Interfaces:**
- Consumes: all exports from `frontend/src/utils/appTheme.js`
- Produces: `ThemeToggle({ appTheme, onToggle })`
- Produces: `.app-header-actions` and `.app-theme-toggle` layout hooks
- Produces: `<Layout className="app-shell" data-theme={appTheme}>`

- [ ] **Step 1: Write a failing accessible-toggle presentation test**

```js
// frontend/test/themePresentation.test.js
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
```

- [ ] **Step 2: Run the presentation test and verify the red state**

Run: `node --test test/themePresentation.test.js`

Expected: FAIL because `ThemeToggle.jsx` does not exist.

- [ ] **Step 3: Create the global header control**

```jsx
// frontend/src/components/ThemeToggle.jsx
import { MoonOutlined, SunOutlined } from '@ant-design/icons';

export default function ThemeToggle({ appTheme, onToggle }) {
  const dark = appTheme === 'dark';
  const nextAction = dark ? '切换到浅色模式' : '切换到深色模式';
  return (
    <button
      type="button"
      className="app-theme-toggle"
      aria-pressed={dark}
      aria-label={nextAction}
      title={nextAction}
      onClick={onToggle}
    >
      {dark ? <SunOutlined aria-hidden="true" /> : <MoonOutlined aria-hidden="true" />}
      <span>{dark ? '浅色模式' : '深色模式'}</span>
    </button>
  );
}
```

- [ ] **Step 4: Move theme ownership into `App.jsx`**

Add imports for `ThemeToggle` and the theme helpers, then initialize and apply the state:

```jsx
const [appTheme, setAppTheme] = useState(() => {
  const storage = getAppThemeStorage(typeof window === 'undefined' ? null : window);
  const storedTheme = readStoredAppTheme(storage);
  const systemPrefersDark = typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-color-scheme: dark)').matches;
  return resolveAppTheme(storedTheme, systemPrefersDark);
});

useEffect(() => {
  if (typeof document !== 'undefined') applyAppTheme(document.documentElement, appTheme);
}, [appTheme]);

const handleThemeToggle = () => {
  setAppTheme((current) => {
    const next = getNextAppTheme(current);
    const storage = getAppThemeStorage(typeof window === 'undefined' ? null : window);
    writeStoredAppTheme(storage, next);
    return next;
  });
};
```

Configure Ant Design and the application root from the same value:

```jsx
<ConfigProvider
  theme={{
    algorithm: appTheme === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: '#176bff',
      colorInfo: '#176bff',
      colorSuccess: appTheme === 'dark' ? '#37d5ad' : '#0aa886',
      colorWarning: appTheme === 'dark' ? '#f4b14a' : '#d88915',
      colorError: appTheme === 'dark' ? '#ff7380' : '#e5484d',
      colorBgBase: appTheme === 'dark' ? '#07111d' : '#f5f7f8',
      colorTextBase: appTheme === 'dark' ? '#eef4fb' : '#111827',
      borderRadius: 12,
      fontFamily: "Inter, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    },
  }}
>
  <BrowserRouter>
    <Layout className="app-shell" data-theme={appTheme}>
```

Wrap the right side of the header so the fourth child does not create an implicit grid row:

```jsx
<div className="app-header-actions">
  <RuntimeStatus config={runtimeConfig} compact loading={runtimeLoading} />
  <ThemeToggle appTheme={appTheme} onToggle={handleThemeToggle} />
</div>
```

- [ ] **Step 5: Add header-control layout and mobile behavior**

```css
.app-header-actions {
  display: flex;
  justify-self: end;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.app-theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid var(--sc-border);
  border-radius: 12px;
  color: var(--sc-ink);
  background: var(--sc-control-bg);
  cursor: pointer;
}

@media (max-width: 767px) {
  .app-header-actions { gap: 7px; }
  .runtime-status-compact {
    width: min(142px, 40vw);
    flex-basis: min(142px, 40vw);
    max-width: 142px;
  }
  .runtime-status-copy strong {
    max-width: calc(min(142px, 40vw) - 36px);
  }
  .app-theme-toggle { width: 38px; flex: 0 0 38px; padding: 0; }
  .app-theme-toggle span:not(.anticon) { display: none; }
}
```

- [ ] **Step 6: Run focused checks**

Run: `node --test test/appTheme.test.js test/themePresentation.test.js`

Expected: 6 tests pass, 0 fail.

Run: `npm.cmd run lint`

Expected: exit 0.

- [ ] **Step 7: Commit the global control**

```powershell
git add frontend/src/App.jsx frontend/src/App.css frontend/src/components/ThemeToggle.jsx frontend/test/themePresentation.test.js
git commit -m "feat(frontend): add application theme toggle"
```

---

### Task 3: Remove the Canvas-Only Theme

**Files:**
- Modify: `frontend/src/components/PipelineGraph.jsx`
- Modify: `frontend/src/App.css`
- Modify: `frontend/test/themePresentation.test.js`

**Interfaces:**
- Consumes: global `data-theme` and `--sc-*` tokens from Task 2
- Preserves: workflow zoom, reset, stage selection, mobile focus, node inspection, and all DAG state semantics
- Removes: component-local `theme`, `setTheme`, `data-theme`, `canvas-theme-label`, and “切换画布主题” button

- [ ] **Step 1: Add a failing SSR assertion for a single global theme owner**

Add the `readFile` import beside the existing imports, then append the test to `frontend/test/themePresentation.test.js`:

```js
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
```

- [ ] **Step 2: Run the test and verify it fails for the current local button**

Run: `node --test test/themePresentation.test.js`

Expected: FAIL because the rendered canvas contains `title="切换画布主题"` and `深色画布`.

- [ ] **Step 3: Remove local theme state and markup**

In `PipelineGraph.jsx`:

- Remove `MoonOutlined` and `SunOutlined` imports.
- Remove `const [theme, setTheme] = useState('light');`.
- Change the root to `<div className="workflow-canvas" data-mobile={...}>`.
- Delete the theme button; keep the zoom group and reset button unchanged.

- [ ] **Step 4: Move canvas dark variables under the global selector**

Replace:

```css
.workflow-canvas[data-theme='dark'] {
```

with:

```css
:root[data-theme='dark'] .workflow-canvas,
.app-shell[data-theme='dark'] .workflow-canvas {
```

Replace toolbar light literals in the same pass:

```css
.workflow-canvas-toolbar {
  border-color: var(--sc-border);
  background: var(--sc-surface-soft);
}

.canvas-toolbar-actions > button,
.canvas-zoom-group {
  border-color: var(--sc-border);
  color: var(--sc-muted);
  background: var(--sc-control-solid);
}

.canvas-zoom-group strong { color: var(--sc-ink); }
```

Remove the now-unused `.canvas-theme-label` mobile selector.

- [ ] **Step 5: Run focused canvas and presentation tests**

Run: `node --test test/themePresentation.test.js test/workflowCanvas.test.js`

Expected: all tests pass and no local theme copy remains.

Run: `npm.cmd run lint`

Expected: exit 0 with no unused icon/state import.

- [ ] **Step 6: Commit the canvas integration**

```powershell
git add frontend/src/components/PipelineGraph.jsx frontend/src/App.css frontend/test/themePresentation.test.js
git commit -m "refactor(frontend): make workflow follow app theme"
```

---

### Task 4: Complete the Global Dark Surface System

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/App.css`
- Modify: `frontend/test/themePresentation.test.js`

**Interfaces:**
- Consumes: `data-theme="dark"` on both `html` and `.app-shell`
- Produces: semantic dark values for `--sc-bg`, surfaces, text, borders, controls, code, overlays, and shadows
- Preserves: full-report iframe content without CSS injection

- [ ] **Step 1: Add a failing stylesheet contract test**

Append to `frontend/test/themePresentation.test.js`:

```js
import { readFile } from 'node:fs/promises';

test('global styles define one semantic dark theme contract', async () => {
  const appCss = await readFile(new URL('../src/App.css', import.meta.url), 'utf8');
  const indexCss = await readFile(new URL('../src/index.css', import.meta.url), 'utf8');

  assert.match(appCss, /:root\[data-theme='dark'\]/);
  assert.match(appCss, /--sc-control-bg:/);
  assert.match(appCss, /--sc-code-bg:/);
  assert.match(indexCss, /html\[data-theme='dark'\]/);
  assert.doesNotMatch(appCss, /\.workflow-canvas\[data-theme='dark'\]/);
});
```

- [ ] **Step 2: Run the contract test and verify the missing semantic tokens fail**

Run: `node --test test/themePresentation.test.js`

Expected: FAIL because the global dark token contract and document selector are incomplete.

- [ ] **Step 3: Extend the semantic token set**

Add the following light defaults to `:root` in `App.css`:

```css
--sc-surface-elevated: #ffffff;
--sc-control-bg: rgba(255, 255, 255, 0.72);
--sc-control-solid: #ffffff;
--sc-header-bg: rgba(250, 252, 252, 0.82);
--sc-code-bg: #0b1220;
--sc-overlay: rgba(4, 10, 20, 0.26);
--sc-on-accent: #ffffff;
```

Add the dark values once for the immediate app render and the document/portal boundary:

```css
:root[data-theme='dark'],
.app-shell[data-theme='dark'] {
  --sc-bg: #07111d;
  --sc-bg-soft: #0b1725;
  --sc-surface: #0f1c2b;
  --sc-surface-soft: #122235;
  --sc-surface-elevated: #16283d;
  --sc-control-bg: rgba(19, 35, 53, 0.86);
  --sc-control-solid: #132235;
  --sc-header-bg: rgba(7, 17, 29, 0.84);
  --sc-code-bg: #07101b;
  --sc-overlay: rgba(0, 0, 0, 0.42);
  --sc-ink: #f3f7fd;
  --sc-text: #dce7f4;
  --sc-muted: #93a5ba;
  --sc-border: rgba(166, 190, 219, 0.14);
  --sc-border-strong: rgba(166, 190, 219, 0.24);
  --sc-blue: #6c9fff;
  --sc-blue-soft: rgba(108, 159, 255, 0.15);
  --sc-mint: #37d5ad;
  --sc-mint-bright: #62e8c7;
  --sc-violet: #9587ff;
  --sc-amber: #f4b14a;
  --sc-danger: #ff7380;
  --sc-on-accent: #ffffff;
  --sc-shadow-soft: 0 20px 70px rgba(0, 0, 0, 0.28);
}
```

- [ ] **Step 4: Make the document boundary theme-aware**

In `index.css`, replace fixed document colors with variables and add the dark fallback:

```css
html,
body {
  color: var(--sc-text, #111827);
  background: var(--sc-bg, #f4f7f7);
}

html[data-theme='dark'] {
  color-scheme: dark;
  background: #07111d;
}
```

Keep the existing `min-width`, typography, body sizing, selection, focus, and reduced-motion rules.

- [ ] **Step 5: Migrate visible light-only surfaces by responsibility**

Use semantic tokens for the following exact UI groups; white-on-brand text remains `var(--sc-on-accent)`:

```css
.app-header { background: var(--sc-header-bg); }
.runtime-status-compact,
.surface-card,
.workflow-stage-nav button,
.workflow-canvas-toolbar,
.workflow-activity-collapse,
.report-view-tabs,
.full-report-panel,
.report-json-panel { background: var(--sc-surface); border-color: var(--sc-border); }

.home-hero-form,
.runtime-status-panel,
.task-item,
.empty-task-state,
.mission-header,
.dag-inspector,
.report-iframe-wrap { background: var(--sc-surface-soft); border-color: var(--sc-border); }

.app-theme-toggle,
.home-hero-quick button,
.report-view-tabs button,
.workbench-back { color: var(--sc-ink); background: var(--sc-control-bg); }

.report-json-panel pre { color: #dce7f4; background: var(--sc-code-bg); }
```

For selectors that already have status-specific blue, mint, amber, or red backgrounds, replace only their neutral base/border/text values; do not erase the status tone. Replace remaining visible `#fff`, `#fbfcfe`, `#f4f6f8`, and `rgba(255, 255, 255, …)` only when they represent a neutral surface, not when they represent text on an accent.

- [ ] **Step 6: Add theme transitions without violating reduced motion**

```css
.app-shell,
.app-header,
.surface-card,
.workflow-canvas,
.dag-node,
.dag-inspector,
.app-theme-toggle {
  transition: color 160ms ease, background-color 160ms ease, border-color 160ms ease;
}

@media (prefers-reduced-motion: reduce) {
  .app-shell,
  .app-header,
  .surface-card,
  .workflow-canvas,
  .dag-node,
  .dag-inspector,
  .app-theme-toggle { transition: none; }
}
```

- [ ] **Step 7: Run targeted and full static verification**

Run: `node --test test/appTheme.test.js test/themePresentation.test.js test/workflowCanvas.test.js`

Expected: all focused tests pass.

Run: `npm.cmd test`

Expected: the complete frontend suite passes with 0 failures.

Run: `npm.cmd run lint`

Expected: exit 0.

- [ ] **Step 8: Commit the surface system**

```powershell
git add frontend/src/index.css frontend/src/App.css frontend/test/themePresentation.test.js
git commit -m "feat(frontend): apply global dark surface system"
```

---

### Task 5: Browser Acceptance and Final Verification

**Files:**
- Modify only if browser evidence reveals a concrete defect: `frontend/src/App.css`, `frontend/src/App.jsx`, `frontend/src/components/ThemeToggle.jsx`, or `frontend/src/components/PipelineGraph.jsx`
- Add a regression to `frontend/test/appTheme.test.js` or `frontend/test/themePresentation.test.js` before fixing any discovered behavior defect

**Interfaces:**
- Validates the complete app theme across `/`, `/tasks/d5f72529`, and `/tasks/d5f72529/report`
- Does not invoke task creation, LLM calls, web search, or QA execution

- [ ] **Step 1: Produce a fresh production build**

Run: `npm.cmd run build`

Expected: Vite exits 0. The existing chunk-size warning may remain; no new build error is accepted.

- [ ] **Step 2: Inspect desktop light and dark states in a real browser**

Use a temporary hidden Edge instance and the already completed task `d5f72529`. At a viewport around `1392×900`, capture `/`, `/tasks/d5f72529`, and `/tasks/d5f72529/report` before and after the global toggle.

For every route assert from computed styles and screenshots:

- `html.dataset.theme` and `.app-shell.dataset.theme` are both `dark` after the click;
- the Ant Design page background and custom card surfaces are dark together;
- the header control reads “浅色模式” in dark mode;
- the workflow toolbar still shows “重置” with readable contrast;
- no “深色画布/浅色画布” control remains;
- report iframe content is unchanged while its outer panel is dark;
- no replacement characters or page-level horizontal overflow appear.

- [ ] **Step 3: Verify persistence and route continuity**

With the theme set to dark, reload the current route and navigate among the three routes. Confirm dark remains active and the task/report state does not reset. Switch to light, reload once, and confirm light persists.

- [ ] **Step 4: Inspect mobile light and dark states**

Repeat `/` and `/tasks/d5f72529` at `360×800` and `430×932`:

- the theme control is icon-only but retains a non-empty `aria-label` and `title`;
- header brand, runtime status, and theme button remain on one row without overlap;
- the workflow remains at 72% default zoom and current-stage focus;
- the theme button, zoom controls, and reset icon remain visible;
- document width equals viewport width.

- [ ] **Step 5: Convert any visual defect into a red-green fix**

If evidence shows a behavior defect, first add the smallest failing assertion to the applicable test file, run it red, implement one fix, then rerun it green. For purely visual contrast/spacing defects, record the failing selector and computed colors before changing only that selector.

- [ ] **Step 6: Run the final verification gate**

Run: `npm.cmd test`

Expected: full suite passes, 0 fail.

Run: `npm.cmd run lint`

Expected: exit 0.

Run: `npm.cmd run build`

Expected: exit 0 with only the known chunk-size advisory allowed.

Run: `git diff --check`

Expected: no output and exit 0.

- [ ] **Step 7: Request an independent read-only review**

Provide the reviewer the spec path, plan path, current commit range, and browser evidence. Require explicit review of theme ownership, persistence, Ant Design synchronization, canvas regression, mobile header layout, contrast, and report iframe isolation. Resolve every Critical or Important issue before proceeding.

- [ ] **Step 8: Commit final acceptance fixes, if any**

```powershell
git add frontend/src frontend/test
git commit -m "fix(frontend): polish global theme presentation"
```

Skip this commit only when browser acceptance and review require no code change after Task 4.
