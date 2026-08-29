# SmartComp Engine Competition UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the existing React UI into a competition-ready, evidence-led strategy command center without changing the backend workflow or LLM behavior.

**Architecture:** Keep the three existing routes and all REST/WebSocket contracts. Add a shared visual shell and small presentational components, move display-only calculations into tested pure utilities, make QualityAgent gates explicit in the pipeline, and add a decision-first React layer above the existing HTML report iframe.

**Tech Stack:** React 19, React Router 7, Ant Design 6, Vite 8, CSS, Node built-in test runner.

**Spec:** `docs/superpowers/specs/2026-08-29-competition-ui-design.md`

## Global Constraints

- Baseline is commit `5236690` from `final_work`; do not merge `newest`.
- Work only on `codex/competition-ui` in the existing isolated worktree.
- Do not change workflow orchestration, domain models, persistence, permissions, or real LLM/search behavior.
- Reuse `/api/tasks`, `/api/tasks/:id`, artifact, report, log, and `/ws/tasks/:id` contracts.
- Do not add a web-font dependency, charting library, animation library, test framework, or backend dependency.
- QA status must distinguish normal pass, failure/retry, running, and degraded pass in text and color.
- Missing API data must render an honest empty state; never insert demo metrics into real tasks.
- Any Python command must run through Conda environment `smartcomp-engine-dev`.
- Do not run a real LLM or network analysis; final smoke testing may use one rule-engine task only if needed.

---

## Planned File Structure

**Create**

- `frontend/src/components/BrandMark.jsx` — reusable brand glyph and wordmark.
- `frontend/src/components/dashboard/HomeHero.jsx` — value proposition, proof points, and example product shortcuts.
- `frontend/src/components/workbench/LiveActivityRail.jsx` — human-readable recent event stream.
- `frontend/src/components/workbench/QualityCockpit.jsx` — aggregate quality metrics and retry summary.
- `frontend/src/components/report/ReportOverview.jsx` — positioning, priority actions, and trust summary.
- `frontend/src/components/QAGate.jsx` — explicit QualityAgent gate in the pipeline.
- `frontend/src/utils/presentation.js` — task status, merge, elapsed-time, and event-label helpers.
- `frontend/src/utils/quality.js` — QA aggregation and pipeline gate helpers.
- `frontend/src/utils/report.js` — report overview derivation.
- `frontend/test/presentation.test.js` — pure dashboard/event utility tests.
- `frontend/test/quality.test.js` — pure QA aggregation/gate tests.
- `frontend/test/report.test.js` — pure report overview tests.

**Modify**

- `frontend/package.json` — add the dependency-free `node --test` script.
- `frontend/src/App.jsx` — shared application shell and route container.
- `frontend/src/App.css` — replace unused Vite template CSS with the complete design system and responsive rules.
- `frontend/src/index.css` — global reset, typography, focus, and reduced-motion rules.
- `frontend/src/pages/Dashboard.jsx` — narrative homepage and task list.
- `frontend/src/components/TaskForm.jsx` — simplified launcher and advanced settings.
- `frontend/src/pages/TaskDetail.jsx` — command-center layout.
- `frontend/src/components/PipelineGraph.jsx` — staged pipeline with QA gates.
- `frontend/src/components/AgentNode.jsx` — semantic status node.
- `frontend/src/components/AgentDetail.jsx` — product-facing summary first, technical details last.
- `frontend/src/components/QATimeline.jsx` — clearer correction story.
- `frontend/src/components/LlmLogs.jsx` — technical-trace framing and safer density.
- `frontend/src/pages/ReportView.jsx` — decision-first report center.

---

### Task 1: Shared Design System and Application Shell

**Files:**
- Create: `frontend/src/components/BrandMark.jsx`
- Create: `frontend/src/utils/presentation.js`
- Create: `frontend/test/presentation.test.js`
- Modify: `frontend/package.json`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/App.css`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Produces: `getTaskStatusMeta(status: string): { label: string, tone: string }`
- Produces: `mergeTasks(serverTasks: object[], recentTasks: object[]): object[]`
- Produces: `formatElapsed(startedAt?: string, finishedAt?: string): string`
- Produces: `getEventLabel(event: object): string`
- Produces: `<BrandMark compact?: boolean />`
- Consumes: existing React Router routes and Ant Design components.

- [ ] **Step 1: Add dependency-free failing utility tests**

Create `frontend/test/presentation.test.js`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  formatElapsed,
  getEventLabel,
  getTaskStatusMeta,
  mergeTasks,
} from '../src/utils/presentation.js';

test('maps task states to user-facing labels and tones', () => {
  assert.deepEqual(getTaskStatusMeta('running'), { label: '分析中', tone: 'running' });
  assert.deepEqual(getTaskStatusMeta('completed'), { label: '已交付', tone: 'success' });
  assert.deepEqual(getTaskStatusMeta('unknown'), { label: '等待中', tone: 'neutral' });
});

test('merges recent tasks with authoritative server fields', () => {
  const result = mergeTasks(
    [{ id: 'a', status: 'completed', product_description: '飞书' }],
    [{ id: 'a', status: 'pending' }, { id: 'b', status: 'pending' }],
  );
  assert.equal(result.length, 2);
  assert.equal(result.find(item => item.id === 'a').status, 'completed');
});

test('formats elapsed seconds and event labels', () => {
  assert.equal(formatElapsed('2026-08-29T10:00:00Z', '2026-08-29T10:01:05Z'), '1分05秒');
  assert.match(getEventLabel({ type: 'qa_check_failed', data: { target_agent: 'MarketAgent' } }), /MarketAgent/);
});
```

Add to `frontend/package.json`:

```json
"test": "node --test"
```

- [ ] **Step 2: Run tests and confirm the missing module failure**

Run: `cd frontend && npm.cmd test`

Expected: FAIL because `src/utils/presentation.js` does not exist.

- [ ] **Step 3: Implement the pure presentation utilities**

Create `frontend/src/utils/presentation.js` with exported constants/functions matching the tests. `getEventLabel` must cover at least `agent_started`, `agent_completed`, `qa_check_started`, `qa_check_failed`, `qa_check_passed`, `qa_retrying`, `task_completed`, and `task_failed`, using `event.agent`, `event.phase`, or `event.data.target_agent` when present.

- [ ] **Step 4: Replace the Vite template styling with global tokens and shell styles**

Implement CSS custom properties in `App.css`:

```css
:root {
  --sc-bg: #050b14;
  --sc-surface: #0b1728;
  --sc-surface-raised: #0f1f35;
  --sc-border: rgba(153, 177, 211, 0.16);
  --sc-text: #f4f8ff;
  --sc-muted: #91a3bd;
  --sc-cyan: #55d9ff;
  --sc-violet: #8c7cff;
  --sc-amber: #ffbd59;
  --sc-success: #62e6b1;
  --sc-danger: #ff6b72;
  --sc-paper: #f7f9fc;
  --sc-radius-lg: 20px;
  --sc-radius-md: 14px;
  --sc-content-width: 1440px;
}
```

Add shared `.app-shell`, `.app-header`, `.page-shell`, `.surface-card`, `.status-pill`, `.section-eyebrow`, `.primary-action`, `.secondary-action`, and focus-visible styles. Remove every Vite starter selector (`.counter`, `.hero .vite`, `#next-steps`, `#docs`, `#spacer`, `.ticks`).

In `index.css`, set the system font stack, dark page background, `box-sizing`, accessible selection/focus, and a `prefers-reduced-motion` block that disables non-essential animation.

- [ ] **Step 5: Build the application shell and brand mark**

Create `BrandMark.jsx` as semantic inline markup with CSS-drawn layered squares. Modify `App.jsx` to import `./App.css`, replace inline Ant Design header styles, and render:

```jsx
<Layout className="app-shell">
  <Header className="app-header">
    <BrandMark />
    <nav aria-label="主导航">
      <NavLink to="/">分析中心</NavLink>
    </nav>
    <span className="mode-pill">教学 / 比赛模式</span>
  </Header>
  <Content className="app-content">
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/tasks/:taskId" element={<TaskDetail />} />
      <Route path="/tasks/:taskId/report" element={<ReportView />} />
    </Routes>
  </Content>
</Layout>
```

- [ ] **Step 6: Verify tests and production compilation**

Run:

```powershell
cd frontend
npm.cmd ci
npm.cmd test
npm.cmd run lint
npm.cmd run build
```

Expected: tests PASS, lint exits 0, Vite production build exits 0.

- [ ] **Step 7: Commit the shared foundation**

```powershell
git add frontend/package.json frontend/src/App.jsx frontend/src/App.css frontend/src/index.css frontend/src/components/BrandMark.jsx frontend/src/utils/presentation.js frontend/test/presentation.test.js
git commit -m "feat: establish competition UI design system"
```

---

### Task 2: Narrative Dashboard and Safer Task Launcher

**Files:**
- Create: `frontend/src/components/dashboard/HomeHero.jsx`
- Modify: `frontend/src/pages/Dashboard.jsx`
- Modify: `frontend/src/components/TaskForm.jsx`
- Modify: `frontend/src/App.css`
- Modify: `frontend/test/presentation.test.js`

**Interfaces:**
- Consumes: `getTaskStatusMeta`, `mergeTasks`, and `formatElapsed` from `src/utils/presentation.js`.
- Produces: `<HomeHero onExampleSelect(name: string): void />` for the headline, proof points, and example products.
- Preserves: `TaskForm({ onSubmit, loading })` and the existing submit payload keys.

- [ ] **Step 1: Extend the dashboard utility test for ordering**

Append to `presentation.test.js`:

```js
test('keeps server task order and appends unmatched local tasks', () => {
  const result = mergeTasks(
    [{ id: 'new', status: 'running' }, { id: 'old', status: 'completed' }],
    [{ id: 'local', status: 'pending' }, { id: 'old', status: 'pending' }],
  );
  assert.deepEqual(result.map(item => item.id), ['new', 'old', 'local']);
});
```

- [ ] **Step 2: Run the targeted test and confirm current ordering fails**

Run: `cd frontend && npm.cmd test`

Expected: the new ordering assertion FAILS until `mergeTasks` is adjusted.

- [ ] **Step 3: Implement deterministic task merging**

Update `mergeTasks` so server order is preserved, recent-only tasks are appended, and server properties override local properties.

- [ ] **Step 4: Create the narrative hero**

`HomeHero.jsx` must render:

- Eyebrow: “可信竞品策略生成引擎”.
- Headline: “把竞品分析交给一支会互相质检的 Agent 团队”.
- Proof points: “7 个业务 Agent + QualityAgent”, “功能 / 定价 / 市场并行”, “结论保留引用链”.
- Example buttons for 飞书、Notion、小米汽车 calling `onExampleSelect`.

- [ ] **Step 5: Simplify TaskForm without changing its payload**

Keep product description and competitor count visible. Put `useRuleEngine` and `skipQa` inside an Ant Design `Collapse` labelled “高级设置”. Rename `skipQa` label to “关闭质量检查（不建议）” and add warning copy. Keep initial values `{ maxCompetitors: 5, skipQa: false, useRuleEngine: false }`.

Expose an optional `initialProduct` prop and call `form.setFieldValue('productDescription', initialProduct)` in an effect when an example is selected.

- [ ] **Step 6: Recompose Dashboard**

Preserve current task loading, polling, local storage, submit, delete, and navigation behavior. Replace inline layout with:

```jsx
const PROCESS_STEPS = [
  { title: '发现竞品', description: '界定真实竞争边界' },
  { title: '采集证据', description: '保留来源与查询链' },
  { title: '并行分析', description: '功能、定价、市场同步推进' },
  { title: 'QA 打回', description: '检查幻觉、完整性与覆盖率' },
  { title: '策略交付', description: '输出带引用的行动建议' },
];

<main className="page-shell dashboard-page">
  <section className="dashboard-hero-grid">
    <HomeHero onExampleSelect={setSelectedExample} />
    <TaskForm initialProduct={selectedExample} onSubmit={handleSubmit} loading={submitting} />
  </section>
  <section className="process-proof">
    {PROCESS_STEPS.map((step, index) => (
      <article className="process-step" key={step.title}>
        <span>{String(index + 1).padStart(2, '0')}</span>
        <strong>{step.title}</strong>
        <p>{step.description}</p>
      </article>
    ))}
  </section>
  <section className="recent-tasks" aria-labelledby="recent-task-heading">
    <header className="section-heading">
      <div><span className="section-eyebrow">Recent missions</span><h2 id="recent-task-heading">最近分析</h2></div>
      <span>{tasks.length} 个任务</span>
    </header>
    <List
      loading={loading}
      dataSource={tasks}
      locale={{ emptyText: '还没有分析任务，从上方启动第一支 Agent 团队' }}
      renderItem={task => {
        const status = getTaskStatusMeta(task.status);
        return <TaskListItem task={task} status={status} onOpen={() => navigate(`/tasks/${task.id}`)} onDelete={handleDelete} />;
      }}
    />
  </section>
</main>
```

`TaskListItem` remains a local component inside `Dashboard.jsx`; it must not introduce a new API or state store:

```jsx
function TaskListItem({ task, status, onOpen, onDelete }) {
  return (
    <List.Item className="task-list-item" onClick={onOpen}>
      <div className="task-list-main">
        <span className={`status-pill status-${status.tone}`}>{status.label}</span>
        <strong>{task.product_description}</strong>
        <span>{task.max_competitors || 5} 个竞品</span>
        <span>{formatElapsed(task.started_at, task.finished_at)}</span>
      </div>
      <div className="task-list-actions">
        <Button type="primary" onClick={event => { event.stopPropagation(); onOpen(); }}>
          {task.status === 'completed' ? '查看结果' : '进入工作台'}
        </Button>
        <Popconfirm title="删除任务" description="删除后将无法从任务列表恢复" onConfirm={() => onDelete(task.id)}>
          <Button danger type="text" onClick={event => event.stopPropagation()}>删除</Button>
        </Popconfirm>
      </div>
    </List.Item>
  );
}
```

Task rows must show product, semantic status pill, competitor count, current/duration metadata, a primary “进入工作台/查看报告” affordance, and a visually secondary delete action.

- [ ] **Step 7: Add responsive dashboard styles**

At `<768px`, stack hero and launcher, make proof steps a vertical timeline, render each task as a card, and keep controls at least 44px high. At `768–1199px`, use a single-column hero and two-column task metadata.

- [ ] **Step 8: Verify dashboard behavior**

Run:

```powershell
cd frontend
npm.cmd test
npm.cmd run lint
npm.cmd run build
```

Expected: PASS. Confirm the call remains `submitTask(values.productDescription, values.maxCompetitors, values.skipQa, values.useRuleEngine)`.

- [ ] **Step 9: Commit the dashboard**

```powershell
git add frontend/src/pages/Dashboard.jsx frontend/src/components/TaskForm.jsx frontend/src/components/dashboard/HomeHero.jsx frontend/src/App.css frontend/src/utils/presentation.js frontend/test/presentation.test.js
git commit -m "feat: turn dashboard into narrative analysis center"
```

---

### Task 3: Explicit QA Gates and Tested Quality Aggregation

**Files:**
- Create: `frontend/src/components/QAGate.jsx`
- Create: `frontend/src/utils/quality.js`
- Create: `frontend/test/quality.test.js`
- Modify: `frontend/src/components/PipelineGraph.jsx`
- Modify: `frontend/src/components/AgentNode.jsx`
- Modify: `frontend/src/App.css`

**Interfaces:**
- Produces: `aggregateQuality(checks: object[]): QualitySummary`.
- Produces: `getGateState(targetKeys: string[], qaSummaries: object): GateState`.
- Produces: `<QAGate label targets qaSummaries />`.
- Consumes: existing `nodeStates`, `qaSummaries`, `timings`, and `onNodeClick` PipelineGraph props.

Define `QualitySummary` as:

```js
{
  totalChecks: number,
  retryCount: number,
  degradedCount: number,
  issueCount: number,
  accuracyRate: number | null,
  coverageRate: number | null,
  correctionRate: number | null,
  latestChecks: object[],
}
```

- [ ] **Step 1: Add failing quality tests**

Create `frontend/test/quality.test.js`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { aggregateQuality, getGateState } from '../src/utils/quality.js';

test('uses the latest completed check per phase for weighted metrics', () => {
  const summary = aggregateQuality([
    { phase: 'product', passed: false, total_fields: 5, accuracy_rate: 40, coverage_rate: 60, correction_count: 2, issues: [{}] },
    { phase: 'product', passed: true, total_fields: 5, accuracy_rate: 90, coverage_rate: 80, correction_count: 1, issues: [] },
    { phase: 'market', passed: true, total_fields: 10, accuracy_rate: 80, coverage_rate: 70, correction_count: 1, issues: [] },
  ]);
  assert.equal(summary.totalChecks, 3);
  assert.equal(summary.retryCount, 1);
  assert.equal(summary.accuracyRate, 83.3);
  assert.equal(summary.coverageRate, 73.3);
  assert.equal(summary.correctionRate, 13.3);
});

test('prioritizes running, failed, degraded, then passed gate states', () => {
  assert.equal(getGateState(['product_analysis'], { product_analysis: { status: 'running' } }).status, 'running');
  assert.equal(getGateState(['product_analysis'], { product_analysis: { status: 'failed' } }).status, 'failed');
  assert.equal(getGateState(['product_analysis'], { product_analysis: { status: 'degraded' } }).status, 'degraded');
  assert.equal(getGateState(['product_analysis'], { product_analysis: { status: 'passed' } }).status, 'passed');
});
```

- [ ] **Step 2: Run tests and confirm missing module failure**

Run: `cd frontend && npm.cmd test`

Expected: FAIL because `src/utils/quality.js` does not exist.

- [ ] **Step 3: Implement quality aggregation**

Create `quality.js`. Ignore `running` checks in metric calculations, count each non-passed completed check as a retry, retain the latest completed check per `phase`, weight accuracy/coverage by `total_fields`, round rates to one decimal, and return `null` when no valid fields exist.

`getGateState` must aggregate one or more target node summaries and return `{ status, label, score, retryCount, targets }`, with priority `running > failed > degraded > passed > waiting`.

- [ ] **Step 4: Model the truthful pipeline stages**

Replace the existing stage list with:

```js
const PIPELINE = [
  { type: 'agent', key: 'discovery', label: '竞品发现', agent: 'DiscoveryAgent' },
  { type: 'agent', key: 'collection', label: '证据采集', agent: 'CollectionAgent' },
  { type: 'qa', key: 'qa_collection', label: '采集质量门', targets: ['collection'] },
  { type: 'agent', key: 'dimension', label: '维度配置', agent: 'DimensionAgent' },
  { type: 'parallel', key: 'parallel_analysis', nodes: [
    { key: 'product_analysis', label: '功能分析', agent: 'ProductAgent' },
    { key: 'pricing_analysis', label: '定价分析', agent: 'PricingAgent' },
    { key: 'market_analysis', label: '市场分析', agent: 'MarketAgent' },
  ] },
  { type: 'qa', key: 'qa_analysis', label: '三维分析质量门', targets: ['product_analysis', 'pricing_analysis', 'market_analysis'] },
  { type: 'agent', key: 'strategy', label: '策略综合', agent: 'StrategyAgent' },
  { type: 'qa', key: 'qa_strategy', label: '交付质量门', targets: ['strategy'] },
];
```

- [ ] **Step 5: Implement AgentNode and QAGate visual states**

Both components must render an icon, text label, machine-readable Agent name, status label, and optional timing/score. Add `aria-label`, keyboard activation for clickable nodes, and `data-status` attributes. Running nodes pulse; retrying nodes show “QA 打回后重做”; degraded gates show “降级通过”.

When a gate is failed, render a visible correction note naming its targets; do not animate indefinitely.

- [ ] **Step 6: Verify logic and build**

Run:

```powershell
cd frontend
npm.cmd test
npm.cmd run lint
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 7: Commit the pipeline**

```powershell
git add frontend/src/components/PipelineGraph.jsx frontend/src/components/AgentNode.jsx frontend/src/components/QAGate.jsx frontend/src/utils/quality.js frontend/test/quality.test.js frontend/src/App.css
git commit -m "feat: make quality gates explicit in agent pipeline"
```

---

### Task 4: Real-Time Agent Workbench and Technical Trace Hierarchy

**Files:**
- Create: `frontend/src/components/workbench/LiveActivityRail.jsx`
- Create: `frontend/src/components/workbench/QualityCockpit.jsx`
- Modify: `frontend/src/pages/TaskDetail.jsx`
- Modify: `frontend/src/components/AgentDetail.jsx`
- Modify: `frontend/src/components/QATimeline.jsx`
- Modify: `frontend/src/components/LlmLogs.jsx`
- Modify: `frontend/src/App.css`

**Interfaces:**
- Consumes: `aggregateQuality` and `getEventLabel`.
- Produces: `<LiveActivityRail events currentMessage connected />`.
- Produces: `<QualityCockpit checks />`.
- Preserves: current artifact refresh, WebSocket event handling, report navigation, and AgentDetail props.

- [ ] **Step 1: Implement LiveActivityRail as a pure presentation component**

Render the connection state, current message, and at most the six most recent non-ping events. Each item shows a semantic icon, `getEventLabel(event)`, and progress when supplied. Empty state: “等待 Agent 团队接管任务”. Disconnected state: “实时连接中断，正在自动重连；已保存的任务状态仍可查看”.

- [ ] **Step 2: Implement QualityCockpit from aggregateQuality**

Render accuracy, coverage, correction rate, total QA checks, retry count, and degraded count. For `null` metrics render “待质检” rather than `0%`. Add short explanatory labels so a judge understands whether high or low is desirable.

- [ ] **Step 3: Recompose TaskDetail without changing data effects**

Keep every existing `useEffect`, artifact cache update, `refreshQa`, `loadTaskInfo`, node click, and report navigation behavior. Replace the render tree with:

```jsx
<main className="page-shell workbench-page">
  <section className="mission-header">
    <button className="secondary-action" onClick={() => navigate('/')}>返回分析中心</button>
    <div className="mission-title-row">
      <div>
        <span className="section-eyebrow">Live agent mission</span>
        <h1>{taskInfo?.product_description || taskId}</h1>
        <p>{currentMessage || '等待 Agent 团队更新进度'}</p>
      </div>
      <div className="mission-actions">
        <span className={`status-pill status-${taskStatus}`}>{statusText}</span>
        <span className={`status-pill ${connected ? 'status-connected' : 'status-disconnected'}`}>
          {connected ? '实时连接正常' : '正在重新连接'}
        </span>
      </div>
    </div>
    <Progress percent={Math.round(progress * 100)} status={taskStatus === 'failed' ? 'exception' : undefined} />
  </section>
  <section className="workbench-grid">
    <div className="workflow-deck">
      <PipelineGraph nodeStates={graphNodeStates} qaSummaries={graphQaSummaries} onNodeClick={handleNodeClick} />
    </div>
    <LiveActivityRail events={events} currentMessage={currentMessage} connected={connected} />
  </section>
  <section className="quality-grid">
    <QualityCockpit checks={timelineQaResults} />
    <QATimeline results={timelineQaResults} />
  </section>
  <section className="technical-trace">
    <LlmLogs taskId={taskId} refreshKey={llmLogsKey} />
  </section>
  <AgentDetail
    taskId={taskId}
    phase={selectedPhase}
    open={detailOpen}
    onClose={() => setDetailOpen(false)}
    agentLabel={selectedPhase ? AGENT_PHASE_MAP[selectedPhase]?.label : ''}
    nodeStatus={selectedPhase ? graphNodeStates[selectedPhase] : undefined}
    artifactData={selectedPhase ? artifactCache[selectedPhase] : undefined}
    qaArtifactData={artifactCache.qa}
    onArtifactLoaded={cacheArtifact}
  />
</main>
```

The mission header must include product, semantic status, WebSocket text status, total progress, current Agent, rule-engine/QA mode badges, and the report button when complete.

- [ ] **Step 4: Improve the QA correction story**

In `QATimeline`, group entries by phase/target visually, show attempt, score, issue count, first two issues, feedback, and result. Use “发现问题 → 已反馈给 X → 第 N 轮修正” copy for failures. Keep degraded pass distinct.

- [ ] **Step 5: Reorder AgentDetail content**

Tabs/order:

1. “阶段结论” — formatted artifact summary and stage status.
2. “质量反馈” — relevant QA checks and retries.
3. “引用与原始数据” — structured artifact JSON.
4. “技术追溯” — raw execution details when available.

Do not remove existing artifact fetching or QA filtering.

- [ ] **Step 6: Reframe LlmLogs as advanced technical trace**

Keep all data columns and expandable details, but add a short privacy/engineering explanation and reduce the default table to Agent, type, status, tokens, duration, model, summary. Keep System Prompt/User Message/LLM Output collapsed. Wrap the component in a native/Ant Design collapse closed by default on the workbench.

- [ ] **Step 7: Add responsive and motion behavior**

Desktop uses a `minmax(0, 2fr) minmax(300px, 1fr)` workbench grid. Tablet stacks the activity rail under the pipeline. Mobile uses vertical pipeline stages and two-column metric cards. Add reduced-motion fallbacks.

- [ ] **Step 8: Verify workbench compilation and existing interfaces**

Run:

```powershell
cd frontend
npm.cmd test
npm.cmd run lint
npm.cmd run build
```

Expected: PASS. Confirm `TaskDetail` still calls `getTask`, `getArtifact`, `useWebSocket`, and `useTask`; confirm `AgentDetail` still receives the existing prop names.

- [ ] **Step 9: Commit the workbench**

```powershell
git add frontend/src/pages/TaskDetail.jsx frontend/src/components/workbench/LiveActivityRail.jsx frontend/src/components/workbench/QualityCockpit.jsx frontend/src/components/AgentDetail.jsx frontend/src/components/QATimeline.jsx frontend/src/components/LlmLogs.jsx frontend/src/App.css
git commit -m "feat: build real-time agent quality workbench"
```

---

### Task 5: Decision-First Report Center

**Files:**
- Create: `frontend/src/components/report/ReportOverview.jsx`
- Create: `frontend/src/utils/report.js`
- Create: `frontend/test/report.test.js`
- Modify: `frontend/src/pages/ReportView.jsx`
- Modify: `frontend/src/App.css`

**Interfaces:**
- Produces: `buildReportOverview(report: object): ReportOverviewData`.
- Produces: `<ReportOverview report />`.
- Preserves: `getReport(taskId)`, HTML iframe URL, JSON toggle/download behavior.

Define `ReportOverviewData` as:

```js
{
  productName: string,
  competitorCount: number,
  positioning: string,
  actions: object[],
  citationCount: number,
  qaCheckCount: number,
  qaStatus: 'passed' | 'degraded' | 'failed' | 'unknown',
}
```

- [ ] **Step 1: Add failing report derivation tests**

Create `frontend/test/report.test.js`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildReportOverview } from '../src/utils/report.js';

test('derives prioritized actions and trust evidence from serialized report data', () => {
  const result = buildReportOverview({
    product_name: '飞书',
    competitor_count: 5,
    overall_positioning: '以协作深度建立差异化',
    action_plan: [
      { priority: 'P2', action: '长期生态建设' },
      { priority: 'P0', action: '强化核心协作能力' },
      { priority: 'P1', action: '优化团队定价' },
    ],
    citation_index: { citations: { c1: {}, c2: {} } },
    qa_timeline: { checks: [{ passed: true }, { passed: true, degraded: true }] },
  });
  assert.equal(result.productName, '飞书');
  assert.deepEqual(result.actions.map(item => item.priority), ['P0', 'P1', 'P2']);
  assert.equal(result.citationCount, 2);
  assert.equal(result.qaStatus, 'degraded');
});

test('uses honest unknown states for incomplete reports', () => {
  const result = buildReportOverview({ product_name: '未完成任务' });
  assert.equal(result.citationCount, 0);
  assert.equal(result.qaStatus, 'unknown');
  assert.deepEqual(result.actions, []);
});
```

- [ ] **Step 2: Run tests and confirm missing module failure**

Run: `cd frontend && npm.cmd test`

Expected: FAIL because `src/utils/report.js` does not exist.

- [ ] **Step 3: Implement robust report overview derivation**

Support `citation_index.citations` as either an object or array. Sort actions using `P0`, `P1`, `P2`, `P3`, then preserve input order within a priority. Use at most three actions in the overview. Reduce QA checks to the latest completed check per `phase`, then determine status with priority `failed > degraded > passed > unknown`; a corrected historical failure must not make the final report appear failed.

- [ ] **Step 4: Create ReportOverview**

Render positioning, up to three action cards with priority/timeline/impact, and trust cards for competitor count, citation count, QA check count, and QA state. For missing positioning or actions use explanatory empty copy, not generated placeholders.

- [ ] **Step 5: Recompose ReportView**

Keep loading/error behavior and JSON download. Add view state with values `overview`, `full`, and `json`. Default to `overview`. Render `ReportOverview` first; include a prominent “阅读完整分析” action that switches to `full`. Full view embeds the existing `/api/tasks/${taskId}/report.html` iframe, shows a loading skeleton until `onLoad`, and always provides an anchor with `target="_blank"` and `rel="noreferrer"` as the fallback. JSON remains a formatted, scrollable technical view.

- [ ] **Step 6: Add report paper styling and mobile behavior**

Use the light `--sc-paper` surface inside the report content while retaining the dark application shell. At mobile widths, action cards stack and view controls become horizontally scrollable or wrap without truncating labels.

- [ ] **Step 7: Verify report logic and build**

Run:

```powershell
cd frontend
npm.cmd test
npm.cmd run lint
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 8: Commit the report center**

```powershell
git add frontend/src/pages/ReportView.jsx frontend/src/components/report/ReportOverview.jsx frontend/src/utils/report.js frontend/test/report.test.js frontend/src/App.css
git commit -m "feat: add decision-first strategy report center"
```

---

### Task 6: Integrated Responsive QA and Competition Acceptance

**Files:**
- Modify as findings require: `frontend/src/App.css`
- Modify as findings require: frontend page/component files already listed above.
- No backend file changes unless an existing frontend contract is proven unusable.

**Interfaces:**
- Consumes: complete UI from Tasks 1–5.
- Produces: verified responsive build with no known P0/P1 presentation regression.

- [ ] **Step 1: Run the complete targeted automated verification**

```powershell
cd frontend
npm.cmd test
npm.cmd run lint
npm.cmd run build
```

Expected: all commands exit 0.

- [ ] **Step 2: Start the built frontend for visual inspection**

Run `npm.cmd run preview -- --host 127.0.0.1` from `frontend`. Use a headless local browser to capture the dashboard at 1440×1000, 1024×900, and 390×844. Inspect brand hierarchy, task controls, focus visibility, overflow, and reduced-motion behavior.

- [ ] **Step 3: Perform a zero-cost integration smoke only if task/detail states need validation**

Use the existing Conda environment and rule engine; do not configure or call Doubao:

```powershell
& 'D:\Elmo\anaconda3\Scripts\conda.exe' run -n smartcomp-engine-dev python -m uvicorn server.main:app --port 8000
```

Submit at most one task with `use_rule_engine=true`, `max_competitors=3`, and QA enabled. Stop if the rule path requests network/API credentials. Verify task creation, live workbench, QA presentation, completion, report overview, full report, and JSON download.

- [ ] **Step 4: Fix only directly observed presentation defects**

Apply scoped CSS/component changes for overflow, contrast, missing labels, or broken responsive layout. Do not add a demo mode, account system, workflow editor, chart library, or new backend endpoint.

- [ ] **Step 5: Re-run verification after fixes**

Run:

```powershell
cd frontend
npm.cmd test
npm.cmd run lint
npm.cmd run build
```

Expected: all commands exit 0.

- [ ] **Step 6: Inspect git scope**

Run:

```powershell
git status --short
git diff --stat final_work...HEAD
git diff --check final_work...HEAD
```

Expected: only the design/plan and intended frontend files changed; `git diff --check` exits 0.

- [ ] **Step 7: Commit final polish**

```powershell
git add frontend
git commit -m "fix: polish responsive competition experience"
```

- [ ] **Step 8: Record the validation boundary in the handoff**

State exactly which of unit tests, lint, production build, responsive screenshots, and rule-engine smoke ran. Explicitly state that no real LLM/network analysis and no unrelated full Python suite ran unless they were separately executed.
