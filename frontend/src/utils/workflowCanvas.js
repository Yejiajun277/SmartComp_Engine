import { getGateState } from './quality.js';

export const WORKFLOW_CANVAS_SIZE = Object.freeze({ width: 2050, height: 680 });
export const WORKFLOW_DEFAULT_ZOOM = 0.84;
export const WORKFLOW_MOBILE_DEFAULT_ZOOM = 0.72;
export const WORKFLOW_MOBILE_BREAKPOINT = 767;

export const WORKFLOW_NODE_SIZES = Object.freeze({
  agent: Object.freeze({ width: 145, height: 96 }),
  input: Object.freeze({ width: 124, height: 96 }),
  output: Object.freeze({ width: 124, height: 96 }),
  qa: Object.freeze({ width: 96, height: 92 }),
});

export const WORKFLOW_STAGES = Object.freeze([
  {
    id: 'evidence',
    number: 1,
    label: '找到对手与证据',
    shortLabel: '发现与取证',
    outcome: '竞品清单与可信证据',
    bounds: { x: 20, y: 56, width: 650, height: 568 },
    nodeIds: ['input', 'discovery', 'collection', 'qa_collection'],
  },
  {
    id: 'framework',
    number: 2,
    label: '决定怎么比较',
    shortLabel: '分析框架',
    outcome: '本次任务专属比较维度',
    bounds: { x: 680, y: 56, width: 235, height: 568 },
    nodeIds: ['dimension'],
  },
  {
    id: 'analysis',
    number: 3,
    label: '三路并行分析',
    shortLabel: '并行研判',
    outcome: '产品、定价与市场三维结论',
    bounds: { x: 925, y: 56, width: 455, height: 568 },
    nodeIds: ['product_analysis', 'pricing_analysis', 'market_analysis', 'qa_analysis'],
  },
  {
    id: 'strategy',
    number: 4,
    label: '生成策略报告',
    shortLabel: '策略交付',
    outcome: '可执行的竞争策略报告',
    bounds: { x: 1390, y: 56, width: 640, height: 568 },
    nodeIds: ['strategy', 'qa_strategy', 'report'],
  },
]);

export const WORKFLOW_NODES = Object.freeze([
  {
    id: 'input', kind: 'input', stage: 'evidence', label: '输入产品',
    description: '确认本次分析对象与范围', output: '任务输入', x: 45, y: 292,
  },
  {
    id: 'discovery', kind: 'agent', stage: 'evidence', phase: 'discovery',
    agent: 'DiscoveryAgent', label: '竞品发现', description: '识别真正需要比较的竞争对手',
    output: '竞品清单', x: 205, y: 292,
  },
  {
    id: 'collection', kind: 'agent', stage: 'evidence', phase: 'collection',
    agent: 'CollectionAgent', label: '证据采集', description: '补全产品、价格、市场信息与引用',
    output: '证据集', x: 370, y: 292,
  },
  {
    id: 'qa_collection', kind: 'qa', stage: 'evidence', targets: ['collection'],
    label: '证据质检', description: '检查证据完整性与引用可信度',
    output: '通过后进入分析框架', x: 550, y: 302,
  },
  {
    id: 'dimension', kind: 'agent', stage: 'framework', phase: 'dimension',
    agent: 'DimensionAgent', label: '定义分析维度', description: '根据产品与证据确定比较框架',
    output: '分析框架', x: 700, y: 292,
  },
  {
    id: 'product_analysis', kind: 'agent', stage: 'analysis', phase: 'product_analysis',
    agent: 'ProductAgent', label: '产品分析', description: '比较功能、体验与差异化',
    output: '产品结论', x: 930, y: 132,
  },
  {
    id: 'pricing_analysis', kind: 'agent', stage: 'analysis', phase: 'pricing_analysis',
    agent: 'PricingAgent', label: '定价分析', description: '比较价格、套餐与商业模式',
    output: '定价结论', x: 930, y: 292,
  },
  {
    id: 'market_analysis', kind: 'agent', stage: 'analysis', phase: 'market_analysis',
    agent: 'MarketAgent', label: '市场分析', description: '比较用户、定位与竞争态势',
    output: '市场结论', x: 930, y: 452,
  },
  {
    id: 'qa_analysis', kind: 'qa', stage: 'analysis',
    targets: ['product_analysis', 'pricing_analysis', 'market_analysis'],
    label: '分析质检', description: '逐路检查三维分析，有问题只打回对应 Agent',
    output: '可信三维分析', x: 1210, y: 302,
  },
  {
    id: 'strategy', kind: 'agent', stage: 'strategy', phase: 'strategy',
    agent: 'StrategyAgent', label: '策略综合', description: '把证据与三维结论转化为行动建议',
    output: '策略建议', x: 1420, y: 292,
  },
  {
    id: 'qa_strategy', kind: 'qa', stage: 'strategy', targets: ['strategy'],
    label: '报告质检', description: '核对策略与证据、分析是否一致',
    output: '可交付报告', x: 1650, y: 302,
  },
  {
    id: 'report', kind: 'output', stage: 'strategy', label: '策略报告',
    description: '查看最终结论、行动优先级与引用', output: 'HTML / JSON 报告', x: 1830, y: 292,
  },
]);

export const WORKFLOW_EDGES = Object.freeze([
  { id: 'input-discovery', from: 'input', to: 'discovery', label: '开始分析' },
  { id: 'discovery-collection', from: 'discovery', to: 'collection', label: '补全证据' },
  { id: 'collection-qa', from: 'collection', to: 'qa_collection', label: '提交检查' },
  { id: 'qa-dimension', from: 'qa_collection', to: 'dimension', label: '通过后继续' },
  { id: 'dimension-product', from: 'dimension', to: 'product_analysis', kind: 'branch' },
  { id: 'dimension-pricing', from: 'dimension', to: 'pricing_analysis', kind: 'branch' },
  { id: 'dimension-market', from: 'dimension', to: 'market_analysis', kind: 'branch' },
  { id: 'product-qa', from: 'product_analysis', to: 'qa_analysis', kind: 'merge' },
  { id: 'pricing-qa', from: 'pricing_analysis', to: 'qa_analysis', kind: 'merge' },
  { id: 'market-qa', from: 'market_analysis', to: 'qa_analysis', kind: 'merge' },
  { id: 'analysis-strategy', from: 'qa_analysis', to: 'strategy', label: '汇总三维结论' },
  { id: 'strategy-qa', from: 'strategy', to: 'qa_strategy', label: '提交检查' },
  { id: 'qa-report', from: 'qa_strategy', to: 'report', label: '生成报告' },
]);

const BRANCH_TARGETS = ['product_analysis', 'pricing_analysis', 'market_analysis'];
const MERGE_SOURCES = ['product_analysis', 'pricing_analysis', 'market_analysis'];

function getNodeSize(node) {
  return WORKFLOW_NODE_SIZES[node?.kind] || WORKFLOW_NODE_SIZES.agent;
}

function getEdgePort(node, side, portIndex = null) {
  const size = getNodeSize(node);
  const y = portIndex === null
    ? node.y + (size.height / 2)
    : node.y + ((size.height / 4) * (portIndex + 1));
  return {
    x: side === 'source' ? node.x + size.width : node.x,
    y,
  };
}

export function getWorkflowEdgeGeometry(edge, nodesById) {
  const sourceNode = nodesById?.[edge?.from];
  const targetNode = nodesById?.[edge?.to];
  if (!sourceNode || !targetNode) return null;

  const branchIndex = edge.kind === 'branch' ? BRANCH_TARGETS.indexOf(edge.to) : -1;
  const mergeIndex = edge.kind === 'merge' ? MERGE_SOURCES.indexOf(edge.from) : -1;
  const source = getEdgePort(sourceNode, 'source', branchIndex >= 0 ? branchIndex : null);
  const target = getEdgePort(targetNode, 'target', mergeIndex >= 0 ? mergeIndex : null);
  const horizontalGap = Math.max(1, target.x - source.x);
  const controlDistance = Math.max(4, Math.min(88, horizontalGap * 0.36));
  const sourceControl = { x: source.x + controlDistance, y: source.y };
  const targetControl = { x: target.x - controlDistance, y: target.y };

  return {
    source,
    target,
    sourceControl,
    targetControl,
    path: `M ${source.x} ${source.y} C ${sourceControl.x} ${sourceControl.y}, ${targetControl.x} ${targetControl.y}, ${target.x} ${target.y}`,
  };
}

const COMPLETE_STATES = new Set(['completed', 'passed', 'degraded']);
const ACTIVE_STATES = new Set(['running', 'retrying']);
const BLOCKING_SOURCE_STATES = new Set(['failed', 'blocked']);
const BLOCKING_TARGET_EXCEPTIONS = new Set([
  'completed',
  'passed',
  'degraded',
  'failed',
  'disabled',
]);

function getQaNodeStatus(node, qaSummaries, qaDisabled) {
  return getGateState(node.targets, qaSummaries, { disabled: qaDisabled }).status;
}

function getInitialNodeStatus(node, nodeStates, qaSummaries, taskStatus, qaDisabled) {
  if (node.kind === 'input') return taskStatus === 'pending' ? 'waiting' : 'completed';
  if (node.kind === 'output') {
    if (taskStatus === 'completed') return 'completed';
    if (taskStatus === 'failed') return 'blocked';
    return 'waiting';
  }
  if (node.kind === 'qa') {
    if (qaDisabled) return 'disabled';
    const hasExplicitStatus = Object.prototype.hasOwnProperty.call(nodeStates || {}, node.id);
    const explicitStatus = nodeStates?.[node.id] || 'waiting';
    if (hasExplicitStatus && explicitStatus !== 'waiting') {
      if (taskStatus === 'completed' && explicitStatus !== 'failed') return 'completed';
      return { status: explicitStatus, explicit: true };
    }
    return getQaNodeStatus(node, qaSummaries, qaDisabled);
  }

  const hasExplicitStatus = Object.prototype.hasOwnProperty.call(nodeStates || {}, node.phase);
  const explicitStatus = nodeStates?.[node.phase] || 'waiting';
  if (taskStatus === 'completed' && explicitStatus !== 'failed') return 'completed';
  return { status: explicitStatus, explicit: hasExplicitStatus };
}

function propagateBlockedNodes(nodes, taskStatus) {
  if (taskStatus !== 'failed') return nodes;

  const next = nodes.map(node => ({ ...node }));
  const nodesById = Object.fromEntries(next.map(node => [node.id, node]));
  const failedNode = next.find(node => node.status === 'failed');
  const failedStageNumber = failedNode
    ? WORKFLOW_STAGES.find(stage => stage.id === failedNode.stage)?.number
    : null;

  if (failedStageNumber) {
    next.forEach((node) => {
      const stageNumber = WORKFLOW_STAGES.find(stage => stage.id === node.stage)?.number;
      if (
        stageNumber >= failedStageNumber
        && !BLOCKING_TARGET_EXCEPTIONS.has(node.status)
        && node.status !== 'blocked'
      ) {
        node.status = 'blocked';
      }
    });
  }

  let changed = true;

  while (changed) {
    changed = false;
    WORKFLOW_EDGES.forEach((edge) => {
      const source = nodesById[edge.from];
      const target = nodesById[edge.to];
      if (
        !source
        || !target
        || !BLOCKING_SOURCE_STATES.has(source.status)
        || BLOCKING_TARGET_EXCEPTIONS.has(target.status)
        || target.status === 'blocked'
      ) return;
      target.status = 'blocked';
      changed = true;
    });
  }

  return next;
}

function inferReadyNodes(nodes, taskStatus) {
  if (taskStatus !== 'running') return nodes;

  const nodesById = Object.fromEntries(nodes.map(node => [node.id, node]));
  return nodes.map((node) => {
    if (
      node.status !== 'waiting'
      || node.explicit
      || !['agent', 'output'].includes(node.kind)
    ) return node;
    const incoming = WORKFLOW_EDGES.filter(edge => edge.to === node.id);
    if (incoming.length === 0) return node;
    const ready = incoming.every(edge => isForwardComplete(edge.from, nodesById));
    return ready ? { ...node, status: 'running', inferred: true } : node;
  });
}

function isForwardComplete(nodeId, nodesById, visited = new Set()) {
  const node = nodesById[nodeId];
  if (!node) return false;
  if (node.status !== 'disabled') return COMPLETE_STATES.has(node.status);
  if (visited.has(nodeId)) return false;

  const incoming = WORKFLOW_EDGES.filter(edge => edge.to === nodeId);
  if (incoming.length === 0) return false;
  const nextVisited = new Set(visited);
  nextVisited.add(nodeId);
  return incoming.every(edge => isForwardComplete(edge.from, nodesById, nextVisited));
}

function deriveEdgeStatus(edge, nodesById) {
  const sourceStatus = nodesById[edge.from]?.status || 'waiting';
  const targetStatus = nodesById[edge.to]?.status || 'waiting';
  const sourceComplete = isForwardComplete(edge.from, nodesById);
  const targetComplete = isForwardComplete(edge.to, nodesById);

  if (sourceStatus === 'failed' || targetStatus === 'failed') return 'failed';
  if (sourceStatus === 'blocked' || targetStatus === 'blocked') return 'blocked';
  if (sourceStatus === 'degraded' || targetStatus === 'degraded') return 'degraded';
  if (targetStatus === 'retrying' || sourceStatus === 'retrying') return 'retrying';
  if (edge.kind === 'branch') {
    if (ACTIVE_STATES.has(targetStatus)) return 'running';
    return targetComplete ? 'completed' : 'waiting';
  }
  if (edge.kind === 'merge') {
    if (ACTIVE_STATES.has(sourceStatus)) return 'running';
    return sourceComplete ? 'completed' : 'waiting';
  }
  if (ACTIVE_STATES.has(targetStatus)) return 'running';
  if (targetComplete || sourceComplete) return 'completed';
  return ACTIVE_STATES.has(sourceStatus) ? 'running' : 'waiting';
}

export function buildWorkflowCanvasModel({
  nodeStates = {},
  qaSummaries = {},
  taskStatus = 'pending',
  qaDisabled = false,
} = {}) {
  const initialNodes = WORKFLOW_NODES.map((node) => {
    const initialState = getInitialNodeStatus(
      node,
      nodeStates,
      qaSummaries,
      taskStatus,
      qaDisabled,
    );
    return {
      ...node,
      ...(typeof initialState === 'string' ? { status: initialState } : initialState),
    };
  });
  const blockedNodes = propagateBlockedNodes(initialNodes, taskStatus);
  const nodes = inferReadyNodes(blockedNodes, taskStatus);
  const nodesById = Object.fromEntries(nodes.map(node => [node.id, node]));
  const edges = WORKFLOW_EDGES.map(edge => ({
    ...edge,
    status: deriveEdgeStatus(edge, nodesById),
  }));

  return { stages: WORKFLOW_STAGES, nodes, edges, nodesById };
}

const FOCUS_COPY = {
  1: {
    title: '正在识别竞品并建立证据',
    outcome: '完成后将得到竞品清单与可信证据',
  },
  2: {
    title: '正在确定本次分析维度',
    outcome: '完成后将得到专属比较框架',
  },
  3: {
    title: '正在并行比较产品、定价与市场',
    outcome: '完成后将得到三维竞争分析',
  },
  4: {
    title: '正在生成可执行的策略报告',
    outcome: '完成后即可查看策略建议与引用',
  },
};

export function getWorkflowFocus(options = {}) {
  const model = buildWorkflowCanvasModel(options);
  const { taskStatus = 'pending' } = options;
  let stageNumber = 1;
  let focusNode = null;

  if (taskStatus === 'completed') {
    stageNumber = 4;
  } else {
    if (taskStatus === 'failed') {
      focusNode = model.nodes.find(node => node.status === 'failed')
        || model.nodes.find(node => ACTIVE_STATES.has(node.status));
    } else if (taskStatus === 'degraded') {
      focusNode = model.nodes.find(node => node.status === 'degraded')
        || model.nodes.find(node => node.status === 'failed')
        || model.nodes.find(node => ACTIVE_STATES.has(node.status));
    } else {
      focusNode = model.nodes.find(node => ACTIVE_STATES.has(node.status))
        || model.nodes.find(node => node.status === 'failed')
        || model.nodes.find(node => node.status === 'degraded');
    }
    const activeStage = focusNode
      ? WORKFLOW_STAGES.find(stage => stage.id === focusNode.stage)
      : null;
    if (activeStage) stageNumber = activeStage.number;
  }

  const stage = WORKFLOW_STAGES.find(candidate => candidate.number === stageNumber);
  let copy = FOCUS_COPY[stageNumber];
  if (taskStatus === 'completed') {
    copy = { title: '分析流程已完成', outcome: '策略报告与全部阶段产物已就绪' };
  } else if (focusNode?.status === 'failed' || taskStatus === 'failed') {
    copy = {
      title: `分析在“${stage.label}”阶段中断`,
      outcome: '已定位失败节点，可查看详情后重新处理',
    };
  } else if (focusNode?.status === 'degraded' || taskStatus === 'degraded') {
    copy = {
      title: `“${stage.label}”存在质量风险`,
      outcome: '可查看质检说明，确认风险后继续处理',
    };
  }

  return {
    stageNumber,
    progressLabel: `第 ${stageNumber} / 4 步`,
    ...copy,
  };
}

export function shouldResetWorkflowSelection(previousTaskStatus, nextTaskStatus) {
  return previousTaskStatus !== 'completed' && nextTaskStatus === 'completed';
}

export function clampCanvasZoom(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return WORKFLOW_DEFAULT_ZOOM;
  return Math.min(1.4, Math.max(0.6, Math.round(numeric * 100) / 100));
}

export function getWorkflowInitialZoom(viewportWidth) {
  const width = Number(viewportWidth);
  if (Number.isFinite(width) && width > 0 && width <= WORKFLOW_MOBILE_BREAKPOINT) {
    return WORKFLOW_MOBILE_DEFAULT_ZOOM;
  }
  return WORKFLOW_DEFAULT_ZOOM;
}

export function getWorkflowStageScrollLeft(stage, zoom, viewportWidth) {
  const width = Number(viewportWidth);
  if (!stage?.bounds || !Number.isFinite(width) || width <= 0) return 0;

  const scale = clampCanvasZoom(zoom);
  const stageStart = stage.bounds.x * scale;
  const stageWidth = stage.bounds.width * scale;
  const sceneWidth = WORKFLOW_CANVAS_SIZE.width * scale;
  const maxScrollLeft = Math.max(0, sceneWidth - width);
  let desiredScrollLeft = stageStart + (stageWidth / 2) - (width / 2);

  if (stage.number === 1) {
    desiredScrollLeft = stageStart - 16;
  } else if (stage.number === WORKFLOW_STAGES.length) {
    desiredScrollLeft = stageStart + stageWidth - width + 16;
  }

  return Math.round(Math.min(maxScrollLeft, Math.max(0, desiredScrollLeft)));
}

export function scheduleWorkflowStageFocus({
  stage,
  zoom,
  viewportWidth,
  focusedStageRef,
  scheduleFrame,
  applyFocus,
}) {
  if (
    !stage
    || !focusedStageRef
    || focusedStageRef.current === stage.number
    || typeof scheduleFrame !== 'function'
    || typeof applyFocus !== 'function'
  ) return null;

  return scheduleFrame(() => {
    applyFocus({
      stageId: stage.id,
      stageNumber: stage.number,
      scrollLeft: getWorkflowStageScrollLeft(stage, zoom, viewportWidth),
    });
    focusedStageRef.current = stage.number;
  });
}

export function getWorkflowScrollBehavior(prefersReducedMotion, animate = true) {
  return prefersReducedMotion || !animate ? 'auto' : 'smooth';
}

export function getWorkflowNodeAction(node, taskStatus) {
  if (!node) return null;
  if (node.kind === 'agent') {
    return { kind: 'artifact', phase: node.phase, label: '查看阶段产物' };
  }
  if (node.kind === 'output' && taskStatus === 'completed') {
    return { kind: 'report', label: '查看策略报告' };
  }
  return null;
}

export function getStageZoneStyle(stage) {
  const { x, y, width, height } = stage?.bounds || {};
  return { left: x, top: y, width, height };
}
