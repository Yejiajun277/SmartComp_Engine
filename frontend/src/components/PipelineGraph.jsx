import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AppstoreOutlined,
  BarChartOutlined,
  BranchesOutlined,
  CheckCircleFilled,
  FileSearchOutlined,
  FileTextOutlined,
  FullscreenOutlined,
  MinusOutlined,
  PlusOutlined,
  ProductOutlined,
  RadarChartOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  SettingOutlined,
  TagOutlined,
} from '@ant-design/icons';
import {
  WORKFLOW_CANVAS_SIZE,
  WORKFLOW_DEFAULT_ZOOM,
  WORKFLOW_MOBILE_BREAKPOINT,
  WORKFLOW_MOBILE_DEFAULT_ZOOM,
  buildWorkflowCanvasModel,
  clampCanvasZoom,
  getStageZoneStyle,
  getWorkflowEdgeGeometry,
  getWorkflowFocus,
  getWorkflowInitialZoom,
  getWorkflowNodeAction,
  getWorkflowScrollBehavior,
  getWorkflowStageScrollLeft,
  scheduleWorkflowStageFocus,
  shouldResetWorkflowSelection,
} from '../utils/workflowCanvas';

function prefersReducedMotion() {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

const STATUS_LABELS = {
  waiting: '等待接力',
  running: '正在运行',
  completed: '已完成',
  passed: '已通过',
  retrying: '正在重做',
  degraded: '带风险交付',
  failed: '需要处理',
  blocked: '已阻断',
  disabled: '质检已关闭',
};

const NODE_ICONS = {
  input: <ProductOutlined />,
  discovery: <SearchOutlined />,
  collection: <FileSearchOutlined />,
  qa_collection: <SafetyCertificateOutlined />,
  dimension: <AppstoreOutlined />,
  product_analysis: <ProductOutlined />,
  pricing_analysis: <TagOutlined />,
  market_analysis: <BarChartOutlined />,
  qa_analysis: <SafetyCertificateOutlined />,
  strategy: <RadarChartOutlined />,
  qa_strategy: <SafetyCertificateOutlined />,
  report: <FileTextOutlined />,
};

const EDGE_STATUSES = [
  'waiting',
  'running',
  'completed',
  'retrying',
  'degraded',
  'failed',
  'blocked',
];

function getStageStatus(stage, nodesById) {
  const statuses = stage.nodeIds.map(id => nodesById[id]?.status || 'waiting');
  if (statuses.includes('failed')) return 'failed';
  if (statuses.includes('degraded')) return 'degraded';
  if (statuses.includes('retrying')) return 'retrying';
  if (statuses.includes('running')) return 'running';
  if (statuses.includes('blocked')) return 'blocked';
  if (statuses.every(status => ['completed', 'passed', 'disabled'].includes(status))) return 'completed';
  return 'waiting';
}

function WorkflowEdgeLayer({ edges, nodesById }) {
  return (
    <svg
      className="dag-edge-layer"
      width={WORKFLOW_CANVAS_SIZE.width}
      height={WORKFLOW_CANVAS_SIZE.height}
      viewBox={`0 0 ${WORKFLOW_CANVAS_SIZE.width} ${WORKFLOW_CANVAS_SIZE.height}`}
      aria-hidden="true"
    >
      <defs>
        {EDGE_STATUSES.map(status => (
          <marker
            id={`dag-arrow-${status}`}
            key={status}
            markerWidth="8"
            markerHeight="8"
            refX="7"
            refY="4"
            orient="auto"
          >
            <path className={`dag-arrow-head edge-${status}`} d="M 0 0 L 8 4 L 0 8 z" />
          </marker>
        ))}
      </defs>
      {edges.map((edge) => {
        const geometry = getWorkflowEdgeGeometry(edge, nodesById);
        if (!geometry) return null;
        const { path, source, target } = geometry;
        return (
          <g className="dag-edge" data-status={edge.status} key={edge.id}>
            <path className="dag-edge-track" d={path} />
            <path
              className="dag-edge-signal"
              d={path}
              markerEnd={`url(#dag-arrow-${edge.status})`}
            />
            {edge.label && (
              <text
                className="dag-edge-label"
                x={(source.x + target.x) / 2}
                y={(source.y + target.y) / 2 - 13}
                textAnchor="middle"
              >
                {edge.label}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function WorkflowStageLayer({ stages, nodesById }) {
  return (
    <div className="dag-stage-layer" aria-hidden="true">
      {stages.map((stage) => {
        const status = getStageStatus(stage, nodesById);
        return (
          <div
            className="dag-stage-zone"
            data-status={status}
            key={stage.id}
            style={getStageZoneStyle(stage)}
          >
            <span className="dag-stage-zone-number">0{stage.number}</span>
            <span>
              <strong>{stage.label}</strong>
              <small>{stage.outcome}</small>
            </span>
          </div>
        );
      })}
    </div>
  );
}

function WorkflowNode({ node, selected, onSelect }) {
  const statusLabel = node.kind === 'output' && node.status === 'blocked'
    ? '未生成'
    : (STATUS_LABELS[node.status] || STATUS_LABELS.waiting);
  return (
    <button
      className={`dag-node dag-node-${node.kind}`}
      data-status={node.status}
      data-selected={selected ? 'true' : 'false'}
      style={{ left: node.x, top: node.y }}
      type="button"
      onClick={() => onSelect(node.id)}
      aria-label={`${node.label}，${statusLabel}${selected ? '，已选中' : ''}`}
    >
      <span className="dag-node-icon" aria-hidden="true">{NODE_ICONS[node.id]}</span>
      <span className="dag-node-copy">
        <strong>{node.label}</strong>
        <small>{node.kind === 'qa' ? '可信度检查' : statusLabel}</small>
      </span>
      <span className="dag-node-state" aria-hidden="true">
        {['completed', 'passed'].includes(node.status) ? <CheckCircleFilled /> : <i />}
      </span>
      {node.output && node.kind !== 'qa' && (
        <span className="dag-node-output">{node.output}</span>
      )}
    </button>
  );
}

function WorkflowMinimap({ stages, nodes, selectedNodeId, onStageSelect }) {
  return (
    <div className="dag-minimap" aria-label="工作流缩略图">
      <div className="dag-minimap-map">
        {stages.map(stage => (
          <button
            key={stage.id}
            type="button"
            aria-label={`定位到${stage.label}`}
            className="dag-minimap-stage"
            style={{
              left: `${(stage.bounds.x / WORKFLOW_CANVAS_SIZE.width) * 100}%`,
              width: `${(stage.bounds.width / WORKFLOW_CANVAS_SIZE.width) * 100}%`,
            }}
            onClick={() => onStageSelect(stage)}
          />
        ))}
        {nodes.map(node => (
          <i
            key={node.id}
            className="dag-minimap-node"
            data-status={node.status}
            data-selected={node.id === selectedNodeId ? 'true' : 'false'}
            style={{
              left: `${(node.x / WORKFLOW_CANVAS_SIZE.width) * 100}%`,
              top: `${(node.y / WORKFLOW_CANVAS_SIZE.height) * 100}%`,
            }}
          />
        ))}
      </div>
      <span>点击阶段快速定位</span>
    </div>
  );
}

function WorkflowInspector({ node, taskStatus, onNodeClick, onReportClick }) {
  if (!node) return null;
  const action = getWorkflowNodeAction(node, taskStatus);
  const statusLabel = node.kind === 'output' && node.status === 'blocked'
    ? '未生成'
    : (STATUS_LABELS[node.status] || STATUS_LABELS.waiting);

  const handleAction = () => {
    if (action?.kind === 'artifact') onNodeClick?.(action.phase);
    if (action?.kind === 'report') onReportClick?.();
  };

  return (
    <aside className="dag-inspector" data-status={node.status} aria-live="polite">
      <header>
        <span className="dag-inspector-kicker">当前选中节点</span>
        <div className="dag-inspector-title">
          <span>{NODE_ICONS[node.id]}</span>
          <div>
            <h3>{node.label}</h3>
            <p>{node.agent || (node.kind === 'qa' ? 'QualityAgent' : 'Workflow')}</p>
          </div>
        </div>
        <span className="dag-inspector-status"><i />{statusLabel}</span>
      </header>
      <div className="dag-inspector-section">
        <span>这一步在做什么</span>
        <p>{node.description}</p>
      </div>
      <div className="dag-inspector-section">
        <span>完成后得到</span>
        <strong>{node.output}</strong>
      </div>
      {node.kind === 'qa' && (
        <div className="dag-inspector-qa-note">
          <SafetyCertificateOutlined />
          <p>未通过时，只返回对应 Agent 修正，再重新检查，不会让全部流程从头开始。</p>
        </div>
      )}
      {action && (
        <button className="dag-inspector-action" type="button" onClick={handleAction}>
          {action.label}
        </button>
      )}
      {!action && node.kind === 'output' && taskStatus !== 'completed' && (
        <p className="dag-inspector-waiting">
          {node.status === 'blocked'
            ? '上游节点执行失败，本次报告尚未生成。'
            : '流程完成后可在这里打开最终报告。'}
        </p>
      )}
    </aside>
  );
}

export default function PipelineGraph({
  nodeStates = {},
  qaSummaries = {},
  taskStatus = 'pending',
  qaDisabled = false,
  onNodeClick,
  onReportClick,
}) {
  const viewportRef = useRef(null);
  const stageNavRef = useRef(null);
  const lastAutoFocusedStageRef = useRef(null);
  const [selection, setSelection] = useState({ nodeId: null, taskStatus: null });
  const [mobileView, setMobileView] = useState(() => (
    typeof window !== 'undefined' && window.innerWidth <= WORKFLOW_MOBILE_BREAKPOINT
  ));
  const [zoom, setZoom] = useState(() => getWorkflowInitialZoom(
    typeof window === 'undefined' ? undefined : window.innerWidth,
  ));
  const model = useMemo(() => buildWorkflowCanvasModel({
    nodeStates,
    qaSummaries,
    taskStatus,
    qaDisabled,
  }), [nodeStates, qaDisabled, qaSummaries, taskStatus]);
  const focus = useMemo(() => getWorkflowFocus({
    nodeStates,
    qaSummaries,
    taskStatus,
    qaDisabled,
  }), [nodeStates, qaDisabled, qaSummaries, taskStatus]);
  const activeNode = taskStatus === 'completed'
    ? model.nodesById.report
    : (model.nodes.find(node => ['running', 'retrying', 'failed'].includes(node.status))
      || model.nodes.find(node => node.status === 'degraded')
      || model.nodes.at(-1));
  const selectedNode = shouldResetWorkflowSelection(selection.taskStatus, taskStatus)
    ? model.nodesById.report
    : (model.nodesById[selection.nodeId] || activeNode);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined;
    const mediaQuery = window.matchMedia(`(max-width: ${WORKFLOW_MOBILE_BREAKPOINT}px)`);
    const handleViewportChange = (event) => {
      setMobileView(event.matches);
      setZoom(currentZoom => (
        [WORKFLOW_DEFAULT_ZOOM, WORKFLOW_MOBILE_DEFAULT_ZOOM].includes(currentZoom)
          ? (event.matches ? WORKFLOW_MOBILE_DEFAULT_ZOOM : WORKFLOW_DEFAULT_ZOOM)
          : currentZoom
      ));
      lastAutoFocusedStageRef.current = null;
    };
    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', handleViewportChange);
      return () => mediaQuery.removeEventListener('change', handleViewportChange);
    }
    mediaQuery.addListener?.(handleViewportChange);
    return () => mediaQuery.removeListener?.(handleViewportChange);
  }, []);

  useEffect(() => {
    if (!mobileView || lastAutoFocusedStageRef.current === focus.stageNumber) return undefined;
    const stage = model.stages.find(candidate => candidate.number === focus.stageNumber);
    if (!stage || !viewportRef.current) return undefined;

    const frameId = scheduleWorkflowStageFocus({
      stage,
      zoom,
      viewportWidth: viewportRef.current.clientWidth,
      focusedStageRef: lastAutoFocusedStageRef,
      scheduleFrame: callback => window.requestAnimationFrame(callback),
      applyFocus: ({ stageId, scrollLeft }) => {
        const behavior = getWorkflowScrollBehavior(prefersReducedMotion(), false);
        viewportRef.current?.scrollTo({ left: scrollLeft, behavior });
        stageNavRef.current
          ?.querySelector(`[data-stage-id="${stageId}"]`)
          ?.scrollIntoView({ behavior, block: 'nearest', inline: 'center' });
      },
    });
    if (frameId === null) return undefined;
    return () => window.cancelAnimationFrame(frameId);
  }, [focus.stageNumber, mobileView, model.stages, zoom]);

  const setNextZoom = value => setZoom(clampCanvasZoom(value));

  const handleStageSelect = (stage) => {
    const stageNodes = stage.nodeIds.map(id => model.nodesById[id]).filter(Boolean);
    const targetNode = stageNodes.find(node => ['running', 'retrying', 'failed'].includes(node.status))
      || stageNodes.find(node => node.status === 'waiting')
      || stageNodes.at(-1);
    if (targetNode) setSelection({ nodeId: targetNode.id, taskStatus });
    const behavior = getWorkflowScrollBehavior(prefersReducedMotion());
    if (viewportRef.current) {
      viewportRef.current.scrollTo({
        left: getWorkflowStageScrollLeft(stage, zoom, viewportRef.current.clientWidth),
        behavior,
      });
    }
    stageNavRef.current
      ?.querySelector(`[data-stage-id="${stage.id}"]`)
      ?.scrollIntoView({ behavior, block: 'nearest', inline: 'center' });
  };

  return (
    <div className="workflow-canvas" data-mobile={mobileView ? 'true' : 'false'}>
      <div className="workflow-focus-strip">
        <span className="workflow-focus-step">{focus.progressLabel}</span>
        <div>
          <strong>{focus.title}</strong>
          <p>{focus.outcome}</p>
        </div>
        <BranchesOutlined aria-hidden="true" />
      </div>

      <nav className="workflow-stage-nav" aria-label="工作流阶段" ref={stageNavRef}>
        {model.stages.map(stage => (
          <button
            key={stage.id}
            type="button"
            data-stage-id={stage.id}
            data-status={getStageStatus(stage, model.nodesById)}
            data-current={stage.number === focus.stageNumber ? 'true' : 'false'}
            data-selected={stage.id === selectedNode.stage ? 'true' : 'false'}
            aria-current={stage.number === focus.stageNumber ? 'step' : undefined}
            onClick={() => handleStageSelect(stage)}
          >
            <span>0{stage.number}</span>
            <strong>{stage.label}</strong>
          </button>
        ))}
      </nav>

      <div className="workflow-canvas-toolbar">
        <div>
          <span className="canvas-toolbar-label">静态执行图</span>
          <small>点击节点查看职责、产物与当前状态</small>
        </div>
        <div className="canvas-toolbar-actions">
          <span className="canvas-zoom-group">
            <button type="button" aria-label="缩小画布" onClick={() => setNextZoom(zoom - 0.1)}>
              <MinusOutlined />
            </button>
            <strong>{Math.round(zoom * 100)}%</strong>
            <button type="button" aria-label="放大画布" onClick={() => setNextZoom(zoom + 0.1)}>
              <PlusOutlined />
            </button>
          </span>
          <button
            type="button"
            onClick={() => setNextZoom(
              mobileView ? WORKFLOW_MOBILE_DEFAULT_ZOOM : WORKFLOW_DEFAULT_ZOOM,
            )}
            title="重置画布"
          >
            <FullscreenOutlined /><span className="canvas-reset-label">重置</span>
          </button>
        </div>
      </div>

      <div className="workflow-canvas-layout">
        <div className="workflow-canvas-frame">
          <div className="workflow-canvas-viewport" ref={viewportRef}>
            <div
              className="workflow-canvas-scaled"
              style={{
                width: WORKFLOW_CANVAS_SIZE.width * zoom,
                height: WORKFLOW_CANVAS_SIZE.height * zoom,
              }}
            >
              <div
                className="workflow-canvas-scene"
                style={{
                  width: WORKFLOW_CANVAS_SIZE.width,
                  height: WORKFLOW_CANVAS_SIZE.height,
                  transform: `scale(${zoom})`,
                }}
              >
                <WorkflowStageLayer
                  stages={model.stages}
                  nodesById={model.nodesById}
                />
                <WorkflowEdgeLayer edges={model.edges} nodesById={model.nodesById} />
                <div className="dag-node-layer">
                  {model.nodes.map(node => (
                    <WorkflowNode
                      key={node.id}
                      node={node}
                      selected={node.id === selectedNode.id}
                      onSelect={nodeId => setSelection({ nodeId, taskStatus })}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
          <WorkflowMinimap
            stages={model.stages}
            nodes={model.nodes}
            selectedNodeId={selectedNode.id}
            onStageSelect={handleStageSelect}
          />
          <span className="workflow-mobile-stage-hint">左右滑动 · 点击阶段快速定位</span>
          <span className="workflow-canvas-pan-hint"><SettingOutlined /> 横向滚动查看完整流程</span>
        </div>
        <WorkflowInspector
          node={selectedNode}
          taskStatus={taskStatus}
          onNodeClick={onNodeClick}
          onReportClick={onReportClick}
        />
      </div>
    </div>
  );
}
