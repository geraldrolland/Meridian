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

  const getUrl = (token: string) => {
    const base = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:3001";
    return (
      base.replace(/^http/, "ws") +
      "/ws/video/notification?token=" +
      encodeURIComponent(token)
    );
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

    let socket: WebSocket;
    try {
      socket = new WebSocket(getUrl(token));
    } catch {
      scheduleReconnect();
      return;
    }
    ws = socket;

    socket.onopen = () => {
      if (closed) {
        socket.close();
        return;
      }
      attempt = 0;
      setStatus("open");
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as WsNotification;
        if (data && data.video_id) onMessage(data);
      } catch {
        /* ignore non-json */
      }
    };

    socket.onerror = () => {
      if (!closed) setStatus("error");
    };

    socket.onclose = async (e) => {
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
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      const socket = ws;
      ws = null;
      if (socket) {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onerror = null;
        socket.onclose = null;
        if (socket.readyState === WebSocket.CONNECTING) {
          socket.addEventListener("open", () => socket.close(), {
            once: true,
          });
        } else {
          try {
            socket.close();
          } catch {
            /* ignore */
          }
        }
      }
      setStatus("closed");
    },
    status: () => status,
  };
}
