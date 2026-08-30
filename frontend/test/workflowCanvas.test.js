import test from 'node:test';
import assert from 'node:assert/strict';

const workflowCanvas = await import('../src/utils/workflowCanvas.js').catch(() => ({}));

test('the canvas exposes the approved four-stage forward DAG', () => {
  assert.deepEqual(
    workflowCanvas.WORKFLOW_STAGES?.map(stage => stage.label),
    ['找到对手与证据', '决定怎么比较', '三路并行分析', '生成策略报告'],
  );

  assert.deepEqual(
    workflowCanvas.WORKFLOW_EDGES?.map(edge => `${edge.from}->${edge.to}`),
    [
      'input->discovery',
      'discovery->collection',
      'collection->qa_collection',
      'qa_collection->dimension',
      'dimension->product_analysis',
      'dimension->pricing_analysis',
      'dimension->market_analysis',
      'product_analysis->qa_analysis',
      'pricing_analysis->qa_analysis',
      'market_analysis->qa_analysis',
      'qa_analysis->strategy',
      'strategy->qa_strategy',
      'qa_strategy->report',
    ],
  );
});

test('the current workflow summary explains the active business stage', () => {
  assert.equal(typeof workflowCanvas.getWorkflowFocus, 'function');

  assert.deepEqual(
    workflowCanvas.getWorkflowFocus({
      nodeStates: {
        discovery: 'completed',
        collection: 'completed',
        dimension: 'completed',
        product_analysis: 'running',
        pricing_analysis: 'running',
        market_analysis: 'running',
      },
      qaSummaries: { collection: { status: 'passed' } },
      taskStatus: 'running',
      qaDisabled: false,
    }),
    {
      stageNumber: 3,
      progressLabel: '第 3 / 4 步',
      title: '正在并行比较产品、定价与市场',
      outcome: '完成后将得到三维竞争分析',
    },
  );
});

test('a failed task keeps the focus on the stage that actually failed', () => {
  assert.deepEqual(
    workflowCanvas.getWorkflowFocus({
      nodeStates: {
        discovery: 'completed',
        collection: 'completed',
        dimension: 'completed',
        product_analysis: 'completed',
        pricing_analysis: 'completed',
        market_analysis: 'completed',
        strategy: 'failed',
      },
      qaSummaries: {
        collection: { status: 'passed' },
        product_analysis: { status: 'passed' },
        pricing_analysis: { status: 'passed' },
        market_analysis: { status: 'passed' },
      },
      taskStatus: 'failed',
      qaDisabled: false,
    }),
    {
      stageNumber: 4,
      progressLabel: '第 4 / 4 步',
      title: '分析在“生成策略报告”阶段中断',
      outcome: '已定位失败节点，可查看详情后重新处理',
    },
  );
});

test('a terminal failure outranks a stale running event from an earlier stage', () => {
  const focus = workflowCanvas.getWorkflowFocus({
    nodeStates: {
      discovery: 'running',
      strategy: 'failed',
    },
    taskStatus: 'failed',
    qaDisabled: true,
  });

  assert.equal(focus.stageNumber, 4);
  assert.equal(focus.title, '分析在“生成策略报告”阶段中断');
});

test('a degraded checkpoint keeps the focus on its real risk stage', () => {
  const focus = workflowCanvas.getWorkflowFocus({
    nodeStates: {
      discovery: 'completed',
      collection: 'completed',
      dimension: 'completed',
      product_analysis: 'completed',
      pricing_analysis: 'completed',
      market_analysis: 'completed',
    },
    qaSummaries: {
      collection: { status: 'passed' },
      product_analysis: { status: 'degraded' },
      pricing_analysis: { status: 'passed' },
      market_analysis: { status: 'passed' },
    },
    taskStatus: 'degraded',
    qaDisabled: false,
  });

  assert.equal(focus.stageNumber, 3);
  assert.equal(focus.title, '“三路并行分析”存在质量风险');
});

test('a terminal quality risk outranks a stale running event', () => {
  const focus = workflowCanvas.getWorkflowFocus({
    nodeStates: {
      discovery: 'running',
      product_analysis: 'completed',
      pricing_analysis: 'completed',
      market_analysis: 'completed',
    },
    qaSummaries: {
      product_analysis: { status: 'degraded' },
      pricing_analysis: { status: 'passed' },
      market_analysis: { status: 'passed' },
    },
    taskStatus: 'degraded',
    qaDisabled: false,
  });

  assert.equal(focus.stageNumber, 3);
  assert.equal(focus.title, '“三路并行分析”存在质量风险');
});

test('quality gates stay visibly disabled without blocking the forward DAG', () => {
  assert.equal(typeof workflowCanvas.buildWorkflowCanvasModel, 'function');

  const model = workflowCanvas.buildWorkflowCanvasModel({
    nodeStates: { discovery: 'completed', collection: 'completed' },
    qaSummaries: {},
    taskStatus: 'running',
    qaDisabled: true,
  });

  assert.deepEqual(
    model.nodes
      .filter(node => node.kind === 'qa')
      .map(node => node.status),
    ['disabled', 'disabled', 'disabled'],
  );
  assert.equal(model.nodes.find(node => node.id === 'dimension').status, 'running');
  assert.equal(model.nodes.find(node => node.id === 'strategy').status, 'waiting');
  assert.equal(model.nodes.find(node => node.id === 'report').status, 'waiting');
  assert.equal(model.edges.find(edge => edge.from === 'qa_collection').status, 'running');
  assert.equal(model.edges.find(edge => edge.from === 'qa_analysis').status, 'waiting');
  assert.equal(model.edges.find(edge => edge.from === 'qa_strategy').status, 'waiting');
});

test('disabled quality gates never advance past unfinished upstream agents', () => {
  const nodeStates = Object.fromEntries(
    workflowCanvas.WORKFLOW_NODES
      .filter(node => node.kind === 'agent')
      .map(node => [node.phase, 'waiting']),
  );
  const model = workflowCanvas.buildWorkflowCanvasModel({
    nodeStates,
    taskStatus: 'running',
    qaDisabled: true,
  });

  assert.equal(model.nodes.find(node => node.id === 'strategy').status, 'waiting');
  assert.equal(model.nodes.find(node => node.id === 'report').status, 'waiting');
  assert.equal(model.edges.find(edge => edge.id === 'analysis-strategy').status, 'waiting');
  assert.equal(model.edges.find(edge => edge.id === 'qa-report').status, 'waiting');
  assert.equal(workflowCanvas.getWorkflowFocus({
    nodeStates,
    taskStatus: 'running',
    qaDisabled: true,
  }).stageNumber, 1);
});

test('the canvas highlights branch and merge edges from their real node states', () => {
  const model = workflowCanvas.buildWorkflowCanvasModel({
    nodeStates: {
      discovery: 'completed',
      collection: 'completed',
      dimension: 'completed',
      product_analysis: 'completed',
      pricing_analysis: 'running',
      market_analysis: 'waiting',
    },
    qaSummaries: { collection: { status: 'passed' } },
    taskStatus: 'running',
    qaDisabled: false,
  });

  assert.equal(
    model.edges.find(edge => edge.from === 'dimension' && edge.to === 'product_analysis').status,
    'completed',
  );
  assert.equal(
    model.edges.find(edge => edge.from === 'dimension' && edge.to === 'pricing_analysis').status,
    'running',
  );
  assert.equal(
    model.edges.find(edge => edge.from === 'dimension' && edge.to === 'market_analysis').status,
    'waiting',
  );
  assert.equal(
    model.edges.find(edge => edge.from === 'product_analysis' && edge.to === 'qa_analysis').status,
    'completed',
  );
});

test('parallel branch routes use separate ports with a readable horizontal gutter', () => {
  assert.equal(typeof workflowCanvas.getWorkflowEdgeGeometry, 'function');
  const nodesById = Object.fromEntries(
    workflowCanvas.WORKFLOW_NODES.map(node => [node.id, node]),
  );
  const routes = ['dimension-product', 'dimension-pricing', 'dimension-market']
    .map(id => workflowCanvas.WORKFLOW_EDGES.find(edge => edge.id === id))
    .map(edge => workflowCanvas.getWorkflowEdgeGeometry(edge, nodesById));

  assert.deepEqual(routes.map(route => route.source.y), [316, 340, 364]);
  assert.equal(new Set(routes.map(route => route.source.y)).size, 3);
  routes.forEach((route) => {
    assert.ok(route.target.x - route.source.x >= 72);
    assert.ok(route.source.x < route.sourceControl.x);
    assert.ok(route.sourceControl.x < route.targetControl.x);
    assert.ok(route.targetControl.x < route.target.x);
  });
});

test('parallel merge routes enter the quality gate through separate ports', () => {
  assert.equal(typeof workflowCanvas.getWorkflowEdgeGeometry, 'function');
  const nodesById = Object.fromEntries(
    workflowCanvas.WORKFLOW_NODES.map(node => [node.id, node]),
  );
  const routes = ['product-qa', 'pricing-qa', 'market-qa']
    .map(id => workflowCanvas.WORKFLOW_EDGES.find(edge => edge.id === id))
    .map(edge => workflowCanvas.getWorkflowEdgeGeometry(edge, nodesById));

  assert.deepEqual(routes.map(route => route.target.y), [325, 348, 371]);
  assert.equal(new Set(routes.map(route => route.target.y)).size, 3);
  routes.forEach((route) => {
    assert.ok(route.target.x - route.source.x >= 72);
    assert.ok(route.source.x < route.sourceControl.x);
    assert.ok(route.sourceControl.x < route.targetControl.x);
    assert.ok(route.targetControl.x < route.target.x);
  });
});

test('the widened canvas keeps the report node clear of the right edge', () => {
  const report = workflowCanvas.WORKFLOW_NODES.find(node => node.id === 'report');
  const reportRight = report.x + 124;
  assert.ok(workflowCanvas.WORKFLOW_CANVAS_SIZE.width - reportRight >= 96);
});

test('canvas zoom is clamped to the supported readable range', () => {
  assert.equal(typeof workflowCanvas.clampCanvasZoom, 'function');
  assert.equal(workflowCanvas.clampCanvasZoom(0.2), 0.6);
  assert.equal(workflowCanvas.clampCanvasZoom(0.85), 0.85);
  assert.equal(workflowCanvas.clampCanvasZoom(1.8), 1.4);
});

test('node actions expose artifacts only for business agents and the finished report', () => {
  assert.equal(typeof workflowCanvas.getWorkflowNodeAction, 'function');
  const nodes = Object.fromEntries(workflowCanvas.WORKFLOW_NODES.map(node => [node.id, node]));

  assert.deepEqual(workflowCanvas.getWorkflowNodeAction(nodes.collection, 'running'), {
    kind: 'artifact',
    phase: 'collection',
    label: '查看阶段产物',
  });
  assert.equal(workflowCanvas.getWorkflowNodeAction(nodes.qa_collection, 'running'), null);
  assert.equal(workflowCanvas.getWorkflowNodeAction(nodes.report, 'running'), null);
  assert.deepEqual(workflowCanvas.getWorkflowNodeAction(nodes.report, 'completed'), {
    kind: 'report',
    label: '查看策略报告',
  });
});

test('stage bounds map canvas coordinates to positioned HTML styles', () => {
  assert.equal(typeof workflowCanvas.getStageZoneStyle, 'function');
  assert.deepEqual(workflowCanvas.getStageZoneStyle({
    bounds: { x: 11, y: 22, width: 333, height: 444 },
  }), {
    left: 11,
    top: 22,
    width: 333,
    height: 444,
  });
});

test('a live completion transition resets the inspector to the report only once', () => {
  assert.equal(
    workflowCanvas.shouldResetWorkflowSelection('running', 'completed'),
    true,
  );
  assert.equal(
    workflowCanvas.shouldResetWorkflowSelection('completed', 'completed'),
    false,
  );
  assert.equal(
    workflowCanvas.shouldResetWorkflowSelection('running', 'failed'),
    false,
  );
});
