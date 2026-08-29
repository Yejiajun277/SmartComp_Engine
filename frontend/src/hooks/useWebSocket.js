import { useEffect, useRef, useState } from 'react';
import { shouldAcceptTaskEvent } from '../utils/taskEvents';

export function useWebSocket(taskId, onEvent) {
  const wsRef = useRef(null);
  const onEventRef = useRef(onEvent);
  const [connected, setConnected] = useState(false);

  // Keep callback ref current without causing re-renders
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!taskId) return;

    let closed = false;
    let finished = false;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/tasks/${taskId}`;

    function connect() {
      if (closed || finished) return;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!closed) setConnected(true);
      };

      ws.onmessage = (msg) => {
        try {
          const event = JSON.parse(msg.data);
          if (!shouldAcceptTaskEvent(event, taskId, closed)) return;
          console.log('[WS] received:', event.type, event.agent, event.phase);
          onEventRef.current?.(event);
          // Stop reconnecting once task reaches terminal state
          if (event.type === 'task_completed' || event.type === 'task_failed') {
            finished = true;
          }
        } catch (err) {
          console.error('[WS] parse error:', err);
        }
      };

      ws.onclose = () => {
        if (closed) return;
        setConnected(false);
        if (!finished) {
          setTimeout(connect, 2000);
        }
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      closed = true;
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [taskId]);

  return { connected };
}
