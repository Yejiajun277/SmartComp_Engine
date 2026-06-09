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

export function useTask() {
  const [events, setEvents] = useState([]);
  const [nodeStates, setNodeStates] = useState({ ...INITIAL_NODE_STATES });
  const [progress, setProgress] = useState(0);
  const [currentMessage, setCurrentMessage] = useState('');
  const [qaResults, setQaResults] = useState([]);
  const [taskStatus, setTaskStatus] = useState('pending');

  const handleEvent = useCallback((event) => {
    console.log('[useTask] handleEvent:', event.type, event.phase, event.progress);
    setEvents(prev => [...prev, event]);

    if (event.progress) setProgress(event.progress);
    if (event.message) setCurrentMessage(event.message);

    // Update node states based on event type
    const phase = event.phase;
    if (phase && INITIAL_NODE_STATES.hasOwnProperty(phase)) {
      if (event.type === 'agent_started') {
        setNodeStates(prev => ({ ...prev, [phase]: 'running' }));
      } else if (event.type === 'agent_completed') {
        setNodeStates(prev => ({ ...prev, [phase]: 'completed' }));
      } else if (event.type === 'agent_failed') {
        setNodeStates(prev => ({ ...prev, [phase]: 'failed' }));
      }
    }

    // Handle QA events
    if (event.type === 'qa_check_passed' || event.type === 'qa_check_failed') {
      setQaResults(prev => [...prev, {
        phase: event.phase,
        passed: event.type === 'qa_check_passed',
        score: event.data?.score,
        message: event.message,
      }]);
      if (event.type === 'qa_check_failed') {
        setNodeStates(prev => ({ ...prev, [phase]: 'retrying' }));
      }
    }

    // Handle task completion
    if (event.type === 'task_completed') {
      setTaskStatus('completed');
      setProgress(1.0);
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
  }, []);

  return {
    events,
    nodeStates,
    progress,
    currentMessage,
    qaResults,
    taskStatus,
    handleEvent,
    reset,
    AGENT_PHASE_MAP,
  };
}
