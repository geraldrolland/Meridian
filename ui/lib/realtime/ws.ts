import { getAccessToken, refreshAccessToken } from "@/lib/auth/token-store";
import type { WsAbrRecommendation, WsNotification } from "@/lib/types";

export type WsStatus = "connecting" | "open" | "closed" | "error";

/** One backoff delay per reconnect attempt, in ms — 5 retries max. */
const RETRY_DELAYS_MS = [5000, 10000, 15000, 20000, 25000] as const;
const JITTER_RATIO = 0.1;

/** 5000 -> 4500..5500, 10000 -> 9000..11000, … so retries do not sync up. */
function withJitter(base: number): number {
  return base * (1 - JITTER_RATIO + Math.random() * 2 * JITTER_RATIO);
}

export interface VideoWsHandle {
  close: () => void;
  status: () => WsStatus;
  /** Send a JSON frame to the video service; false if the socket is not open. */
  send: (payload: unknown) => boolean;
}

/**
 * A frame arrives as string, Blob or ArrayBuffer depending on its opcode, so
 * a proxy that re-frames text as binary must not make us drop the notification.
 */
async function frameToText(data: unknown): Promise<string> {
  if (typeof data === "string") return data;
  if (data instanceof Blob) return data.text();
  if (data instanceof ArrayBuffer || ArrayBuffer.isView(data)) {
    return new TextDecoder().decode(data);
  }
  return "";
}

export function connectVideoWs(
  onMessage: (msg: WsNotification) => void,
  onStatus?: (s: WsStatus) => void,
  onAbr?: (msg: WsAbrRecommendation) => void,
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
      if (closed) return;
      // A missing token is a failed attempt too: it burns one of the 5 retries.
      scheduleReconnect();
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

    socket.onmessage = async (event) => {
      try {
        const data = JSON.parse(await frameToText(event.data)) as
          | (WsNotification & { type?: string })
          | WsAbrRecommendation;
        if (!data || !data.video_id) return;
        if (data.type === "abr_recommendation") {
          onAbr?.(data as WsAbrRecommendation);
          return;
        }
        onMessage(data as WsNotification);
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
    const delay = RETRY_DELAYS_MS[attempt];
    if (delay === undefined) {
      // Budget of MAX_RETRIES exhausted — stay offline until remount.
      setStatus("error");
      return;
    }
    attempt += 1;
    timer = setTimeout(() => {
      timer = null;
      void open();
    }, withJitter(delay));
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
    send: (payload: unknown) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return false;
      try {
        ws.send(JSON.stringify(payload));
        return true;
      } catch {
        return false;
      }
    },
  };
}
