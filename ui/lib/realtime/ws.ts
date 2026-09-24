import { getAccessToken, refreshAccessToken } from "@/lib/auth/token-store";
import type { WsNotification } from "@/lib/types";

export type WsStatus = "connecting" | "open" | "closed" | "error";

export interface VideoWsHandle {
  close: () => void;
  status: () => WsStatus;
}

export function connectVideoWs(
  onMessage: (msg: WsNotification) => void,
  onStatus?: (s: WsStatus) => void,
): VideoWsHandle {
  let ws: WebSocket | null = null;
  let closed = false;
  let attempt = 0;
  let status: WsStatus = "connecting";
  let timer: ReturnType<typeof setTimeout> | null = null;

  const setStatus = (s: WsStatus) => {
    status = s;
    onStatus?.(s);
  };

  const getUrl = () => {
    const base = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:3001";
    return base.replace(/^http/, "ws") + "/ws/video/notification";
  };

  const open = async () => {
    if (closed) return;
    setStatus("connecting");
    let token = getAccessToken();
    if (!token) token = await refreshAccessToken();
    if (!token || closed) {
      setStatus("error");
      return;
    }

    try {
      ws = new WebSocket(getUrl());
    } catch {
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      attempt = 0;
      setStatus("open");
      try {
        ws?.send("auth");
      } catch {
        /* browsers may not allow custom headers on WS; gateway validates upgrade */
      }
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as WsNotification;
        if (data && data.video_id) onMessage(data);
      } catch {
        /* ignore non-json */
      }
    };

    ws.onerror = () => setStatus("error");

    ws.onclose = async (e) => {
      if (closed) return;
      setStatus("closed");
      if (e.code === 4001) {
        await refreshAccessToken();
      }
      scheduleReconnect();
    };
  };

  const scheduleReconnect = () => {
    if (closed) return;
    const delay = Math.min(15000, 1000 * 2 ** attempt);
    attempt += 1;
    timer = setTimeout(() => {
      void open();
    }, delay);
  };

  void open();

  return {
    close: () => {
      closed = true;
      if (timer) clearTimeout(timer);
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
      setStatus("closed");
    },
    status: () => status,
  };
}
