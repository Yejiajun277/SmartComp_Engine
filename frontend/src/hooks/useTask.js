import { useState, useCallback } from 'react';

const AGENT_PHASE_MAP = {
  discovery: { label: '竞品发现', agent: 'DiscoveryAgent' },
  collection: { label: '数据采集', agent: 'CollectionAgent' },
  dimension: { label: '维度配置', agent: 'DimensionAgent' },
  product_analysis: { label: '功能分析', agent: 'ProductAgent' },
  pricing_analysis: { label: '定价分析', agent: 'PricingAgent' },
  market_analysis: { label: '市场分析', agent: 'MarketAgent' },
  strategy: { label: '报告生成', agent: 'StrategyAgent' },
  finalize: { label: '最终整理', agent: 'Orchestrator' },
};

const INITIAL_NODE_STATES = {
  discovery: 'waiting',
  collection: 'waiting',
  dimension: 'waiting',
  product_analysis: 'waiting',
  pricing_analysis: 'waiting',
  market_analysis: 'waiting',
  strategy: 'waiting',
};

const QA_PHASE_TO_NODE = {
  collection: 'collection',
  product: 'product_analysis',
  pricing: 'pricing_analysis',
  market: 'market_analysis',
  strategy: 'strategy',
};

function summarizeQaResults(results) {
  const summaries = {};

  results.forEach((result) => {
    const phase = result.phase;
    const nodeKey = QA_PHASE_TO_NODE[phase];
    if (!nodeKey) return;

    const current = summaries[nodeKey] || { retryCount: 0, checks: [] };
    if (result.running) {
      summaries[nodeKey] = {
        phase,
        label: '质检中',
        status: 'running',
        score: result.score,
        retryCount: current.retryCount,
        checks: [...current.checks, result],
      };
      return;
    }

    const failedCount = current.retryCount + (result.passed ? 0 : 1);
    const label = result.degraded
      ? `降级通过，打回 ${failedCount} 次`
      : result.passed
        ? `通过${result.score != null ? ` ${Math.round(result.score)}分` : ''}`
        : `未通过，打回 ${failedCount} 次`;

    summaries[nodeKey] = {
      phase,
      label,
      status: result.degraded ? 'degraded' : result.passed ? 'passed' : 'failed',
      score: result.score,
      retryCount: failedCount,
      checks: [...current.checks, result],
    };
  });

  return summaries;
}

function normalizeQaResult(event) {
  const fromPayload = event.data?.qa_result;
  if (fromPayload) {
    return {
      ...fromPayload,
      message: event.message,
    };
  }
  return {
    phase: event.phase,
    target_agent: event.data?.target_agent,
    passed: event.type === 'qa_check_passed',
    score: event.data?.score,
    attempt: event.data?.attempt,
    degraded: event.data?.degraded,
    issues: event.data?.issues || [],
    feedback_to_agent: event.data?.feedback_to_agent,
    hallucination_status: event.data?.hallucination_status,
    hallucination_score: event.data?.hallucination_score,
    accuracy_rate: event.data?.accuracy_rate,
    coverage_rate: event.data?.coverage_rate,
    correction_count: event.data?.correction_count,
    total_fields: event.data?.total_fields,
    message: event.message,
  };
}

export function useTask() {
  const [events, setEvents] = useState([]);
  const [nodeStates, setNodeStates] = useState({ ...INITIAL_NODE_STATES });
  const [progress, setProgress] = useState(0);
  const [currentMessage, setCurrentMessage] = useState('');
  const [qaResults, setQaResults] = useState([]);
  const [taskStatus, setTaskStatus] = useState('pending');
  const [llmLogsKey, setLlmLogsKey] = useState(0);
  const [intervention, setIntervention] = useState(null);

  const handleEvent = useCallback((event) => {
    console.log('[useTask] handleEvent:', event.type, event.phase, event.progress);
    setEvents(prev => [...prev, event]);

    if (event.progress) setProgress(event.progress);
    if (event.message) setCurrentMessage(event.message);

    // Update node states based on event type
    const phase = event.phase;
    if (phase && Object.prototype.hasOwnProperty.call(INITIAL_NODE_STATES, phase)) {
      if (event.type === 'agent_started') {
        setNodeStates(prev => ({ ...prev, [phase]: 'running' }));
      } else if (event.type === 'agent_completed') {
        setNodeStates(prev => ({ ...prev, [phase]: 'completed' }));
      } else if (event.type === 'agent_failed') {
        setNodeStates(prev => ({ ...prev, [phase]: 'failed' }));
      }
    }

    // Handle QA events
    if (event.type === 'qa_check_started') {
      setQaResults(prev => [...prev, {
        phase: event.phase,
        target_agent: event.data?.target_agent,
        attempt: event.data?.attempt,
        running: true,
        message: event.message,
      }]);
      return;
    } else if (event.type === 'qa_check_passed' || event.type === 'qa_check_failed') {
      const nodeKey = QA_PHASE_TO_NODE[event.phase];
      const result = normalizeQaResult(event);
      setQaResults(prev => [
        ...prev.filter(item => !(
          item.running
          && item.phase === result.phase
          && (item.attempt == null || result.attempt == null || item.attempt === result.attempt)
        )),
        result,
      ]);
      if (event.type === 'qa_check_failed' && nodeKey) {
        setNodeStates(prev => ({ ...prev, [nodeKey]: 'retrying' }));
      } else if (event.type === 'qa_check_passed' && nodeKey) {
        setNodeStates(prev => ({ ...prev, [nodeKey]: 'completed' }));
      }
    } else if (event.type === 'qa_retrying') {
      const nodeKey = QA_PHASE_TO_NODE[event.phase];
      if (nodeKey) {
        setNodeStates(prev => ({ ...prev, [nodeKey]: 'retrying' }));
      }
    }

    // Handle LLM logs update
    if (event.type === 'llm_logs_updated') {
      setLlmLogsKey(prev => prev + 1);
    }

    // Handle intervention events
    if (event.type === 'intervention_required') {
      setIntervention({
        type: event.data?.intervention_type || event.phase,
        message: event.message,
        data: event.data,
      });
    } else if (event.type === 'intervention_submitted') {
      setIntervention(null);
    }

    // Handle task completion
    if (event.type === 'task_started') {
      setTaskStatus('running');
    } else if (event.type === 'task_completed') {
      // 检查是否是降级通过
      const isDegraded = event.data?.degraded || event.status === 'completed_degraded';
      setTaskStatus(isDegraded ? 'completed_degraded' : 'completed');
      setProgress(1.0);
      // 兜底：任务完成时，所有仍在 waiting 的节点自动标记为 completed
      setNodeStates(prev => {
        const updated = { ...prev };
        Object.keys(updated).forEach(key => {
          if (updated[key] === 'waiting') {
            updated[key] = 'completed';
          }
        });
        return updated;
      });
    } else if (event.type === 'task_failed') {
      setTaskStatus('failed');
    }
  }, []);

  const reset = useCallback(() => {
    setEvents([]);
    setNodeStates({ ...INITIAL_NODE_STATES });
    setProgress(0);
    setCurrentMessage('');
    setQaResults([]);
    setTaskStatus('pending');
    setLlmLogsKey(0);
    setIntervention(null);
  }, []);

  return {
    events,
    nodeStates,
    progress,
    currentMessage,
    qaResults,
    qaSummaries: summarizeQaResults(qaResults),
    taskStatus,
    llmLogsKey,
    intervention,
    setIntervention,
    handleEvent,
    reset,
    AGENT_PHASE_MAP,
  };
}
