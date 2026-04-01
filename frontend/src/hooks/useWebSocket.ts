import { useEffect, useRef, useState } from 'react';
import { notification } from 'antd';
import { useWsStore } from '../stores/wsStore';
import type { WsChannel } from '../stores/wsStore';

interface WsMessage {
  channel: WsChannel | 'alert_notification';
  data: unknown[] | AlertNotificationData;
}

interface AlertNotificationData {
  title: string;
  message: string;
  sound_enabled?: boolean;
  popup_enabled?: boolean;
}

function isAlertNotification(data: unknown): data is AlertNotificationData {
  return (
    typeof data === 'object' &&
    data !== null &&
    'title' in data &&
    'message' in data
  );
}

export function useWebSocket(token?: string | null) {
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const tokenRef = useRef(token);
  const retriesRef = useRef(0);
  tokenRef.current = token;

  useEffect(() => {
    let cancelled = false;

    // Request system notification permission on load
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }

    function connect() {
      if (cancelled) return;
      // Prevent duplicate connections
      const cur = wsRef.current;
      if (cur && (cur.readyState === WebSocket.OPEN || cur.readyState === WebSocket.CONNECTING)) {
        return;
      }

      const params = tokenRef.current ? `?token=${tokenRef.current}` : '';
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${protocol}//${window.location.host}/arbitrage/ws${params}`);

      wsRef.current = ws;
      setStatus('connecting');

      ws.onopen = () => {
        if (cancelled) { ws.close(); return; }
        retriesRef.current = 0;
        setStatus('connected');
      };

      ws.onmessage = (event) => {
        try {
          const msg: WsMessage = JSON.parse(event.data);

          if (msg.channel === 'alert_notification' && isAlertNotification(msg.data)) {
            const alertData = msg.data;

            if (alertData.popup_enabled !== false) {
              // System-level notification (appears on top of all windows)
              if ('Notification' in window && Notification.permission === 'granted') {
                new Notification(alertData.title, {
                  body: alertData.message,
                  requireInteraction: true, // Must click to dismiss
                });
              } else if ('Notification' in window && Notification.permission !== 'denied') {
                Notification.requestPermission().then((perm) => {
                  if (perm === 'granted') {
                    new Notification(alertData.title, {
                      body: alertData.message,
                      requireInteraction: true,
                    });
                  }
                });
              }
              // Also show in-page notification as fallback
              notification.warning({
                message: alertData.title,
                description: alertData.message,
                duration: 0,
                placement: 'topRight',
              });
            }

            if (alertData.sound_enabled !== false) {
              const audio = new Audio('/alert.wav');
              audio.play().catch(() => {});
            }

            return;
          }

          if (msg.channel && Array.isArray(msg.data)) {
            useWsStore.getState().setData(msg.channel as WsChannel, msg.data);
          }
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setStatus('disconnected');
        wsRef.current = null;
        // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
        const delay = Math.min(1000 * Math.pow(2, retriesRef.current), 30000);
        retriesRef.current += 1;
        reconnectTimer.current = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        // onclose will fire after this
        ws.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer.current);
      const ws = wsRef.current;
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onclose = null;
        ws.onerror = null;
        ws.close();
        wsRef.current = null;
      }
    };
  }, []); // Only connect once on mount

  return { status };
}
